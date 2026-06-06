# SyncInk Ticket System Setup Guide

This guide will walk you through setting up, configuring, and deploying the new discord.js Ticket System alongside your existing Python SyncInk bot.

## 1. How to Install Dependencies
1. Open your terminal or command prompt in the `ticket-system` folder: `cd ticket-system`
2. Run the command: `npm install`
This will install all required Node.js packages (`discord.js`, `sqlite3`, `mongoose`, `discord-html-transcripts`, etc.).

## 2. How to Configure the Bot
1. Inside the `ticket-system` folder, rename `.env.example` to `.env`.
2. Open the `.env` file and paste your bot token next to `DISCORD_TOKEN=`. (This must be the same token you use for the Python bot so they run together on the same bot account).
3. Open `config.js` and edit the IDs and visual settings.

## 3. How to Setup MongoDB (Optional Upgrade)
By default, the bot uses **SQLite** for easy plug-and-play setup. If you want to switch to MongoDB for better scalability:
1. Go to [MongoDB Atlas](https://www.mongodb.com/atlas/database) and create a free account.
2. Create a new cluster and create a database user (username and password).
3. Allow access from anywhere (IP `0.0.0.0/0`) in the Network Access tab.
4. Click "Connect", choose "Connect your application", and copy the connection string.
5. In your `.env` file, add `MONGO_URI=` and paste your string. Replace `<password>` with your database user's password.
6. Open `config.js` and change `useMongo: false` to `useMongo: true`.

## 4. How to Create Categories/Channels
1. In your Discord Server, create a new Category named something like **"Support Tickets"**.
2. Right-click the Category, click "Copy ID". Paste this into `config.js` under `ticketCategoryId`.
3. Create a private text channel named **"ticket-logs"** (ensure only staff can see it).
4. Right-click this channel, click "Copy ID". Paste it into `config.js` under `logChannelId`.

## 5. How to Add Role IDs
1. In Discord, go to Server Settings -> Roles.
2. Right-click your Staff, Admin, and Owner roles and copy their IDs.
3. Paste them into `config.js` in the respective arrays (e.g., `staffRoleIds: ['123456789']`).

## 6. How to Customize Ticket Types
In `config.js`, locate the `ticketOptions` array. You can:
- Change the `label`, `description`, and `emoji` for each type.
- To use a custom server emoji, use the format `<:name:ID>` (e.g., `<:shield_fire:1122334455>`).

## 7. Required Bot Intents & Permissions
Ensure your bot has the following privileged intents enabled in the [Discord Developer Portal](https://discord.com/developers/applications):
- **Server Members Intent**
- **Message Content Intent**

The bot requires the following permissions in the server:
- Manage Channels, Manage Threads, View Channels
- Send Messages, Embed Links, Attach Files, Read Message History
- Mention Everyone/Roles

*Why these permissions are needed:*
- **Manage Channels & Threads**: To create private ticket channels and threads.
- **Attach Files**: To send the HTML transcript files.
- **Manage Roles/Permissions**: To grant ticket creators and staff access to the private ticket channels.

## 8. How to Start the Bot
To run both your Python bot and Node.js ticket system locally:
We provided a script called `start_bots.bat` in the main folder. Just double-click it to start both simultaneously.
Alternatively, open two separate terminal windows:
- Window 1: `python "SyncInk discord bot(beta)(1).py"`
- Window 2: `cd ticket-system && node src/index.js`

## 9. How to Deploy on VPS/Hosting
For production deployment, use **PM2** (a process manager):
1. Install PM2 globally: `npm install -g pm2`
2. Start the Python Bot: `pm2 start "SyncInk discord bot(beta)(1).py" --name "SyncInk-Main" --interpreter python`
3. Start the Node.js Ticket Bot: `cd ticket-system && pm2 start src/index.js --name "SyncInk-Tickets"`
4. Run `pm2 save` to ensure they restart if the server reboots.

## 10. How Transcripts, Logs, and Claims work
- **Transcripts**: When a ticket is closed, an HTML file containing the entire chat history (including images/embeds) is generated and sent to the logs channel, as well as DM'd to the user.
- **Logs**: Every action (creation, claim, close) sends a detailed embed to the logs channel.
- **Claims**: When a staff member clicks "Claim" OR sends their first message in a ticket, the system marks them as the active handler and updates the welcome embed.

## 11. How to Fix Common Errors
- **`Missing Access` / `Missing Permissions`**: The bot's role is not high enough or lacks "Manage Channels" permission.
- **MongoError**: Your `MONGO_URI` is incorrect or you didn't whitelist your IP address in MongoDB Atlas.
- **Command Not Found**: You need to wait up to an hour for Discord to sync global slash commands, or kick and re-invite the bot with `applications.commands` scope.
