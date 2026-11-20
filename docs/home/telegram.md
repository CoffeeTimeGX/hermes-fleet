# Telegram

Telegram lets you talk to the director, Hermes' `director` profile, from your phone,
and it is where the scheduled health alerts and daily reports arrive. Hermes' gateway
runs on your home PC and connects out to Telegram, so nothing on your PC is opened to
the internet.

## 1. Create the bot

1. In Telegram, search for **@BotFather** and send `/newbot`.
2. Choose a display name (for example *Fleet Director*) and a username that ends in
   `bot` and is not taken yet.
3. BotFather replies with a token like `7123456789:AAF...`. Treat it like a password:
   anyone with it can control the bot.

## 2. Find your user id

Send any message to **@userinfobot**. It answers with your numeric user id, for example
`123456789`. This is a number, not your @username. Only the ids you list can talk to
the bot.

## 3. Connect the director

Run the setup wizard for the director and choose Telegram:

```
hermes -p director gateway setup
```

It asks for the bot token and the allowed user ids, and saves them in the director's
`.env` file as `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_USERS` (several ids are
separated by commas). You can also set them directly:

```
hermes -p director config set TELEGRAM_BOT_TOKEN 7123456789:AAF...
hermes -p director config set TELEGRAM_ALLOWED_USERS 123456789
```

A bot token belongs to one profile. Do not put the same token in Hermes' default
profile too.

## 4. Keep the gateway running

One Hermes gateway serves every profile, the director included, so these commands have
no `-p director`:

```
hermes gateway install
hermes gateway start
hermes gateway status
```

- **Windows:** `install` registers a scheduled task named `Hermes_Gateway` that starts
  the gateway when you log in. It stops when you log out, so stay logged in (a locked
  screen is fine). See [Keep it running](always-on.md).
- **Linux and macOS:** `install` sets up a background service for your user.

The gateway also runs Hermes' scheduled jobs, so the [scheduled checks](../operations/scheduled-checks.md)
only work while it runs.

## 5. Choose where reports go

Open the chat with your bot and send `/sethome`. Scheduled jobs deliver their messages
to this "home channel" (Hermes saves it as `TELEGRAM_HOME_CHANNEL`). A private chat with
the bot is the simplest choice.

## What to ask

Talk to it in plain language. A few examples:

- *"How is the fleet?"*
- *"Make a 60-second short for Space Facts about Saturn's rings."*
- *"Queue tomorrow's three videos for the History channel."*
- *"What failed today, and why?"*
- *"Collect the finished videos."*
- *"Pause vps2, I want to update it."*

The director answers briefly on Telegram and leads with the result. For anything that
changes a server (closing SSH, rebooting, wiping) or moves work to another VPS, it says
what it will do and asks first.

## Keep the bot private

- Keep `TELEGRAM_ALLOWED_USERS` to your own id. Do not add the bot to groups.
- If the token leaks, send `/revoke` to @BotFather, then run
  `hermes -p director gateway setup` again with the new token.
- Never paste API keys or tokens into the chat. Hermes will not ask for them: secrets
  go into files on your PC (see [Rotate credentials](../runbooks/rotate-credentials.md)).
