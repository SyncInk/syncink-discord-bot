# SyncInk Discord Bot

Major update includes:

- Reply-compatible crime targeting: `?rob` and `?heist` now work by mention, ID, username, or replying to a message.
- Fast direct betting: `?bet 4k` is instant 50/50 win/lose (no reaction flow).
- Crash game with 5 picks: `?cr <amount>` shows 5 clickable boxes, 1 bomb and 4 safe options.
- Amounts support shortcuts like `4k`, `2.5k`, `50%`, `90%`, `all`, and `half`.
- Bot command responses reply to the command message to keep channels cleaner.
- Weekly message reset for rob cooldown tiers:
  - 200+ weekly messages: 5 min rob cooldown
  - 100+ weekly messages: 10 min rob cooldown
  - below 100: 15 min rob cooldown
- Progression roles and rewards:
  - Level milestone roles: `5,10,15,20,35,45,50,60,65,70,75,80,90,100`
  - Message milestone roles (includes 100 and 200 with cookie gifts)
  - VC milestone roles (2h, 5h, 7h, 10h, 15h, 18h, 20h, 24h, 28h)
- Social commands:
  - `?hug`, `?kiss`, `?slap`, `?waste`, `?giveup`, `?kidnap`
  - `?kiss` tracks how many kisses each member has received
- Economy:
  - Vault size is fixed at 3000 cookies for everyone
- Professional moderation upgrade:
  - Persistent warnings stored in SQLite (survive restarts)
  - Moderation case IDs for `ban`, `kick`, `mute`, `unmute`, `warn`, `clearwarns`
- Truth or Dare expansion:
  - 2400+ truths and 2400+ dares generated at startup
  - Fast non-repeating queue flow
- Bot filtering:
  - Leaderboard hides bot accounts
  - Bots do not earn message-based progression
- Data safety:
  - Existing `bot_data.db` balances/history are preserved
  - Schema is migrated in place (no reset required)
