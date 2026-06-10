import discord
from discord.ext import commands, tasks
import asyncio
import os
import random
import time
from collections import deque
from datetime import datetime, timedelta
import sqlite3
from aiohttp import web

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="?", intents=intents, help_command=None, case_insensitive=True)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "bot_data.db")
WEEKLY_RESET_HOURS = 168
SETTINGS_COLUMNS = {"welcome_channel", "log_channel", "msg_log_channel", "voice_log_channel", "autorole", "level_channel"}
VAULT_CAP = 3000
COOKIE_EMOJI = "🍪"

# Database
class GlobalDB:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, timeout=30.0, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
    def cursor(self):
        return self.conn.cursor()
    def commit(self):
        self.conn.commit()
    def close(self):
        pass

_global_db = None
def get_conn():
    global _global_db
    if _global_db is None:
        _global_db = GlobalDB(DB_PATH)
    return _global_db

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        guild_id TEXT, user_id TEXT,
        cookies INTEGER DEFAULT 0,
        jar INTEGER DEFAULT 0,
        vault INTEGER DEFAULT 0,
        vault_max INTEGER DEFAULT 3000,
        xp INTEGER DEFAULT 0,
        level INTEGER DEFAULT 0,
        vc_seconds INTEGER DEFAULT 0,
        total_messages INTEGER DEFAULT 0,
        weekly_messages INTEGER DEFAULT 0,
        last_daily TEXT DEFAULT NULL,
        last_weekly TEXT DEFAULT NULL,
        last_rob TEXT DEFAULT NULL,
        last_heist TEXT DEFAULT NULL,
        last_work TEXT DEFAULT NULL,
        PRIMARY KEY (guild_id, user_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS guild_settings (
        guild_id TEXT PRIMARY KEY,
        welcome_channel TEXT, log_channel TEXT,
        msg_log_channel TEXT, voice_log_channel TEXT,
        autorole TEXT, level_channel TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS vc_sessions (
        guild_id TEXT, user_id TEXT, join_time REAL, last_reward_at REAL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS heist_sessions (
        guild_id TEXT PRIMARY KEY,
        leader_id TEXT,
        target_id TEXT,
        members TEXT,
        start_time REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS warnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        mod_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS mod_cases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT NOT NULL,
        action TEXT NOT NULL,
        user_id TEXT NOT NULL,
        mod_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS metadata (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS interactions (
        guild_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        hugs_received INTEGER DEFAULT 0,
        kisses_received INTEGER DEFAULT 0,
        slaps_received INTEGER DEFAULT 0,
        wastes_received INTEGER DEFAULT 0,
        giveups_received INTEGER DEFAULT 0,
        kidnaps_received INTEGER DEFAULT 0,
        PRIMARY KEY (guild_id, user_id)
    )""")

    user_columns = {
        "cookies": "INTEGER DEFAULT 0",
        "jar": "INTEGER DEFAULT 0",
        "vault": "INTEGER DEFAULT 0",
        "vault_max": f"INTEGER DEFAULT {VAULT_CAP}",
        "xp": "INTEGER DEFAULT 0",
        "level": "INTEGER DEFAULT 0",
        "vc_seconds": "INTEGER DEFAULT 0",
        "total_messages": "INTEGER DEFAULT 0",
        "weekly_messages": "INTEGER DEFAULT 0",
        "last_daily": "TEXT DEFAULT NULL",
        "last_weekly": "TEXT DEFAULT NULL",
        "last_rob": "TEXT DEFAULT NULL",
        "last_heist": "TEXT DEFAULT NULL",
        "last_work": "TEXT DEFAULT NULL",
    }
    c.execute("PRAGMA table_info(users)")
    existing_user_cols = {row[1] for row in c.fetchall()}
    for column, ddl in user_columns.items():
        if column not in existing_user_cols:
            c.execute(f"ALTER TABLE users ADD COLUMN {column} {ddl}")

    c.execute("PRAGMA table_info(guild_settings)")
    existing_setting_cols = {row[1] for row in c.fetchall()}
    for column in SETTINGS_COLUMNS:
        if column not in existing_setting_cols:
            c.execute(f"ALTER TABLE guild_settings ADD COLUMN {column} TEXT")

    c.execute("CREATE INDEX IF NOT EXISTS idx_users_guild_wealth ON users(guild_id, jar, vault)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_guild_level ON users(guild_id, level, xp)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_warnings_guild_user ON warnings(guild_id, user_id, id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_cases_guild_id ON mod_cases(guild_id, id)")

    # Migration safety for existing DB files
    c.execute("PRAGMA table_info(vc_sessions)")
    cols = {row[1] for row in c.fetchall()}
    if "last_reward_at" not in cols:
        c.execute("ALTER TABLE vc_sessions ADD COLUMN last_reward_at REAL DEFAULT 0")
    c.execute("UPDATE users SET vault_max=?", (VAULT_CAP,))

    conn.commit()
    conn.close()

def get_user(guild_id, user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (guild_id, user_id) VALUES (?,?)", (str(guild_id), str(user_id)))
    c.execute("UPDATE users SET vault_max=? WHERE guild_id=? AND user_id=?", (VAULT_CAP, str(guild_id), str(user_id)))
    c.execute("SELECT * FROM users WHERE guild_id=? AND user_id=?", (str(guild_id), str(user_id)))
    row = c.fetchone()
    conn.commit()
    conn.close()
    return row

def update_user(guild_id, user_id, **kwargs):
    if not kwargs:
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (guild_id, user_id) VALUES (?,?)", (str(guild_id), str(user_id)))
    c.execute("UPDATE users SET vault_max=? WHERE guild_id=? AND user_id=?", (VAULT_CAP, str(guild_id), str(user_id)))
    for key, val in kwargs.items():
        if not key.isidentifier():
            continue
        c.execute(f"UPDATE users SET {key}=? WHERE guild_id=? AND user_id=?", (val, str(guild_id), str(user_id)))
    conn.commit()
    conn.close()

def get_setting(guild_id, key):
    if key not in SETTINGS_COLUMNS:
        return None
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (str(guild_id),))
    c.execute(f"SELECT {key} FROM guild_settings WHERE guild_id=?", (str(guild_id),))
    row = c.fetchone()
    conn.commit()
    conn.close()
    return row[0] if row else None

def set_setting(guild_id, key, value):
    if key not in SETTINGS_COLUMNS:
        return
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (str(guild_id),))
    c.execute(f"UPDATE guild_settings SET {key}=? WHERE guild_id=?", (value, str(guild_id)))
    conn.commit()
    conn.close()

def get_meta(key, default=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM metadata WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] is not None else default

def set_meta(key, value):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO metadata(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()

def add_interaction(guild_id, user_id, column):
    valid = {
        "hugs_received",
        "kisses_received",
        "slaps_received",
        "wastes_received",
        "giveups_received",
        "kidnaps_received",
    }
    if column not in valid:
        return 0
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO interactions (guild_id, user_id) VALUES (?, ?)", (str(guild_id), str(user_id)))
    c.execute(f"UPDATE interactions SET {column} = {column} + 1 WHERE guild_id=? AND user_id=?", (str(guild_id), str(user_id)))
    c.execute(f"SELECT {column} FROM interactions WHERE guild_id=? AND user_id=?", (str(guild_id), str(user_id)))
    total = c.fetchone()[0]
    conn.commit()
    conn.close()
    return total

# Parse amount helper
def parse_amount(amount_str, jar_balance):
    """Parse amount strings like 4k, 2.5k, all, half, max"""
    if isinstance(amount_str, int):
        return amount_str
    s = str(amount_str).lower().strip()
    if s in ("all", "max"):
        return jar_balance
    if s == "half":
        return jar_balance // 2
    s = s.replace(",", "")
    try:
        if s.endswith("%"):
            pct = float(s[:-1])
            if pct <= 0:
                return 0
            return int((jar_balance * pct) / 100)
        if s.endswith("k"):
            return int(float(s[:-1]) * 1000)
        if s.endswith("m"):
            return int(float(s[:-1]) * 1_000_000)
        return int(float(s))
    except:
        return None

async def send_reply(ctx, *args, **kwargs):
    kwargs.setdefault("reference", ctx.message.to_reference(fail_if_not_exists=False))
    kwargs.setdefault("mention_author", False)
    return await commands.Context.send(ctx, *args, **kwargs)

# Level system
# Level roles config - set these role names in your server
LEVEL_ROLES = {
    5: "Spark Recruit",
    10: "Rising Nova",
    15: "Flare Rider",
    20: "Starlit Ace",
    35: "Nebula Scout",
    45: "Shadow Marksman",
    50: "Diamond Core",
    60: "Royal Vanguard",
    65: "Celestial Knight",
    70: "Cosmic General",
    75: "Mythic Warden",
    80: "Sky Sovereign",
    90: "Astral Monarch",
    100: "Cookie Legend",
}

LEVEL_COOKIE_REWARDS = {
    5: 200, 10: 500, 15: 800, 20: 1000, 35: 2000,
    45: 3000, 50: 5000, 60: 7500, 65: 8000, 70: 9000,
    75: 10000, 80: 12000, 90: 15000, 100: 25000
}

XP_PER_MESSAGE = 10
COOKIES_PER_VC_MINUTE = 2

def xp_for_level(level):
    return 100 * (level ** 2) + 50 * level

async def assign_role(member, role_name, role_color=None):
    """Assign a role by name, create if missing. Optionally set color."""
    guild = member.guild
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        try:
            kwargs = {"name": role_name, "reason": "Auto-created level/vc role"}
            if role_color is not None:
                kwargs["color"] = discord.Color(role_color)
            role = await guild.create_role(**kwargs)
        except:
            return
    elif role_color is not None and role.color.value != role_color:
        try:
            await role.edit(color=discord.Color(role_color), reason="Sync VC milestone role color")
        except:
            pass
    try:
        await member.add_roles(role)
    except:
        pass

async def check_level_up(member, guild_id):
    row = get_user(guild_id, member.id)
    xp, level = row[6], row[7]
    new_level = level
    while xp >= xp_for_level(new_level + 1):
        new_level += 1
    if new_level > level:
        jar = row[3]
        total_reward = 0
        unlocked_roles = []
        for achieved_level in range(level + 1, new_level + 1):
            reward = LEVEL_COOKIE_REWARDS.get(achieved_level, 0)
            if reward:
                jar += reward
                total_reward += reward
            role_name = LEVEL_ROLES.get(achieved_level)
            if role_name:
                await assign_role(member, role_name)
                unlocked_roles.append(role_name)

        update_user(guild_id, member.id, level=new_level, jar=jar)

        ch_id = get_setting(guild_id, "level_channel")
        channel = member.guild.get_channel(int(ch_id)) if ch_id else member.guild.system_channel
        if channel:
            embed = discord.Embed(title="🎉 Level Up!", color=0x9B59B6)
            embed.description = f"{member.mention} reached **Level {new_level}**!"
            if total_reward:
                embed.add_field(name="Cookie Reward", value=f"+{total_reward:,} cookies added to jar!")
            if unlocked_roles:
                embed.add_field(name="Role Unlocked", value=", ".join(f"`{name}`" for name in unlocked_roles), inline=False)
            embed.set_thumbnail(url=member.display_avatar.url)
            try:
                await channel.send(embed=embed)
            except Exception:
                pass

# Message milestone roles
MSG_ROLES = {
    100: ("Quick Chatter", 800),
    200: ("Elite Speaker", 1500),
    500: ("Server Broadcaster", 2500),
    1000: ("Guild Voice", 3500),
    1500: ("Conversation Titan", 5000),
    2500: ("Mythic Yapper", 8500),
    5000: ("Hall of Echoes", 15000),
}

async def check_message_milestone(member, guild_id, _weekly_msgs=None):
    """Check and award message milestone roles."""
    if member.bot:
        return
    row = get_user(guild_id, member.id)
    total = row[9]
    jar = row[3]
    for threshold, (role_name, cookie_reward) in sorted(MSG_ROLES.items()):
        if total != threshold:
            continue

        existing_role = discord.utils.get(member.roles, name=role_name)
        if not existing_role:
            await assign_role(member, role_name)
        jar += cookie_reward
        update_user(guild_id, member.id, jar=jar)

        ch_id = get_setting(guild_id, "level_channel")
        channel = member.guild.get_channel(int(ch_id)) if ch_id else member.guild.system_channel
        if channel:
            embed = discord.Embed(title="Message Milestone Reached", color=0xF39C12)
            embed.description = f"{member.mention} reached **{threshold:,} messages**."
            embed.add_field(name="Unlocked Role", value=f"`{role_name}`", inline=True)
            embed.add_field(name="Cookie Reward", value=f"+{cookie_reward:,} cookies", inline=True)
            if threshold == 100:
                embed.add_field(name="Rob Cooldown Tier", value="10 minutes once weekly msgs hit 100+", inline=False)
            if threshold == 200:
                embed.add_field(name="Rob Cooldown Tier", value="5 minutes once weekly msgs hit 200+", inline=False)
            try:
                await channel.send(embed=embed)
            except Exception:
                pass

# Voice chat time roles
VC_ROLES = {
    2 * 3600: ("🔹 Voice Explorer", 900, 0x1ABC9C),
    5 * 3600: ("🟣 Midnight Broadcaster", 2200, 0x9B59B6),
    7 * 3600: ("⚡ Echo Commander", 5000, 0xF1C40F),
    10 * 3600: ("🌌 Rift Resonator", 7000, 0x34495E),
    15 * 3600: ("🔥 Inferno Orator", 9000, 0xE67E22),
    18 * 3600: ("🧿 Void Harmonic", 11000, 0x2C3E50),
    20 * 3600: ("🛡️ Storm Vanguard", 13000, 0x2980B9),
    24 * 3600: ("💠 Hypernova Herald", 16000, 0x8E44AD),
    28 * 3600: ("👑 Celestial Supreme", 20000, 0xF39C12),
}

async def check_vc_milestones(member, guild_id, prev_vc_seconds, total_vc_seconds):
    """Award VC time roles when thresholds are crossed."""
    if member.bot:
        return
    row = get_user(guild_id, member.id)
    jar = row[3]
    crossed = []
    for threshold, (role_name, cookie_reward, role_color) in sorted(VC_ROLES.items()):
        if prev_vc_seconds < threshold <= total_vc_seconds:
            existing_role = discord.utils.get(member.roles, name=role_name)
            if not existing_role:
                await assign_role(member, role_name, role_color)
            jar += cookie_reward
            crossed.append((threshold, role_name, cookie_reward))

    if not crossed:
        return

    update_user(guild_id, member.id, jar=jar)
    ch_id = get_setting(guild_id, "level_channel")
    channel = member.guild.get_channel(int(ch_id)) if ch_id else member.guild.system_channel
    if channel:
        for threshold, role_name, cookie_reward in crossed:
            h = threshold // 3600
            embed = discord.Embed(title="Voice Milestone Reached", color=0x3498DB)
            embed.description = f"{member.mention} crossed **{h} hours** in voice chat."
            embed.add_field(name="Unlocked Role", value=f"`{role_name}`", inline=True)
            embed.add_field(name="Cookie Reward", value=f"+{cookie_reward:,} cookies", inline=True)
            try:
                await channel.send(embed=embed)
            except Exception:
                pass

# Rob cooldown based on weekly messages
def get_rob_cooldown_minutes(weekly_msgs):
    if weekly_msgs >= 200:
        return 5
    elif weekly_msgs >= 100:
        return 10
    else:
        return 15

def cd_remaining_minutes(last_time_str, minutes):
    if not last_time_str:
        return None
    last = datetime.fromisoformat(last_time_str)
    diff = datetime.utcnow() - last
    limit = timedelta(minutes=minutes)
    if diff < limit:
        remaining = limit - diff
        total_secs = int(remaining.total_seconds())
        h, rem = divmod(total_secs, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}h {m}m {s}s"
        return f"{m}m {s}s"
    return None

def cd_remaining(last_time_str, hours):
    if not last_time_str:
        return None
    return cd_remaining_minutes(last_time_str, int(hours * 60))

# -----------------------------------------------------------------------------
# HEALTH CHECK (For Render Deployment)
# -----------------------------------------------------------------------------
async def handle_ping(request):
    return web.Response(text="Bot is alive!")

async def start_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server started on port {port}")

class WelcomeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Say welcome!", emoji="🫂", style=discord.ButtonStyle.secondary, custom_id="say_welcome_btn")
    async def say_welcome(self, interaction: discord.Interaction, button: discord.ui.Button):
        target = interaction.message.mentions[0] if interaction.message.mentions else None
        target_mention = target.mention if target else "the new member"
        embed = discord.Embed(
            description=f"🫂 Welcome, Thanks for being a proud member of our unique and ever-expanding community.\n\n"
                        f"• 💚 You can # 📡 | vote-for-us\n\n"
                        f"• ✨ Feel free to # 💰 | support-us",
            color=0x2b2d31
        )
        await interaction.response.send_message(
            content=f"{interaction.user.mention} **Welcomed** {target_mention}",
            embed=embed
        )

async def setup_hook():
    bot.loop.create_task(start_server())
    bot.add_view(WelcomeView())

bot.setup_hook = setup_hook

# -----------------------------------------------------------------------------
# EVENTS
# -----------------------------------------------------------------------------
@bot.event
async def on_ready():
    await ensure_weekly_message_reset()
    if not reset_weekly_messages.is_running():
        reset_weekly_messages.start()
    if not update_vc_cookies.is_running():
        update_vc_cookies.start()
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="?help | cookies"))
    print(f"OK: Logged in as {bot.user} | Servers: {len(bot.guilds)}")

@bot.event
async def on_member_join(member):
    guild = member.guild
    ch_id = get_setting(guild.id, "welcome_channel")
    if ch_id:
        channel = guild.get_channel(int(ch_id))
        if channel:
            embed = discord.Embed(color=0x2b2d31)
            embed.description = (
                f"- ✨ **Learn more** 🛫 Server Guide\n\n"
                f"- 💖 **Get roles** 🎚️ Channels & Roles\n\n"
                f"- 💮 **Discover more** 🔍 Browse Channels\n"
                f"─────────────────────────────\n"
                f"🌎 You are our {guild.member_count}th member, Have a great day!"
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            content = f"➡️ {member.mention}, **Welcome to {guild.name}!**"
            await channel.send(content=content, embed=embed, view=WelcomeView())
    role_id = get_setting(guild.id, "autorole")
    if role_id:
        role = guild.get_role(int(role_id))
        if role:
            try:
                await member.add_roles(role)
            except:
                pass

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return
    await ensure_weekly_message_reset()
    row = get_user(message.guild.id, message.author.id)
    new_total = row[9] + 1
    new_weekly = row[10] + 1
    update_user(message.guild.id, message.author.id,
                xp=row[6] + XP_PER_MESSAGE,
                total_messages=new_total,
                weekly_messages=new_weekly)
    try:
        await check_level_up(message.author, message.guild.id)
        await check_message_milestone(message.author, message.guild.id, new_weekly)
    except Exception as e:
        print(f"Error checking milestones: {e}")
    finally:
        await bot.process_commands(message)

@bot.event
async def on_message_delete(message):
    if message.author.bot: return
    ch_id = get_setting(message.guild.id, "msg_log_channel") or get_setting(message.guild.id, "log_channel")
    if ch_id:
        ch = message.guild.get_channel(int(ch_id))
        if ch:
            e = discord.Embed(title="Message Deleted", color=0xE74C3C, timestamp=datetime.utcnow())
            e.add_field(name="Author", value=message.author.mention)
            e.add_field(name="Channel", value=message.channel.mention)
            e.add_field(name="Content", value=message.content[:1024] or "*empty*", inline=False)
            await ch.send(embed=e)

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or not before.guild: return
    ch_id = get_setting(before.guild.id, "msg_log_channel") or get_setting(before.guild.id, "log_channel")
    if ch_id and before.content != after.content:
        ch = before.guild.get_channel(int(ch_id))
        if ch:
            e = discord.Embed(title="Message Edited", color=0xF39C12, timestamp=datetime.utcnow())
            e.add_field(name="Author", value=before.author.mention)
            e.add_field(name="Channel", value=before.channel.mention)
            e.add_field(name="Before", value=before.content[:512] or "*empty*", inline=False)
            e.add_field(name="After", value=after.content[:512] or "*empty*", inline=False)
            e.add_field(name="Link", value=f"[Jump to Message]({after.jump_url})", inline=False)
            await ch.send(embed=e)

@bot.event
async def on_member_ban(guild, user):
    ch_id = get_setting(guild.id, "log_channel")
    if ch_id:
        ch = guild.get_channel(int(ch_id))
        if ch:
            e = discord.Embed(title="Member Banned", color=0xE74C3C, timestamp=datetime.utcnow())
            e.add_field(name="User", value=f"{user} ({user.id})")
            await ch.send(embed=e)

@bot.event
async def on_member_remove(member):
    ch_id = get_setting(member.guild.id, "log_channel")
    if ch_id:
        ch = member.guild.get_channel(int(ch_id))
        if ch:
            e = discord.Embed(title="Member Left", color=0x95A5A6, timestamp=datetime.utcnow())
            e.add_field(name="User", value=f"{member} ({member.id})")
            await ch.send(embed=e)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return
    guild_id, user_id = str(member.guild.id), str(member.id)
    conn = get_conn()
    c = conn.cursor()
    now = time.time()
    if before.channel is None and after.channel is not None:
        ch_id = get_setting(member.guild.id, "voice_log_channel") or get_setting(member.guild.id, "log_channel")
        if ch_id:
            ch = member.guild.get_channel(int(ch_id))
            if ch:
                e = discord.Embed(title="Voice Join", description=f"{member.mention} joined **{after.channel.name}**", color=0x2ECC71, timestamp=datetime.utcnow())
                await ch.send(embed=e)
        c.execute(
            "INSERT OR REPLACE INTO vc_sessions (guild_id, user_id, join_time, last_reward_at) VALUES (?,?,?,?)",
            (guild_id, user_id, now, now),
        )
        conn.commit()
        conn.close()
    elif before.channel is not None and after.channel is None:
        ch_id = get_setting(member.guild.id, "voice_log_channel") or get_setting(member.guild.id, "log_channel")
        if ch_id:
            ch = member.guild.get_channel(int(ch_id))
            if ch:
                e = discord.Embed(title="Voice Leave", description=f"{member.mention} left **{before.channel.name}**", color=0xE74C3C, timestamp=datetime.utcnow())
                await ch.send(embed=e)
        c.execute("SELECT join_time, last_reward_at FROM vc_sessions WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        row = c.fetchone()
        if row:
            join_time = row[0]
            last_reward_at = row[1] or join_time
            seconds = int(now - join_time)
            pending_mins = max(0, int((now - last_reward_at) // 60))
            pending_seconds = max(0, int(now - last_reward_at))
            c.execute("DELETE FROM vc_sessions WHERE guild_id=? AND user_id=?", (guild_id, user_id))
            conn.commit()
            conn.close()
            ur = get_user(guild_id, member.id)
            mins = pending_mins
            prev_vc = ur[8]
            new_vc = ur[8] + pending_seconds
            update_user(guild_id, member.id,
                        vc_seconds=new_vc,
                        xp=ur[6] + mins * 5,
                        jar=ur[3] + pending_mins * COOKIES_PER_VC_MINUTE)
            await check_level_up(member, guild_id)
            await check_vc_milestones(member, guild_id, prev_vc, new_vc)
            return
        else:
            conn.commit()
            conn.close()
    elif before.channel != after.channel:
        ch_id = get_setting(member.guild.id, "voice_log_channel") or get_setting(member.guild.id, "log_channel")
        if ch_id:
            ch = member.guild.get_channel(int(ch_id))
            if ch:
                e = discord.Embed(title="Voice Move", description=f"{member.mention} moved from **{before.channel.name}** to **{after.channel.name}**", color=0x3498DB, timestamp=datetime.utcnow())
                await ch.send(embed=e)
        conn.commit()
        conn.close()
    else:
        conn.commit()
        conn.close()

@tasks.loop(minutes=2)
async def update_vc_cookies():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT guild_id, user_id, last_reward_at FROM vc_sessions")
    sessions = c.fetchall()
    now = time.time()
    for guild_id, user_id, last_reward_at in sessions:
        if not last_reward_at:
            last_reward_at = now
        mins = int((now - last_reward_at) // 60)
        if mins >= 1:
            ur = get_user(guild_id, user_id)
            prev_vc = ur[8]
            gained_secs = mins * 60
            new_vc = prev_vc + gained_secs
            update_user(
                guild_id,
                user_id,
                jar=ur[3] + mins * COOKIES_PER_VC_MINUTE,
                xp=ur[6] + mins * 5,
                vc_seconds=new_vc,
            )
            c.execute(
                "UPDATE vc_sessions SET last_reward_at=? WHERE guild_id=? AND user_id=?",
                (last_reward_at + mins * 60, guild_id, user_id),
            )
            guild = bot.get_guild(int(guild_id))
            if guild:
                member = guild.get_member(int(user_id))
                if member and not member.bot:
                    try:
                        await check_level_up(member, guild_id)
                        await check_vc_milestones(member, guild_id, prev_vc, new_vc)
                    except Exception as e:
                        print(f"Error checking VC milestone: {e}")
    conn.commit()
    conn.close()

async def ensure_weekly_message_reset():
    raw = get_meta("weekly_reset_at")
    now = datetime.utcnow()
    should_store = False
    if raw:
        try:
            next_reset = datetime.fromisoformat(raw)
        except ValueError:
            next_reset = now + timedelta(hours=WEEKLY_RESET_HOURS)
            should_store = True
    else:
        next_reset = now + timedelta(hours=WEEKLY_RESET_HOURS)
        should_store = True

    if now < next_reset:
        if should_store:
            set_meta("weekly_reset_at", next_reset.isoformat())
        return

    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET weekly_messages=0")
    conn.commit()
    conn.close()

    while next_reset <= now:
        next_reset += timedelta(hours=WEEKLY_RESET_HOURS)
    set_meta("weekly_reset_at", next_reset.isoformat())

@tasks.loop(hours=1)
async def reset_weekly_messages():
    await ensure_weekly_message_reset()

# -----------------------------------------------------------------------------
# HELP
# -----------------------------------------------------------------------------
@bot.command()
async def help(ctx, category: str = None):
    if category is None:
        embed = discord.Embed(
            title="Command List",
            color=0x9B59B6,
            description="Use `?help <category>` for details.",
        )
        embed.add_field(name="Economy", value="`?help economy`", inline=True)
        embed.add_field(name="Crime", value="`?help crime`", inline=True)
        embed.add_field(name="Casino", value="`?help casino`", inline=True)
        embed.add_field(name="Stats", value="`?help stats`", inline=True)
        embed.add_field(name="Fun", value="`?help fun`", inline=True)
        embed.add_field(name="Moderation", value="`?help mod`", inline=True)
        embed.add_field(name="Settings", value="`?help settings`", inline=True)
        embed.set_footer(text="Prefix: ?")
        return await send_reply(ctx, embed=embed)

    cat = category.lower()
    if cat == "economy":
        embed = discord.Embed(title="Economy Commands", color=0xF39C12)
        embed.add_field(name="?bal [@user]", value="Check cookie balance", inline=False)
        embed.add_field(name="?daily", value="Claim daily cookies (24h cooldown)", inline=False)
        embed.add_field(name="?weekly", value="Claim weekly cookies (7d cooldown)", inline=False)
        embed.add_field(name="?work", value="Work for cookies (1h cooldown)", inline=False)
        embed.add_field(name="?give @user <amount>", value="Give cookies to someone", inline=False)
        embed.add_field(name="?dep <amount|all>", value="Deposit to vault", inline=False)
        embed.add_field(name="?with <amount|all>", value="Withdraw from vault", inline=False)
    elif cat == "crime":
        embed = discord.Embed(title="Crime Commands", color=0xE74C3C)
        embed.add_field(name="?rob @user", value="Rob someone (reply works)\nCooldown:\n• 200+ msgs -> 5min\n• 100+ msgs -> 10min\n• <100 msgs -> 15min", inline=False)
        embed.add_field(name="?heist @user", value="Start a crew heist (2h cooldown)", inline=False)
        embed.add_field(name="?cd [@user]", value="Check all cooldowns", inline=False)
    elif cat == "casino":
        embed = discord.Embed(title="Casino Commands", color=0xF1C40F)
        embed.add_field(name="?bet <amount>", value="Double or nothing (50/50)", inline=False)
        embed.add_field(name="?cr <amount>", value="Crash game — avoid the bomb", inline=False)
        embed.add_field(name="?slots <amount>", value="Spin the slot machine", inline=False)
        embed.add_field(name="?cf <amount> heads/tails", value="Coin flip", inline=False)
        embed.add_field(name="?dice <amount> <1-6>", value="Dice guess (5x if correct)", inline=False)
        embed.add_field(name="?bj <amount>", value="Blackjack", inline=False)
        embed.add_field(name="?rl <amount> red/black/0-36", value="Roulette", inline=False)
        embed.add_field(name="Amounts", value="Supports: `4k`, `2.5k`, `1m`, `50%`, `all`, `half`", inline=False)
    elif cat == "stats":
        embed = discord.Embed(title="Stats Commands", color=0x1ABC9C)
        embed.add_field(name="?lvl [@user]", value="View level & XP", inline=False)
        embed.add_field(name="?msgs [@user]", value="View message stats", inline=False)
        embed.add_field(name="?vctime [@user]", value="View voice chat time", inline=False)
        embed.add_field(name="?lb", value="Cookie leaderboard", inline=False)
        embed.add_field(name="?roles", value="View all role thresholds", inline=False)
    elif cat == "fun":
        embed = discord.Embed(title="Fun Commands", color=0x9B59B6)
        embed.add_field(name="?truth", value="Get a truth question", inline=False)
        embed.add_field(name="?dare", value="Get a dare challenge", inline=False)
        embed.add_field(name="?hug @user", value="Hug a member", inline=False)
        embed.add_field(name="?kiss @user", value="Kiss a member (tracked count)", inline=False)
        embed.add_field(name="?slap @user", value="Slap a member", inline=False)
        embed.add_field(name="?waste @user", value="Waste a member", inline=False)
        embed.add_field(name="?giveup @user", value="Give up to a member", inline=False)
        embed.add_field(name="?kidnap @user", value="Kidnap a member", inline=False)
    elif cat == "mod":
        embed = discord.Embed(title="Moderation Commands", color=0xE74C3C)
        embed.add_field(name="?ban @user [reason]", value="Ban a member", inline=False)
        embed.add_field(name="?kick @user [reason]", value="Kick a member", inline=False)
        embed.add_field(name="?mute @user [minutes]", value="Timeout a member", inline=False)
        embed.add_field(name="?unmute @user", value="Remove timeout", inline=False)
        embed.add_field(name="?warn @user [reason]", value="Warn a member", inline=False)
        embed.add_field(name="?warnings @user", value="View member warnings", inline=False)
        embed.add_field(name="?clearwarns @user", value="Clear warnings", inline=False)
        embed.add_field(name="?clear [amount]", value="Bulk delete messages", inline=False)
        embed.add_field(name="?lock / ?unlock", value="Lock or unlock channel", inline=False)
        embed.add_field(name="?slowmode [seconds]", value="Set slowmode", inline=False)
    elif cat == "settings":
        embed = discord.Embed(title="Settings Commands", color=0x95A5A6)
        embed.add_field(name="?setwelcome #channel", value="Set welcome channel", inline=False)
        embed.add_field(name="?setlog #channel", value="Set general log channel", inline=False)
        embed.add_field(name="?setmsglog #channel", value="Set message log channel", inline=False)
        embed.add_field(name="?setvoicelog #channel", value="Set voice log channel", inline=False)
        embed.add_field(name="?setauthorole @role", value="Set auto-role", inline=False)
        embed.add_field(name="?setlevelchannel #channel", value="Set level-up channel", inline=False)
    else:
        return await send_reply(ctx, "❌ Unknown category. Use `?help`.")

    await send_reply(ctx, embed=embed)

# ECONOMY
# -----------------------------------------------------------------------------
@bot.command(aliases=["balance", "wallet"])
async def bal(ctx, member: discord.Member = None):
    member = member or ctx.author
    row = get_user(ctx.guild.id, member.id)
    jar, vault, vault_max = row[3], row[4], row[5]
    total = jar + vault
    embed = discord.Embed(color=0x2b2d31)
    embed.set_author(name=f"{member.display_name}'s Account", icon_url=member.display_avatar.url)
    embed.description = f"**Total ➔** `{total:,}` 🍪\n\n"
    embed.add_field(name="🫙 Jar", value=f"`{jar:,}` 🍪", inline=True)
    embed.add_field(name="🏦 Vault", value=f"`{vault:,}/{vault_max:,}` 🍪", inline=True)
    await send_reply(ctx, embed=embed)

@bot.command()
async def dep(ctx, amount: str):
    row = get_user(ctx.guild.id, ctx.author.id)
    jar, vault, vault_max = row[3], row[4], row[5]
    amt = parse_amount(amount, jar)
    if amt is None:
        return await send_reply(ctx, "❌ Invalid amount. Examples: `500`, `4k`, `50%`, `all`")
    if amt <= 0:
        return await send_reply(ctx, "❌ Amount must be positive.")
    if jar < amt:
        return await send_reply(ctx, f"❌ Not enough in jar! You have **{jar:,}** {COOKIE_EMOJI}")
    if vault + amt > vault_max:
        amt = vault_max - vault
        if amt <= 0:
            return await send_reply(ctx, "❌ Vault is full!")
    update_user(ctx.guild.id, ctx.author.id, jar=jar - amt, vault=vault + amt)
    embed = discord.Embed(description=f"🏦 Deposited **{amt:,}** {COOKIE_EMOJI}\nJar: **{jar-amt:,}** | Vault: **{vault+amt:,}/{vault_max:,}**", color=0x2ECC71)
    await send_reply(ctx, embed=embed)

@bot.command(name="with", aliases=["withdraw"])
async def withdraw(ctx, amount: str):
    row = get_user(ctx.guild.id, ctx.author.id)
    jar, vault = row[3], row[4]
    amt = parse_amount(amount, vault)
    if amt is None:
        return await send_reply(ctx, "❌ Invalid amount.")
    if amt <= 0:
        return await send_reply(ctx, "❌ Amount must be positive.")
    if vault < amt:
        return await send_reply(ctx, f"❌ Not enough in vault! You have **{vault:,}** {COOKIE_EMOJI}")
    update_user(ctx.guild.id, ctx.author.id, jar=jar + amt, vault=vault - amt)
    embed = discord.Embed(description=f"📦 Withdrew **{amt:,}** {COOKIE_EMOJI}\nJar: **{jar+amt:,}** | Vault: **{vault-amt:,}**", color=0x3498DB)
    await send_reply(ctx, embed=embed)

@bot.command()
async def daily(ctx):
    row = get_user(ctx.guild.id, ctx.author.id)
    cd = cd_remaining(row[11], 24)
    if cd:
        return await send_reply(ctx, embed=discord.Embed(description=f"⏰ Daily resets in **{cd}**", color=0xE74C3C))
    reward = random.randint(500, 1000)
    xp_reward = random.randint(800, 1500)
    update_user(ctx.guild.id, ctx.author.id, jar=row[3] + reward, xp=row[6] + xp_reward, last_daily=datetime.utcnow().isoformat())
    embed = discord.Embed(color=0x2b2d31)
    embed.set_author(name="Daily Reward", icon_url=ctx.author.display_avatar.url)
    embed.add_field(name="🍪 Cookies", value=f"`+{reward:,} 🍪`", inline=True)
    embed.add_field(name="🧪 XP", value=f"`+{xp_reward:,}`", inline=True)
    await send_reply(ctx, embed=embed)

@bot.command()
async def weekly(ctx):
    row = get_user(ctx.guild.id, ctx.author.id)
    cd = cd_remaining(row[12], 168)
    if cd:
        return await send_reply(ctx, embed=discord.Embed(description=f"⏰ Weekly resets in **{cd}**", color=0xE74C3C))
    reward = random.randint(500, 1500)
    update_user(ctx.guild.id, ctx.author.id, jar=row[3] + reward, last_weekly=datetime.utcnow().isoformat())
    embed = discord.Embed(title="Weekly Reward", color=0x9B59B6)
    embed.add_field(name="Reward", value=f"+**{reward:,}** {COOKIE_EMOJI} added to jar")
    embed.set_footer(text="Come back in 7 days")
    await send_reply(ctx, embed=embed)

@bot.command()
async def work(ctx):
    row = get_user(ctx.guild.id, ctx.author.id)
    cd = cd_remaining(row[15], 1)
    if cd:
        return await send_reply(ctx, embed=discord.Embed(description=f"⏰ Work cooldown: **{cd}**", color=0xE74C3C))

    reward = random.randint(40, 100)
    xp_reward = random.randint(50, 150)
    update_user(ctx.guild.id, ctx.author.id, jar=row[3] + reward, xp=row[6] + xp_reward, last_work=datetime.utcnow().isoformat())
    
    embed = discord.Embed(color=0x2b2d31)
    embed.set_author(name="Work Reward", icon_url=ctx.author.display_avatar.url)
    embed.add_field(name="🍪 Cookies", value=f"`+{reward:,} 🍪`", inline=True)
    embed.add_field(name="🧪 XP", value=f"`+{xp_reward:,}`", inline=True)
    await send_reply(ctx, embed=embed)

@bot.command()
async def give(ctx, member_or_amount: str = None, amount: str = None):
    if amount is None:
        amount = member_or_amount
        member = await resolve_target(ctx)
    else:
        member = await resolve_target(ctx, member_or_amount)

    if not member:
        return await send_reply(ctx, "❌ Tag someone or reply to their message. Usage: `?give @user 500` or reply with `?give 500`")
    if member == ctx.author or member.bot:
        return await send_reply(ctx, "❌ Invalid target.")

    row = get_user(ctx.guild.id, ctx.author.id)
    amt = parse_amount(amount, row[3])
    if amt is None or amt <= 0:
        return await send_reply(ctx, "❌ Invalid amount.")
    if row[3] < amt:
        return await send_reply(ctx, f"❌ Not enough in jar! You have **{row[3]:,}** {COOKIE_EMOJI}")

    row2 = get_user(ctx.guild.id, member.id)
    update_user(ctx.guild.id, ctx.author.id, jar=row[3] - amt)
    update_user(ctx.guild.id, member.id, jar=row2[3] + amt)

    embed = discord.Embed(description=f"✅ {ctx.author.mention} gifted **{amt:,}** {COOKIE_EMOJI} to {member.mention}", color=0x2ECC71)
    await send_reply(ctx, embed=embed)

# Crime - rob and heist (reply-compatible)
# -----------------------------------------------------------------------------
async def resolve_target(ctx, target_input=None, allow_bots=False):
    """Resolve target from mention, ID, username, or replied message."""
    target = None

    if isinstance(target_input, discord.Member):
        target = target_input
    elif isinstance(target_input, str) and target_input.strip():
        token = target_input.strip()
        converter = commands.MemberConverter()
        try:
            target = await converter.convert(ctx, token)
        except commands.BadArgument:
            token_l = token.lower()
            target = discord.utils.find(
                lambda m: m.name.lower() == token_l or m.display_name.lower() == token_l,
                ctx.guild.members,
            )

    if not target and ctx.message.reference:
        try:
            ref_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            target = ref_msg.author
        except Exception:
            pass

    if target and target.bot and not allow_bots:
        return None
    return target

@bot.command()
async def rob(ctx, *, target_input: str = None):
    target = await resolve_target(ctx, target_input)
    if not target:
        return await send_reply(ctx, "❌ Tag someone or reply to their message. Usage: `?rob @user`")
    if target == ctx.author or target.bot:
        return await send_reply(ctx, "❌ Invalid target.")

    row = get_user(ctx.guild.id, ctx.author.id)
    weekly_msgs = row[10]
    cooldown_mins = get_rob_cooldown_minutes(weekly_msgs)
    cd = cd_remaining_minutes(row[13], cooldown_mins)
    if cd:
        return await send_reply(
            ctx,
            embed=discord.Embed(
                description=f"⏰ Rob cooldown: **{cd}**\nChat more to reduce cooldown! ({weekly_msgs} weekly msgs)",
                color=0xE74C3C,
            ),
        )

    victim = get_user(ctx.guild.id, target.id)
    if victim[3] < 50:
        return await send_reply(ctx, f"😅 {target.mention} is too broke to rob! (needs 50+ {COOKIE_EMOJI} in jar)")

    update_user(ctx.guild.id, ctx.author.id, last_rob=datetime.utcnow().isoformat())

    embed = discord.Embed(color=0x2b2d31)
    if random.random() < 0.45:
        percent = random.randint(3, 15)
        amount = max(10, int(victim[3] * percent / 100))
        update_user(ctx.guild.id, ctx.author.id, jar=row[3] + amount)
        update_user(ctx.guild.id, target.id, jar=victim[3] - amount)
        embed.description = f"✅ **Robbed `{percent}%` of cookies**\n\n`+{amount:,} 🍪`\n"
        embed.add_field(name=f"👤 {ctx.author.display_name}", value=f"`{row[3]+amount:,} 🍪`", inline=True)
        embed.add_field(name=f"👤 {target.display_name}", value=f"`{victim[3]-amount:,} 🍪`", inline=True)
        embed.color = 0x2ECC71
    else:
        penalty = min(random.randint(10, 150), max(10, row[3]))
        update_user(ctx.guild.id, ctx.author.id, jar=max(0, row[3] - penalty))
        embed.description = f"❌ **Caught by Police! Paid Fine**\n\n`-{penalty:,} 🍪`\n"
        embed.add_field(name=f"👤 {ctx.author.display_name}", value=f"`{max(0,row[3]-penalty):,} 🍪`", inline=True)
        embed.add_field(name=f"👤 {target.display_name}", value=f"`{victim[3]:,} 🍪`", inline=True)
        embed.color = 0xE74C3C

    await send_reply(ctx, embed=embed)

# Active heist sessions
active_heists = {}

@bot.command()
async def heist(ctx, *, target_input: str = None):
    target = await resolve_target(ctx, target_input)
    if not target:
        return await send_reply(ctx, "❌ Tag someone or reply to their message. Usage: `?heist @user`")
    if target == ctx.author or target.bot:
        return await send_reply(ctx, "❌ Invalid target.")

    gid = ctx.guild.id
    if gid in active_heists:
        return await send_reply(ctx, "❌ A heist is already in progress. React ✅ to join.")

    row = get_user(gid, ctx.author.id)
    cd = cd_remaining(row[14], 2)
    if cd:
        return await send_reply(ctx, embed=discord.Embed(description=f"⏰ Heist cooldown: **{cd}**", color=0xE74C3C))

    victim = get_user(gid, target.id)
    if victim[3] < 200:
        return await send_reply(ctx, f"❌ {target.mention} needs at least 200 {COOKIE_EMOJI} in jar.")

    active_heists[gid] = {"leader": ctx.author, "target": target, "members": [ctx.author], "start": time.time()}

    embed = discord.Embed(title="🏴‍☠️ Heist Recruiting", color=0xE67E22)
    embed.description = (
        f"**{ctx.author.mention}** is planning a heist on **{target.mention}**!\n"
        f"React ✅ to join the crew. Launching in **30 seconds**...\n"
        f"More members = higher success chance!"
    )
    embed.add_field(name="Crew", value=ctx.author.mention)
    embed.add_field(name="Target", value=f"{target.mention} — {victim[3]:,} {COOKIE_EMOJI} in jar")
    msg = await send_reply(ctx, embed=embed)
    active_heists[gid]["msg"] = msg
    await msg.add_reaction("✅")

    await asyncio.sleep(30)
    if gid not in active_heists:
        return

    session = active_heists.pop(gid)
    members = session["members"]
    victim_row = get_user(gid, target.id)
    update_user(gid, ctx.author.id, last_heist=datetime.utcnow().isoformat())

    success_chance = min(0.2 + len(members) * 0.15, 0.75)
    if random.random() < success_chance:
        total_steal = int(victim_row[3] * random.uniform(0.1, 0.35))
        per_person = total_steal // len(members)
        for m in members:
            mr = get_user(gid, m.id)
            update_user(gid, m.id, jar=mr[3] + per_person)
        update_user(gid, target.id, jar=max(0, victim_row[3] - total_steal))
        result = discord.Embed(title="🎉 Heist Successful", color=0x2ECC71)
        result.add_field(name="Total Stolen", value=f"{total_steal:,} {COOKIE_EMOJI}", inline=True)
        result.add_field(name="Per Person", value=f"{per_person:,} {COOKIE_EMOJI}", inline=True)
        result.add_field(name="Crew", value="\n".join(m.mention for m in members), inline=False)
    else:
        penalty = random.randint(50, 200)
        for m in members:
            mr = get_user(gid, m.id)
            update_user(gid, m.id, jar=max(0, mr[3] - penalty))
        result = discord.Embed(title="🚨 Heist Failed", color=0xE74C3C)
        result.add_field(name="Penalty per person", value=f"-{penalty:,} {COOKIE_EMOJI}", inline=False)
        result.add_field(name="Caught Crew", value="\n".join(m.mention for m in members), inline=False)

    await send_reply(ctx, embed=result)

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return
    gid = reaction.message.guild.id if reaction.message.guild else None
    if not gid or gid not in active_heists:
        return
    session = active_heists[gid]
    if reaction.message.id != session["msg"].id:
        return
    if str(reaction.emoji) == "✅" and user not in session["members"]:
        session["members"].append(user)
        embed = session["msg"].embeds[0]
        embed.set_field_at(0, name="Crew", value="\n".join(m.mention for m in session["members"]))
        await session["msg"].edit(embed=embed)

# COOLDOWN CHECK
# -----------------------------------------------------------------------------
@bot.command()
async def cd(ctx, member: discord.Member = None):
    member = member or ctx.author
    row = get_user(ctx.guild.id, member.id)
    weekly_msgs = row[10]
    rob_cd_mins = get_rob_cooldown_minutes(weekly_msgs)

    def status(cd_str):
        return f"**{cd_str}** ⏳" if cd_str else "✅ Ready"

    embed = discord.Embed(title=f"Cooldowns of {member.display_name}", color=0x3498DB)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Heist", value=status(cd_remaining(row[14], 2)), inline=True)
    embed.add_field(name=f"Rob ({rob_cd_mins}m)", value=status(cd_remaining_minutes(row[13], rob_cd_mins)), inline=True)
    embed.add_field(name="Work", value=status(cd_remaining(row[15], 1)), inline=True)
    embed.add_field(name="Daily", value=status(cd_remaining(row[11], 24)), inline=True)
    embed.add_field(name="Weekly", value=status(cd_remaining(row[12], 168)), inline=True)
    embed.set_footer(text=f"Weekly msgs: {weekly_msgs} | Rob cooldown: {rob_cd_mins}min")
    await send_reply(ctx, embed=embed)

# STATS
# -----------------------------------------------------------------------------
@bot.command()
async def msgs(ctx, member: discord.Member = None):
    member = member or ctx.author
    row = get_user(ctx.guild.id, member.id)
    embed = discord.Embed(title=f"{member.display_name}'s Message Count", color=0x1ABC9C)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Weekly", value=f"**{row[10]:,}**", inline=True)
    embed.add_field(name="Total", value=f"**{row[9]:,}**", inline=True)

    next_milestone = None
    for thresh in sorted(MSG_ROLES.keys()):
        if row[9] < thresh:
            next_milestone = thresh
            break
    if next_milestone:
        role_name, reward = MSG_ROLES[next_milestone]
        embed.add_field(
            name="Next Milestone",
            value=f"**{next_milestone:,} msgs** -> `{role_name}` + {reward:,} {COOKIE_EMOJI}\n({next_milestone - row[9]:,} msgs away)",
            inline=False,
        )
    embed.set_footer(text="Weekly messages reset every 7 days")
    await send_reply(ctx, embed=embed)

@bot.command()
async def lvl(ctx, member: discord.Member = None):
    member = member or ctx.author
    row = get_user(ctx.guild.id, member.id)
    xp, level = row[6], row[7]
    needed = xp_for_level(level + 1)
    percent = min(int((xp / needed) * 100), 100)
    filled = percent // 10
    bar = "#" * filled + "-" * (10 - filled)

    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE guild_id=? ORDER BY level DESC, xp DESC", (str(ctx.guild.id),))
    all_users = [r[0] for r in c.fetchall()]
    conn.close()
    rank_pos = all_users.index(str(member.id)) + 1 if str(member.id) in all_users else "?"

    next_level_role = None
    for lvl_threshold, role_name in sorted(LEVEL_ROLES.items()):
        if level < lvl_threshold:
            next_level_role = (lvl_threshold, role_name)
            break

    embed = discord.Embed(color=0x2b2d31)
    embed.set_author(name=f"{member.display_name}'s Account", icon_url=member.display_avatar.url)
    embed.description = f"🎖️ **LEVEL ➔** `{level}`\n\n"
    embed.add_field(name="🧪 XP", value=f"`{xp:,} / {needed:,}`", inline=True)
    embed.add_field(name="Prestige", value=f"`0 / 10`", inline=True)
    
    view = discord.ui.View()
    btn = discord.ui.Button(label="Leaderboard", emoji="🏆", style=discord.ButtonStyle.secondary)
    
    async def lb_callback(interaction: discord.Interaction):
        await interaction.response.defer()
        await lb(ctx)
        
    btn.callback = lb_callback
    view.add_item(btn)
    
    await send_reply(ctx, embed=embed, view=view)

@bot.command()
async def vctime(ctx, member: discord.Member = None):
    member = member or ctx.author
    row = get_user(ctx.guild.id, member.id)
    total = row[8]
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)

    next_vc_role = None
    for threshold, (role_name, reward, _color) in sorted(VC_ROLES.items()):
        if total < threshold:
            next_vc_role = (threshold, role_name, reward)
            break

    embed = discord.Embed(title=f"{member.display_name}'s VC Time", color=0x3498DB)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="⏱️ Total Time", value=f"**{h}h {m}m {s}s**")
    if next_vc_role:
        needed_secs = next_vc_role[0] - total
        nh, nr = divmod(needed_secs, 3600)
        nm, ns = divmod(nr, 60)
        embed.add_field(name="Next VC Role",
                        value=f"`{next_vc_role[1]}` ({next_vc_role[2]:,} {COOKIE_EMOJI})\n{nh}h {nm}m away!",
                        inline=False)
    await send_reply(ctx, embed=embed)

@bot.command(aliases=["leaderboard", "top"])
async def lb(ctx):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, jar, vault, level FROM users WHERE guild_id=? ORDER BY (jar+vault) DESC LIMIT 100",
              (str(ctx.guild.id),))
    rows = c.fetchall()
    conn.close()
    embed = discord.Embed(title="🍪 __Cookies Leaderboard__", color=0x2b2d31)
    medals = ["🥇", "🥈", "🥉"]
    rank = 0
    desc = ""
    for uid, jar, vault, level in rows:
        member = ctx.guild.get_member(int(uid))
        if not member or member.bot:
            continue
        prefix = medals[rank] if rank < 3 else "👤"
        desc += f"• {prefix} {member.mention} ➔ `{jar+vault:,} 🍪`\n\n"
        rank += 1
        if rank >= 10:
            break
    if rank == 0:
        desc = "No human members found on the leaderboard yet."
    embed.description = desc
    embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
    await send_reply(ctx, embed=embed)

@bot.command()
async def roles(ctx):
    """Show all earnable roles and their thresholds."""
    embed = discord.Embed(title="Earnable Roles", color=0x9B59B6)

    level_text = "\n".join(f"Level **{lv}** -> `{name}` (+{LEVEL_COOKIE_REWARDS.get(lv,0):,} {COOKIE_EMOJI})"
                           for lv, name in sorted(LEVEL_ROLES.items()))
    embed.add_field(name="⭐ Level Roles", value=level_text, inline=False)

    msg_text = "\n".join(f"**{th:,} msgs** -> `{name}` (+{reward:,} {COOKIE_EMOJI})"
                         for th, (name, reward) in sorted(MSG_ROLES.items()))
    embed.add_field(name="💬 Message Roles", value=msg_text, inline=False)

    vc_text = "\n".join(f"**{th//3600}h in VC** -> `{name}` (+{reward:,} {COOKIE_EMOJI})"
                        for th, (name, reward, _color) in sorted(VC_ROLES.items()))
    embed.add_field(name="🎙️ Voice Chat Roles", value=vc_text, inline=False)

    await send_reply(ctx, embed=embed)

# -----------------------------------------------------------------------------
# Casino - fixed and enhanced
# -----------------------------------------------------------------------------
def check_bet(row, amount):
    if amount <= 0:
        return "❌ Bet must be positive."
    if row[3] < amount:
        return f"❌ Not enough in jar! You have **{row[3]:,}** {COOKIE_EMOJI}"
    return None

@bot.command()
async def bet(ctx, amount: str):
    """Simple 50/50 double-or-nothing bet. No reactions needed."""
    row = get_user(ctx.guild.id, ctx.author.id)
    amt = parse_amount(amount, row[3])
    if amt is None:
        return await send_reply(ctx, "❌ Invalid amount. Try: `?bet 500`, `?bet 4k`, `?bet 50%`, `?bet all`")
    err = check_bet(row, amt)
    if err:
        return await send_reply(ctx, err)

    # Instant 50/50
    won = bool(random.getrandbits(1))
    if won:
        update_user(ctx.guild.id, ctx.author.id, jar=row[3] + amt)
        embed = discord.Embed(title="🎲 You Won!", color=0x2ECC71)
        embed.add_field(name="Bet", value=f"{amt:,} {COOKIE_EMOJI}", inline=True)
        embed.add_field(name="Won", value=f"+**{amt:,}** {COOKIE_EMOJI}", inline=True)
        embed.add_field(name="Balance", value=f"{row[3]+amt:,} {COOKIE_EMOJI}", inline=True)
    else:
        update_user(ctx.guild.id, ctx.author.id, jar=row[3] - amt)
        embed = discord.Embed(title="🎲 You Lost!", color=0xE74C3C)
        embed.add_field(name="Bet", value=f"{amt:,} {COOKIE_EMOJI}", inline=True)
        embed.add_field(name="Lost", value=f"-**{amt:,}** {COOKIE_EMOJI}", inline=True)
        embed.add_field(name="Balance", value=f"{row[3]-amt:,} {COOKIE_EMOJI}", inline=True)
    embed.set_footer(text="50/50 chance · Better luck next time!")
    await send_reply(ctx, embed=embed)

@bot.command()
async def cr(ctx, amount: str):
    """Crash game: 5 clickable boxes, 1 bomb and 4 safe."""
    row = get_user(ctx.guild.id, ctx.author.id)
    amt = parse_amount(amount, row[3])
    if amt is None:
        return await send_reply(ctx, "❌ Invalid amount. Try: `?cr 500`, `?cr 4k`, `?cr 50%`, `?cr all`")
    err = check_bet(row, amt)
    if err:
        return await send_reply(ctx, err)

    bomb_pos = random.randint(0, 4)
    multiplier = round(random.uniform(1.25, 3.5), 2)

    class CrashBoxButton(discord.ui.Button):
        def __init__(self, index):
            super().__init__(
                label=str(index + 1),
                emoji=COOKIE_EMOJI,
                style=discord.ButtonStyle.secondary,
                custom_id=f"cr_{ctx.message.id}_{index}",
            )
            self.index = index

        async def callback(self, interaction: discord.Interaction):
            await self.view.pick(interaction, self.index)

    class CrashBoxView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)
            self.message = None
            self.finished = False
            for index in range(5):
                self.add_item(CrashBoxButton(index))

        async def interaction_check(self, interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("This crash box game is not yours.", ephemeral=True)
                return False
            return True

        def reveal_buttons(self, chosen):
            for child in self.children:
                child.disabled = True
                if child.index == bomb_pos:
                    child.emoji = "💣"
                    child.style = discord.ButtonStyle.danger
                elif child.index == chosen:
                    child.emoji = "✅"
                    child.style = discord.ButtonStyle.success
                else:
                    child.emoji = COOKIE_EMOJI
                    child.style = discord.ButtonStyle.success

        async def on_timeout(self):
            if self.finished or not self.message:
                return
            self.finished = True
            for child in self.children:
                child.disabled = True
            timeout_embed = discord.Embed(
                description=f"⏰ Crash game timed out. Bet of {amt:,} {COOKIE_EMOJI} was refunded.",
                color=0x95A5A6,
            )
            await self.message.edit(embed=timeout_embed, view=self)

        async def pick(self, interaction: discord.Interaction, chosen):
            if self.finished:
                return await interaction.response.send_message("This crash box game already ended.", ephemeral=True)

            current = get_user(ctx.guild.id, ctx.author.id)
            if current[3] < amt:
                self.finished = True
                for child in self.children:
                    child.disabled = True
                broke_embed = discord.Embed(
                    description=f"❌ You need **{amt:,}** {COOKIE_EMOJI} in your jar to open this box.",
                    color=0xE74C3C,
                )
                return await interaction.response.edit_message(embed=broke_embed, view=self)

            self.finished = True
            self.reveal_buttons(chosen)

            if chosen == bomb_pos:
                new_balance = current[3] - amt
                update_user(ctx.guild.id, ctx.author.id, jar=new_balance)
                result = discord.Embed(title="💣 BOOM! You hit the bomb.", color=0xE74C3C)
                result.add_field(name="Lost", value=f"-**{amt:,}** {COOKIE_EMOJI}", inline=True)
                result.add_field(name="Balance", value=f"{new_balance:,} {COOKIE_EMOJI}", inline=True)
            else:
                winnings = int(amt * multiplier)
                new_balance = current[3] + winnings
                update_user(ctx.guild.id, ctx.author.id, jar=new_balance)
                result = discord.Embed(title="Congratulations!", color=0x2ECC71)
                result.description = "You claimed your cookies from a safe box."
                result.add_field(name="Win Amount", value=f"+**{winnings:,}** {COOKIE_EMOJI}", inline=True)
                result.add_field(name="Multiplier", value=f"**{multiplier}x**", inline=True)
                result.add_field(name="Balance", value=f"{new_balance:,} {COOKIE_EMOJI}", inline=True)

            result.set_footer(text=f"Bomb was box {bomb_pos + 1} | Requested by {ctx.author.display_name}")
            await interaction.response.edit_message(embed=result, view=self)

    embed = discord.Embed(title="💥 Crash Box Game!", color=0xE67E22)
    embed.description = (f"**Bet:** {amt:,} {COOKIE_EMOJI}\n"
                          f"**5 boxes** — 4 are safe 🟩, 1 hides a **BOMB** 💣\n"
                          f"Safe box multiplier: **{multiplier}x**\n\n"
                          f"Click one box to open it!")
    embed.add_field(name="Boxes", value="1  2  3  4  5")
    embed.set_footer(text="You have 30 seconds to pick!")
    view = CrashBoxView()
    view.message = await send_reply(ctx, embed=embed, view=view)

@bot.command()
async def slots(ctx, amount: str):
    row = get_user(ctx.guild.id, ctx.author.id)
    amt = parse_amount(amount, row[3])
    if amt is None:
        return await send_reply(ctx, "❌ Invalid amount.")
    err = check_bet(row, amt)
    if err:
        return await send_reply(ctx, err)

    symbols = ["🍒", "🍋", "🍊", "🍇", "⭐", "💎", "🍀"]
    reels = [random.choice(symbols) for _ in range(3)]
    display = " | ".join(reels)

    if reels[0] == reels[1] == reels[2]:
        mult = 8 if reels[0] == "💎" else (5 if reels[0] == "🍀" else 3)
        winnings = amt * mult
        update_user(ctx.guild.id, ctx.author.id, jar=row[3] - amt + winnings)
        embed = discord.Embed(title="Slots Jackpot", color=0xF1C40F)
        embed.add_field(name="Reels", value="[ {} ]".format(display), inline=False)
        embed.add_field(name="Won", value="+{} {} (x{})".format(f"{winnings:,}", COOKIE_EMOJI, mult), inline=True)
        embed.add_field(name="Balance", value="{} {}".format(f"{row[3]-amt+winnings:,}", COOKIE_EMOJI), inline=True)
    elif reels[0] == reels[1] or reels[1] == reels[2]:
        embed = discord.Embed(title="Two of a Kind", color=0x95A5A6)
        embed.add_field(name="Reels", value="[ {} ]".format(display), inline=False)
        embed.add_field(name="Result", value="Bet returned", inline=False)
    else:
        update_user(ctx.guild.id, ctx.author.id, jar=row[3] - amt)
        embed = discord.Embed(title="No Match", color=0xE74C3C)
        embed.add_field(name="Reels", value="[ {} ]".format(display), inline=False)
        embed.add_field(name="Lost", value="-{} {}".format(f"{amt:,}", COOKIE_EMOJI), inline=True)
        embed.add_field(name="Balance", value="{} {}".format(f"{row[3]-amt:,}", COOKIE_EMOJI), inline=True)
    await send_reply(ctx, embed=embed)


@bot.command(aliases=["coinflip", "flip"])
async def cf(ctx, amount: str, choice: str):
    row = get_user(ctx.guild.id, ctx.author.id)
    amt = parse_amount(amount, row[3])
    if amt is None:
        return await send_reply(ctx, "❌ Invalid amount.")
    err = check_bet(row, amt)
    if err:
        return await send_reply(ctx, err)

    choice = choice.lower()
    if choice not in ["heads", "tails", "h", "t"]:
        return await send_reply(ctx, "❌ Choose heads or tails.")

    result = random.choice(["heads", "tails"])
    won = choice[0] == result[0]
    if won:
        update_user(ctx.guild.id, ctx.author.id, jar=row[3] + amt)
        embed = discord.Embed(title="Coin: {} - You Win".format(result.capitalize()), color=0x2ECC71)
        embed.add_field(name="Won", value="+{} {}".format(f"{amt:,}", COOKIE_EMOJI))
        embed.add_field(name="Balance", value="{} {}".format(f"{row[3]+amt:,}", COOKIE_EMOJI))
    else:
        update_user(ctx.guild.id, ctx.author.id, jar=row[3] - amt)
        embed = discord.Embed(title="Coin: {} - You Lose".format(result.capitalize()), color=0xE74C3C)
        embed.add_field(name="Lost", value="-{} {}".format(f"{amt:,}", COOKIE_EMOJI))
        embed.add_field(name="Balance", value="{} {}".format(f"{row[3]-amt:,}", COOKIE_EMOJI))
    await send_reply(ctx, embed=embed)


@bot.command()
async def dice(ctx, amount: str, guess: int):
    row = get_user(ctx.guild.id, ctx.author.id)
    amt = parse_amount(amount, row[3])
    if amt is None:
        return await send_reply(ctx, "❌ Invalid amount.")
    err = check_bet(row, amt)
    if err:
        return await send_reply(ctx, err)
    if not 1 <= guess <= 6:
        return await send_reply(ctx, "❌ Guess a number between 1 and 6.")

    roll = random.randint(1, 6)
    if roll == guess:
        win = amt * 5
        update_user(ctx.guild.id, ctx.author.id, jar=row[3] - amt + win)
        embed = discord.Embed(title="Dice rolled {} - Perfect guess".format(roll), color=0x2ECC71)
        embed.add_field(name="Won", value="+{} {} (x5)".format(f"{win:,}", COOKIE_EMOJI))
        embed.add_field(name="Balance", value="{} {}".format(f"{row[3]-amt+win:,}", COOKIE_EMOJI))
    else:
        update_user(ctx.guild.id, ctx.author.id, jar=row[3] - amt)
        embed = discord.Embed(title="Dice rolled {} - Wrong guess".format(roll), color=0xE74C3C)
        embed.add_field(name="Lost", value="-{} {}".format(f"{amt:,}", COOKIE_EMOJI))
        embed.add_field(name="Balance", value="{} {}".format(f"{row[3]-amt:,}", COOKIE_EMOJI))
    await send_reply(ctx, embed=embed)


@bot.command(aliases=["blackjack"])
async def bj(ctx, amount: str):
    row = get_user(ctx.guild.id, ctx.author.id)
    amt = parse_amount(amount, row[3])
    if amt is None:
        return await send_reply(ctx, "❌ Invalid amount.")
    err = check_bet(row, amt)
    if err:
        return await send_reply(ctx, err)

    player = random.randint(15, 23)
    dealer = random.randint(15, 23)

    if player > 21:
        outcome = "Bust"
        net = -amt
        color = 0xE74C3C
    elif dealer > 21 or player > dealer:
        outcome = "Win"
        net = amt
        color = 0x2ECC71
    elif player == dealer:
        outcome = "Push"
        net = 0
        color = 0x95A5A6
    else:
        outcome = "Lose"
        net = -amt
        color = 0xE74C3C

    update_user(ctx.guild.id, ctx.author.id, jar=row[3] + net)
    embed = discord.Embed(title="Blackjack", color=color)
    embed.add_field(name="Your Total", value=str(player), inline=True)
    embed.add_field(name="Dealer Total", value=str(dealer), inline=True)
    embed.add_field(name="Result", value=outcome, inline=False)
    embed.add_field(name="Balance", value=f"{row[3] + net:,} {COOKIE_EMOJI}", inline=False)
    await send_reply(ctx, embed=embed)

@bot.command(aliases=["roulette"])
async def rl(ctx, amount: str, choice: str):
    row = get_user(ctx.guild.id, ctx.author.id)
    amt = parse_amount(amount, row[3])
    if amt is None:
        return await send_reply(ctx, "❌ Invalid amount.")
    err = check_bet(row, amt)
    if err:
        return await send_reply(ctx, err)
    reds = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    number = random.randint(0, 36)
    color = "red" if number in reds else ("green" if number == 0 else "black")
    choice = choice.lower()
    won = (choice=="red" and color=="red") or (choice=="black" and color=="black") or (choice.isdigit() and int(choice)==number)
    mult = 35 if choice.isdigit() else 2
    if won:
        win = amt * mult
        update_user(ctx.guild.id, ctx.author.id, jar=row[3] + win - amt)
        embed = discord.Embed(title=f"Roulette: {number} ({color}) - Win", color=0x2ECC71)
        embed.add_field(name="Won", value=f"+{win:,} {COOKIE_EMOJI} (x{mult})")
        embed.add_field(name="Balance", value=f"{row[3]+win-amt:,} {COOKIE_EMOJI}")
    else:
        update_user(ctx.guild.id, ctx.author.id, jar=row[3] - amt)
        embed = discord.Embed(title=f"Roulette: {number} ({color}) - Lose", color=0xE74C3C)
        embed.add_field(name="Lost", value=f"-{amt:,} {COOKIE_EMOJI}")
        embed.add_field(name="Balance", value=f"{row[3]-amt:,} {COOKIE_EMOJI}")
    await send_reply(ctx, embed=embed)

# -----------------------------------------------------------------------------
# Truth and dare
# -----------------------------------------------------------------------------
TRUTH_BASE = [
    "What’s the most embarrassing thing you’ve done in public?",
    "What’s a lie you told recently?",
    "Who was your first crush?",
    "What’s the weirdest dream you’ve ever had?",
    "What’s something you’ve never told your parents?",
    "Have you ever stalked someone’s social media for hours?",
    "What’s your biggest fear?",
    "What’s the most childish thing you still do?",
    "Have you ever pretended to be sick to skip something?",
    "What’s the dumbest thing you’ve spent money on?",
    "What’s your guilty pleasure song?",
    "Have you ever cried during a movie? Which one?",
    "What’s the meanest thing you’ve ever said to someone?",
    "What’s your biggest insecurity?",
    "What’s the weirdest food combination you secretly like?",
    "Have you ever had a crush on a friend?",
    "What’s the most awkward text you’ve accidentally sent?",
    "If you could switch lives with anyone for a day, who would it be?",
    "What’s the worst haircut you’ve ever had?",
    "Have you ever blamed someone else for something you did?",
    "What’s your most useless talent?",
    "What’s the strangest rumor you’ve heard about yourself?",
    "What’s something you wish you were better at?",
    "Have you ever snooped through someone’s phone?",
    "What’s the weirdest thing you do when you’re alone?",
    "What’s your biggest pet peeve?",
    "Have you ever laughed at the wrong moment?",
    "What’s the cringiest phase you’ve gone through?",
    "What’s the longest you’ve gone without showering?",
    "What’s a secret you’ve kept from your best friend?",
    "Have you ever had a crush on a teacher or celebrity?",
    "What’s the most awkward interaction you’ve had with a crush?",
    "What’s one thing you regret doing at school?",
    "Have you ever ghosted someone?",
    "What’s your worst habit?",
    "If you had to delete one app forever, which would hurt the most?",
    "What’s your funniest childhood memory?",
    "What’s the most trouble you’ve ever gotten into?",
    "Have you ever broken something and blamed someone else?",
    "What’s your biggest irrational fear?",
    "What’s the weirdest thing in your search history?",
    "What’s your most toxic trait?",
    "Have you ever had an imaginary argument in the shower?",
    "What’s the worst excuse you’ve used?",
    "What’s the most awkward family moment you’ve witnessed?",
    "What’s something you pretend to like but actually don’t?",
    "Have you ever had a crush on two people at once?",
    "What’s your biggest flex?",
    "What’s one thing you’d change about yourself?",
    "What’s the funniest lie you believed as a kid?",
    "What’s the weirdest compliment you’ve ever received?",
    "Have you ever accidentally insulted someone?",
    "What’s the most useless thing you own?",
    "What’s your worst fashion mistake?",
    "What’s the strangest thing you’ve done out of boredom?",
    "What’s your most awkward school memory?",
    "Have you ever pretended to know something you didn’t?",
    "What’s the funniest thing you’ve overheard?",
    "What’s your biggest “instant regret” moment?",
    "What’s the weirdest nickname you’ve ever had?",
    "If I were a snack, what snack would I be?",
    "What song would play when I walk into a room?",
    "If we were in a rom-com, who would fall first?",
    "What’s one cheesy pickup line you secretly like?",
    "If you had to dedicate a love song to someone here, what song would it be?",
    "What’s more powerful: love at first sight or Wi-Fi?",
    "If someone wrote a poem about you, what would the title be?",
    "What’s your idea of the perfect late-night conversation?",
    "If your love life was a movie, what genre would it be?",
    "What’s the corniest thing you’ve ever done for someone you liked?"
]

DARE_BASE = [
    "Do your best celebrity impression for 1 minute.",
    "Send the last meme in your gallery to someone random.",
    "Speak in an accent until your next turn.",
    "Dance with no music for 30 seconds.",
    "Let the group choose your profile picture for a day.",
    "Try to lick your elbow.",
    "Sing the chorus of your favorite song dramatically.",
    "Text someone “I have a confession…” and don’t reply for 10 minutes.",
    "Do 15 jumping jacks while naming animals.",
    "Pretend to be a news reporter covering a ridiculous event.",
    "Eat a snack without using your hands.",
    "Recreate your favorite emoji face.",
    "Let someone scroll through your camera roll for 10 seconds.",
    "Talk like a robot for the next 5 minutes.",
    "Call a friend and talk only in movie quotes.",
    "Wear your shirt backwards for the next 3 rounds.",
    "Make up a rap about the person to your left.",
    "Act like your favorite teacher for 1 minute.",
    "Try to juggle 3 random objects.",
    "Let the group give you a harmless nickname for the rest of the game.",
    "Post “I’m finally famous” on your story.",
    "Eat a spoonful of something spicy or sour.",
    "Pretend the floor is lava for 1 minute.",
    "Let someone type a sentence and make it your status.",
    "Speak only in questions for the next 3 rounds.",
    "Show the weirdest photo on your phone.",
    "Attempt your best runway walk.",
    "Read your last text out loud.",
    "Balance something on your head for 1 minute.",
    "Pretend you’re in a dramatic soap opera scene.",
    "Make your best evil villain laugh.",
    "Try to touch your nose with your tongue.",
    "Act like a cat until your next turn.",
    "Send a random “hey” text to the 7th contact in your phone.",
    "Tell a fake inspirational speech about potatoes.",
    "Let someone draw a tiny doodle on your hand.",
    "Do your best anime character impression.",
    "Spin around 10 times and try to walk straight.",
    "Try to say the alphabet backwards.",
    "Let the group pick a song for you to lip-sync.",
    "Pretend to cry dramatically over losing a pencil.",
    "Wear socks on your hands for 2 minutes.",
    "Imitate another player until someone guesses who it is.",
    "Make up a handshake with the person next to you.",
    "Act like you just won an Oscar.",
    "Say 5 nice things about the person across from you.",
    "Try to freestyle rap for 30 seconds.",
    "Do your best baby voice for 1 minute.",
    "Pretend you’re a fitness influencer teaching a workout.",
    "Let someone choose a word you must use in every sentence for 5 minutes.",
    "Make the weirdest face possible and hold it for 20 seconds.",
    "Narrate everything you do like a nature documentary.",
    "Try to moonwalk across the room.",
    "Call someone and sing “Happy Birthday” even if it’s not their birthday.",
    "Trade one clothing item with the person next to you for 10 minutes.",
    "Attempt a magic trick with random objects.",
    "Talk in slow motion until your next turn.",
    "Let the group ask you 3 rapid-fire questions you must answer instantly.",
    "Pretend to be a waiter taking everyone’s order dramatically.",
    "Try to wink continuously for 30 seconds.",
    "Make a dramatic movie trailer voice about your life.",
    "Let someone style your hair however they want.",
    "Attempt your best football/sports commentary voice.",
    "Pretend you’re a famous influencer doing a livestream.",
    "Act like you’re terrified of a harmless object.",
    "Speak like an old grandparent for 2 minutes.",
    "Try to invent a new dance move.",
    "Hold a funny pose until your next turn.",
    "Do an impression of your favorite fictional character.",
    "Let someone send an emoji-only message from your phone.",
    "Make up a random conspiracy theory on the spot.",
    "Pretend you’re in a cooking show while making a snack.",
    "Do your best “main character” walk.",
    "Speak using only song lyrics for 2 minutes.",
    "Try to do a cartwheel or fake one dramatically.",
    "Tell a joke in the most serious voice possible.",
    "Act like you’re seeing snow for the first time.",
    "Wear a blanket like a superhero cape for the next round.",
    "Pretend your hand is a phone and have a dramatic conversation.",
    "Do your best laugh imitation of someone in the room.",
    "Make up a random holiday and explain how it’s celebrated.",
    "Let the group pick an animal you must imitate.",
    "Try to say a tongue twister 5 times fast.",
    "Walk across the room like a model carrying invisible groceries.",
    "Pretend to be a game show host.",
    "Let someone pick a random object for you to advertise dramatically.",
    "Freeze every time someone says your name until your next turn.",
    "Do your best superhero landing pose.",
    "Pretend you’re teaching aliens how humans use phones.",
    "Make up a ridiculous rumor about yourself.",
    "Let someone choose a funny hairstyle for you.",
    "Speak as if you’re narrating a horror movie.",
    "Try to dance like your parents would at a wedding.",
    "Act like you’re stuck in slow internet buffering.",
    "Pretend you’re a detective solving the mystery of missing snacks.",
    "Make a heart with your hands and dramatically thank the group.",
    "Say the first word that comes to mind after every sentence for 1 minute.",
    "Pretend you’re auditioning for a superhero movie.",
    "Reenact your most embarrassing moment without explaining it.",
    "End the game with your most dramatic mic-drop exit."
]

def _generate_truths(target=1):
    return TRUTH_BASE

def _generate_dares(target=1):
    return DARE_BASE


TRUTHS = _generate_truths(2400)
DARES = _generate_dares(2400)
truth_queue = deque()
dare_queue = deque()


def refill_truth_queue():
    truth_queue.clear()
    shuffled = TRUTHS.copy()
    random.shuffle(shuffled)
    truth_queue.extend(shuffled)


def refill_dare_queue():
    dare_queue.clear()
    shuffled = DARES.copy()
    random.shuffle(shuffled)
    dare_queue.extend(shuffled)


@bot.command()
async def truth(ctx):
    if not truth_queue:
        refill_truth_queue()
    q = truth_queue.popleft()
    embed = discord.Embed(title="Truth", description=q, color=0x3498DB)
    embed.set_footer(text=f"Asked by {ctx.author.display_name} | {len(TRUTHS):,} total truths")
    await send_reply(ctx, embed=embed)


@bot.command()
async def dare(ctx):
    if not dare_queue:
        refill_dare_queue()
    d = dare_queue.popleft()
    embed = discord.Embed(title="Dare", description=d, color=0xE74C3C)
    embed.set_footer(text=f"Dared by {ctx.author.display_name} | {len(DARES):,} total dares")
    await send_reply(ctx, embed=embed)


async def _interaction_embed(ctx, member, column, verb, emoji):
    if not member:
        return await send_reply(ctx, f"❌ Tag someone or reply to their message. Usage: `?{ctx.command.name} @user`")
    if member.bot:
        return await send_reply(ctx, "❌ You can only use this on server members.")
    if member == ctx.author:
        return await send_reply(ctx, "❌ You cannot target yourself.")
    total = add_interaction(ctx.guild.id, member.id, column)
    embed = discord.Embed(color=0x5865F2)
    embed.description = f"{emoji} {ctx.author.mention} **{verb}** {member.mention}"
    if column == "kisses_received":
        embed.add_field(name="Total Kisses Received", value=f"**{total:,}**", inline=False)
    await send_reply(ctx, embed=embed)


@bot.command()
async def hug(ctx, *, target_input: str = None):
    member = await resolve_target(ctx, target_input)
    await _interaction_embed(ctx, member, "hugs_received", "hugged", "🤗")


@bot.command()
async def kiss(ctx, *, target_input: str = None):
    member = await resolve_target(ctx, target_input)
    await _interaction_embed(ctx, member, "kisses_received", "kissed", "😘")


@bot.command()
async def slap(ctx, *, target_input: str = None):
    member = await resolve_target(ctx, target_input)
    await _interaction_embed(ctx, member, "slaps_received", "slapped", "🖐️")


@bot.command()
async def waste(ctx, *, target_input: str = None):
    member = await resolve_target(ctx, target_input)
    await _interaction_embed(ctx, member, "wastes_received", "wasted", "💥")


@bot.command()
async def giveup(ctx, *, target_input: str = None):
    member = await resolve_target(ctx, target_input)
    await _interaction_embed(ctx, member, "giveups_received", "gave up to", "🏳️")


@bot.command()
async def kidnap(ctx, *, target_input: str = None):
    member = await resolve_target(ctx, target_input)
    await _interaction_embed(ctx, member, "kidnaps_received", "kidnapped", "🕶️")


# Moderation - professional
# -----------------------------------------------------------------------------
async def mod_log(guild, embed):
    """Send to log channel if set."""
    ch_id = get_setting(guild.id, "log_channel")
    if ch_id:
        ch = guild.get_channel(int(ch_id))
        if ch:
            try:
                await ch.send(embed=embed)
            except:
                pass

def add_mod_case(guild_id, action, user_id, mod_id, reason):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO mod_cases (guild_id, action, user_id, mod_id, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (str(guild_id), action, str(user_id), str(mod_id), reason, datetime.utcnow().isoformat()),
    )
    case_id = c.lastrowid
    conn.commit()
    conn.close()
    return case_id

def add_warning_record(guild_id, user_id, mod_id, reason):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO warnings (guild_id, user_id, mod_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
        (str(guild_id), str(user_id), str(mod_id), reason, datetime.utcnow().isoformat()),
    )
    warn_id = c.lastrowid
    c.execute("SELECT COUNT(*) FROM warnings WHERE guild_id=? AND user_id=?", (str(guild_id), str(user_id)))
    count = c.fetchone()[0]
    conn.commit()
    conn.close()
    return warn_id, count

def fetch_warnings(guild_id, user_id, limit=20):
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT id, reason, mod_id, created_at FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT ?",
        (str(guild_id), str(user_id), limit),
    )
    rows = c.fetchall()
    conn.close()
    return rows

def clear_warnings_records(guild_id, user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM warnings WHERE guild_id=? AND user_id=?", (str(guild_id), str(user_id)))
    removed = c.rowcount
    conn.commit()
    conn.close()
    return removed

def is_protected_target(ctx, member):
    if member == ctx.author:
        return "You cannot moderate yourself."
    if member == ctx.guild.owner:
        return "You cannot moderate the server owner."
    if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        return "That member has an equal or higher top role than you."
    return None

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    block_reason = is_protected_target(ctx, member)
    if block_reason:
        return await send_reply(ctx, f"❌ {block_reason}")

    case_id = add_mod_case(ctx.guild.id, "ban", member.id, ctx.author.id, reason)
    embed = discord.Embed(title="Member Banned", color=0xE74C3C, timestamp=datetime.utcnow())
    embed.add_field(name="User", value=f"{member} ({member.id})", inline=True)
    embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
    embed.add_field(name="Case", value=f"#{case_id}", inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)

    try:
        await member.send(embed=discord.Embed(title=f"You were banned from {ctx.guild.name}", description=f"**Reason:** {reason}", color=0xE74C3C))
    except:
        pass

    await member.ban(reason=reason)
    await send_reply(ctx, embed=embed)
    await mod_log(ctx.guild, embed)


@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    block_reason = is_protected_target(ctx, member)
    if block_reason:
        return await send_reply(ctx, f"❌ {block_reason}")

    case_id = add_mod_case(ctx.guild.id, "kick", member.id, ctx.author.id, reason)
    embed = discord.Embed(title="Member Kicked", color=0xE67E22, timestamp=datetime.utcnow())
    embed.add_field(name="User", value=f"{member} ({member.id})", inline=True)
    embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
    embed.add_field(name="Case", value=f"#{case_id}", inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)

    try:
        await member.send(embed=discord.Embed(title=f"You were kicked from {ctx.guild.name}", description=f"**Reason:** {reason}", color=0xE67E22))
    except:
        pass

    await member.kick(reason=reason)
    await send_reply(ctx, embed=embed)
    await mod_log(ctx.guild, embed)


@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int = 10, *, reason="No reason provided"):
    if minutes <= 0 or minutes > 40320:
        return await send_reply(ctx, "❌ Duration must be between 1 and 40320 minutes.")

    block_reason = is_protected_target(ctx, member)
    if block_reason:
        return await send_reply(ctx, f"❌ {block_reason}")

    until = discord.utils.utcnow() + timedelta(minutes=minutes)
    case_id = add_mod_case(ctx.guild.id, "mute", member.id, ctx.author.id, reason)
    await member.timeout(until, reason=reason)

    embed = discord.Embed(title="Member Muted", color=0x95A5A6, timestamp=datetime.utcnow())
    embed.add_field(name="User", value=member.mention, inline=True)
    embed.add_field(name="Duration", value=f"{minutes} minutes", inline=True)
    embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
    embed.add_field(name="Case", value=f"#{case_id}", inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Expires", value=f"<t:{int(until.timestamp())}:R>", inline=False)
    await send_reply(ctx, embed=embed)
    await mod_log(ctx.guild, embed)


@bot.command()
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    block_reason = is_protected_target(ctx, member)
    if block_reason:
        return await send_reply(ctx, f"❌ {block_reason}")

    case_id = add_mod_case(ctx.guild.id, "unmute", member.id, ctx.author.id, "Manual unmute")
    await member.timeout(None)
    embed = discord.Embed(title="Member Unmuted", color=0x2ECC71, timestamp=datetime.utcnow())
    embed.add_field(name="User", value=member.mention, inline=True)
    embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
    embed.add_field(name="Case", value=f"#{case_id}", inline=True)
    await send_reply(ctx, embed=embed)
    await mod_log(ctx.guild, embed)


@bot.command()
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    if member.bot:
        return await send_reply(ctx, "❌ You cannot warn bot accounts.")

    block_reason = is_protected_target(ctx, member)
    if block_reason:
        return await send_reply(ctx, f"❌ {block_reason}")

    warn_id, count = add_warning_record(ctx.guild.id, member.id, ctx.author.id, reason)
    case_id = add_mod_case(ctx.guild.id, "warn", member.id, ctx.author.id, reason)

    embed = discord.Embed(title="Member Warned", color=0xF39C12, timestamp=datetime.utcnow())
    embed.add_field(name="User", value=member.mention, inline=True)
    embed.add_field(name="Warning ID", value=f"#{warn_id}", inline=True)
    embed.add_field(name="Total Warnings", value=f"**{count}**", inline=True)
    embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
    embed.add_field(name="Case", value=f"#{case_id}", inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)
    await send_reply(ctx, embed=embed)
    await mod_log(ctx.guild, embed)

    try:
        await member.send(embed=discord.Embed(title=f"Warning in {ctx.guild.name}", description=f"**Reason:** {reason}\n**Total Warnings:** {count}", color=0xF39C12))
    except:
        pass

@bot.command()
async def warnings(ctx, member: discord.Member):
    warns = fetch_warnings(ctx.guild.id, member.id, limit=20)
    if not warns:
        embed = discord.Embed(description=f"OK: {member.mention} has no warnings.", color=0x2ECC71)
        return await send_reply(ctx, embed=embed)

    embed = discord.Embed(title=f"Warnings for {member.display_name}", color=0xF39C12)
    embed.set_thumbnail(url=member.display_avatar.url)
    for warn_id, warn_reason, mod_id, created_at in warns:
        mod_user = ctx.guild.get_member(int(mod_id)) if str(mod_id).isdigit() else None
        mod_text = mod_user.mention if mod_user else f"Moderator {mod_id}"
        try:
            ts = datetime.fromisoformat(created_at).strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            ts = str(created_at)
        embed.add_field(
            name=f"Warning #{warn_id} - {ts}",
            value=f"**Reason:** {warn_reason}\n**By:** {mod_text}",
            inline=False,
        )
    embed.set_footer(text=f"Total: {len(warns)} warning(s)")
    await send_reply(ctx, embed=embed)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def clearwarns(ctx, member: discord.Member):
    removed = clear_warnings_records(ctx.guild.id, member.id)
    case_id = add_mod_case(ctx.guild.id, "clearwarns", member.id, ctx.author.id, f"Cleared {removed} warning(s)")
    embed = discord.Embed(
        description=f"OK: Cleared **{removed}** warning(s) for {member.mention}. Case #{case_id}",
        color=0x2ECC71,
    )
    await send_reply(ctx, embed=embed)

@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 10):
    amount = max(1, min(amount, 100))
    deleted = await ctx.channel.purge(limit=amount)
    msg = await send_reply(
        ctx,
        embed=discord.Embed(description=f"Deleted **{len(deleted)}** messages.", color=0x2ECC71),
    )
    log_embed = discord.Embed(title="Messages Purged", color=0xE74C3C, timestamp=datetime.utcnow())
    log_embed.add_field(name="Channel", value=ctx.channel.mention, inline=True)
    log_embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
    log_embed.add_field(name="Count", value=str(len(deleted)), inline=True)
    await mod_log(ctx.guild, log_embed)
    await asyncio.sleep(3)
    try:
        await msg.delete()
    except Exception:
        pass

@bot.command()
@commands.has_permissions(manage_channels=True)
async def lock(ctx, *, reason="No reason provided"):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False)
    embed = discord.Embed(title="Channel Locked", color=0xE74C3C, timestamp=datetime.utcnow())
    embed.add_field(name="Channel", value=ctx.channel.mention, inline=True)
    embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    await send_reply(ctx, embed=embed)
    await mod_log(ctx.guild, embed)

@bot.command()
@commands.has_permissions(manage_channels=True)
async def unlock(ctx):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=None)
    embed = discord.Embed(title="Channel Unlocked", color=0x2ECC71, timestamp=datetime.utcnow())
    embed.add_field(name="Channel", value=ctx.channel.mention, inline=True)
    embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
    await send_reply(ctx, embed=embed)
    await mod_log(ctx.guild, embed)

@bot.command()
@commands.has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int = 0):
    if seconds < 0 or seconds > 21600:
        return await send_reply(ctx, "Slowmode must be between 0 and 21600 seconds.")
    await ctx.channel.edit(slowmode_delay=seconds)
    embed = discord.Embed(description=f"Slowmode set to **{seconds}s** in {ctx.channel.mention}.", color=0x3498DB)
    embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
    await send_reply(ctx, embed=embed)
    await mod_log(ctx.guild, embed)

@bot.command()
async def serverinfo(ctx):
    guild = ctx.guild
    embed = discord.Embed(title=guild.name, color=0x9B59B6, timestamp=datetime.utcnow())
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=True)
    embed.add_field(name="Members", value=f"{guild.member_count:,}", inline=True)
    embed.add_field(name="Created", value=f"<t:{int(guild.created_at.timestamp())}:D>", inline=True)
    embed.add_field(name="Channels", value=f"{len(guild.text_channels)} text / {len(guild.voice_channels)} voice", inline=True)
    embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
    embed.add_field(name="Emojis", value=str(len(guild.emojis)), inline=True)
    embed.add_field(name="Verification", value=str(guild.verification_level).capitalize(), inline=True)
    embed.add_field(name="Boosts", value=f"{guild.premium_subscription_count} (Tier {guild.premium_tier})", inline=True)
    embed.set_footer(text=f"ID: {guild.id}")
    await send_reply(ctx, embed=embed)

@bot.command()
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    row = get_user(ctx.guild.id, member.id)
    embed = discord.Embed(title=member.display_name, color=member.color if member.color.value else 0x3498DB, timestamp=datetime.utcnow())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Tag", value=str(member), inline=True)
    embed.add_field(name="ID", value=str(member.id), inline=True)
    embed.add_field(name="Account Created", value=f"<t:{int(member.created_at.timestamp())}:D>", inline=True)
    embed.add_field(name="Joined Server", value=f"<t:{int(member.joined_at.timestamp())}:D>" if member.joined_at else "Unknown", inline=True)
    embed.add_field(name="Level", value=str(row[7]), inline=True)
    embed.add_field(name="Cookies", value=f"{row[3] + row[4]:,}", inline=True)
    embed.add_field(name="Messages", value=f"{row[9]:,}", inline=True)
    top_role = member.top_role
    embed.add_field(name="Top Role", value=top_role.mention if top_role != ctx.guild.default_role else "None", inline=True)
    embed.add_field(name="Bot", value="Yes" if member.bot else "No", inline=True)
    embed.set_footer(text=f"Requested by {ctx.author.display_name}")
    await send_reply(ctx, embed=embed)

# SETTINGS
@bot.command()
@commands.has_permissions(administrator=True)
async def setwelcome(ctx, channel: discord.TextChannel):
    set_setting(ctx.guild.id, "welcome_channel", str(channel.id))
    await send_reply(ctx, embed=discord.Embed(description=f"Welcome channel set to {channel.mention}.", color=0x2ECC71))

@bot.command()
@commands.has_permissions(administrator=True)
async def setlog(ctx, channel: discord.TextChannel):
    set_setting(ctx.guild.id, "log_channel", str(channel.id))
    await send_reply(ctx, embed=discord.Embed(description=f"Log channel set to {channel.mention}.", color=0x2ECC71))

@bot.command()
@commands.has_permissions(administrator=True)
async def setauthorole(ctx, role: discord.Role):
    set_setting(ctx.guild.id, "autorole", str(role.id))
    await send_reply(ctx, embed=discord.Embed(description=f"Auto-role set to {role.mention}.", color=0x2ECC71))

@bot.command()
@commands.has_permissions(administrator=True)
async def setlevelchannel(ctx, channel: discord.TextChannel):
    set_setting(ctx.guild.id, "level_channel", str(channel.id))
    await send_reply(ctx, f"✅ Level-up channel set to {channel.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def setmsglog(ctx, channel: discord.TextChannel):
    set_setting(ctx.guild.id, "msg_log_channel", str(channel.id))
    await send_reply(ctx, f"✅ Message log channel set to {channel.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def setvoicelog(ctx, channel: discord.TextChannel):
    set_setting(ctx.guild.id, "voice_log_channel", str(channel.id))
    await send_reply(ctx, f"✅ Voice log channel set to {channel.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def clearslash(ctx):
    try:
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()
        bot.tree.clear_commands(guild=ctx.guild)
        await bot.tree.sync(guild=ctx.guild)
        await send_reply(ctx, "✅ All ghost global and guild slash commands have been successfully permanently deleted from Discord's servers!")
    except Exception as e:
        await send_reply(ctx, f"❌ Failed to clear slash commands: {e}")

# ERROR HANDLER
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await send_reply(ctx, embed=discord.Embed(description="You do not have permission to use this command.", color=0xE74C3C))
    elif isinstance(error, commands.MissingRequiredArgument):
        await send_reply(ctx, embed=discord.Embed(description=f"Missing argument: `{error.param.name}`\nUse `?help` for usage.", color=0xE74C3C))
    elif isinstance(error, commands.BadArgument):
        await send_reply(ctx, embed=discord.Embed(description="Invalid argument. Use `?help` for correct usage.", color=0xE74C3C))
    elif isinstance(error, commands.MemberNotFound):
        await send_reply(ctx, embed=discord.Embed(description="Member not found. Tag them or reply to their message.", color=0xE74C3C))
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        print(f"Unhandled error: {error}")

# RUN
init_db()

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("ERROR: Set DISCORD_TOKEN environment variable!")
else:
    bot.run(TOKEN)




