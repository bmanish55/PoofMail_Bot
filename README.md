<div align="center">

# 👻 PoofMail

**A disposable email inbox, delivered through Telegram.**

Generate a temporary email address in one tap, receive messages and OTPs automatically, and delete the mailbox whenever you are done.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Telegram](https://img.shields.io/badge/Platform-Telegram%20Bot-26A5E4?logo=telegram&logoColor=white)](https://core.telegram.org/bots/api)
[![Mail.tm](https://img.shields.io/badge/Email%20provider-mail.tm-6366F1)](https://mail.tm/)
[![SQLite](https://img.shields.io/badge/Storage-SQLite-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)

</div>

---

## 📖 What is PoofMail?

PoofMail is a Telegram bot for creating and managing disposable email inboxes without requiring a separate website or account. A user starts the bot, generates an address, and receives incoming messages directly in the Telegram chat.

The bot uses the [mail.tm API](https://api.mail.tm/) as its temporary-mail provider. Each Telegram user can have one active mailbox at a time. The bot stores the mailbox credentials locally so it can restore the session after a restart and continue checking for new mail.

### ✨ Highlights

- Generate a random temporary email address with one tap
- Copy the address directly from Telegram
- Browse the latest messages in the inbox
- Automatically detect common numeric OTP codes
- Push new messages to Telegram in the background
- Copy detected OTPs with a dedicated button
- Replace or delete a mailbox at any time
- Persist mailbox state across restarts with SQLite
- Recover automatically when a mail.tm token expires

> **Privacy note:** Disposable email is not suitable for account recovery, financial services, or sensitive communication. The mailbox credentials and message metadata are stored in the local SQLite database, and email content is processed through mail.tm.

---

## 🧰 Technology stack

| Area | Technology | Purpose |
|---|---|---|
| Telegram interface | Telegram Bot API | Receives commands, displays menus, and sends email notifications |
| Bot framework | `python-telegram-bot` | Async handlers, callback buttons, command registration, and job scheduling |
| Temporary email | mail.tm REST API | Creates accounts, authenticates users, lists messages, and deletes mailboxes |
| HTTP client | `httpx` | Makes asynchronous requests to mail.tm |
| Persistence | SQLite | Stores active mailbox credentials and already-notified message IDs |
| Configuration | `python-dotenv` | Loads `BOT_TOKEN` and optional settings from `.env` |
| Runtime | Python 3.10+ | Runs the bot and its background polling job |

For Vercel deployment, PoofMail additionally uses Flask-compatible Python functions and Supabase REST API storage. The original long-polling mode remains available through `python bot.py`; the Vercel mode uses [`api/webhook.py`](./api/webhook.py) and [`api/cron.py`](./api/cron.py).

---

## 🏗️ Architecture

```text
┌──────────────────────┐
│   User in Telegram   │
│ commands / buttons   │
└──────────┬───────────┘
           │ Telegram Bot API
           ▼
┌────────────────────────────────────────────┐
│              PoofMail (serverless)           │
│                                            │
│  Command handlers  ·  Callback handlers   │
│  Mailbox lifecycle · OTP/message formatter │
│  Background polling job every 20 seconds   │
└───────────────┬──────────────────┬─────────┘
                │                  │
                │ REST API         │ local persistence
                ▼                  ▼
       ┌─────────────────┐  ┌──────────────────┐
       │    mail.tm      │  │ SQLite database   │
       │ accounts/inbox  │  │ tempmail.db      │
       └─────────────────┘  └──────────────────┘
```

### Main components

#### Telegram handlers

`/start`, `/new`, `/inbox`, and `/delete` are registered as Telegram commands. Inline keyboard callbacks provide the same actions without requiring users to type commands.

#### mail.tm integration

The bot:

1. Retrieves an available mail.tm domain.
2. Generates a random address and password.
3. Creates a mail.tm account.
4. Logs in to receive an API token.
5. Uses the token to list, read, and delete messages.
6. Deletes the previous mailbox when a user creates a replacement.

Authenticated API calls are wrapped by `uapi()`. If mail.tm returns `401`, the bot logs in again using the saved address and password, updates SQLite, and retries the request once.

#### Background poller

The scheduled `poll()` job runs every 20 seconds. For each active mailbox it:

1. Fetches the mailbox message list.
2. Skips message IDs already recorded in the user’s `seen` set.
3. Fetches each new message in full.
4. Extracts the plain-text or HTML body.
5. Detects a 4–8 digit OTP when present.
6. Sends a formatted notification to the user.
7. Persists the message ID so it is not sent again.

#### Message formatting

Email HTML is converted into readable text when a plain-text body is unavailable. Sender names, subjects, and message bodies are HTML-escaped before being sent using Telegram HTML parse mode. Message previews are limited to 1,200 characters.

---

## 🔄 User flow

```text
/start
   │
   ├── No mailbox ──► Generate Email
   │                      │
   │                      ├── mail.tm account created
   │                      ├── token issued
   │                      └── credentials saved locally
   │
   └── Existing mailbox ──► Show address and mailbox actions
                              │
                              ├── Copy Address
                              ├── Check Inbox
                              ├── New Address
                              └── Delete
```

When a new address is generated, the previous mail.tm account is deleted where possible. New-address creation is rate-limited to once every 30 seconds per Telegram user.

---

## 💾 Data model

PoofMail creates two SQLite tables on startup:

### `mailboxes`

Stores one active mailbox per Telegram user:

| Column | Description |
|---|---|
| `user_id` | Telegram user ID; primary key |
| `chat_id` | Chat where notifications are delivered |
| `address` | Temporary email address |
| `password` | Password used to authenticate with mail.tm |
| `token` | Current mail.tm API token |
| `created_at` | Creation timestamp |

### `seen`

Stores `(user_id, msg_id)` pairs for messages already forwarded to Telegram. The composite primary key prevents duplicate records.

SQLite write-ahead logging (WAL) is enabled to improve reliability for reads and writes while the polling job is active.

> `tempmail.db`, SQLite WAL files, `.env`, virtual environments, and Python cache directories are excluded by [`.gitignore`](./.gitignore). Never commit a real bot token or mailbox credentials.

---

## 🚀 Getting started

### 1. Prerequisites

- Python 3.10 or newer
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- Network access to Telegram and `api.mail.tm`

### 2. Install dependencies

```bash
python -m venv venv
```

Windows PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS/Linux:

```bash
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure the environment

Create a `.env` file in the project root based on [`env.example`](./env.example):

```env
BOT_TOKEN=your_telegram_bot_token
```

`DB_PATH` is optional. By default, the bot creates `tempmail.db` in the project directory:

```env
BOT_TOKEN=your_telegram_bot_token
DB_PATH=tempmail.db
```

### 4. Run the bot

```bash
python bot.py
```

The bot uses Telegram long polling, so keep the process running. On startup it loads saved mailboxes from SQLite and registers the Telegram command menu.

---

## ☁️ Deploying on Vercel

The Vercel deployment uses Telegram webhooks instead of long polling:

```text
Telegram ──► /api/webhook ──► Supabase
                                  ▲
Vercel Cron ──► /api/cron ────────┘
                                  │
                                  ▼
                              mail.tm API
```

### 1. Create the Supabase database

Create a Supabase project, open the SQL Editor, and run [`supabase_schema.sql`](./supabase_schema.sql). The Vercel functions use the Supabase service-role key server-side; never expose this key in browser code or commit it to Git.

### 2. Add Vercel environment variables

Configure these variables for Production, Preview, and Development as appropriate:

```env
BOT_TOKEN=your_telegram_bot_token
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_supabase_service_role_key
CRON_SECRET=use_a_long_random_value
```

`CRON_SECRET` protects the inbox polling endpoint from unauthorized manual calls. Vercel automatically sends it when invoking a configured Cron function.

### 3. Deploy

Install the Vercel CLI and deploy from the project directory:

```bash
npm install -g vercel
vercel login
vercel
vercel --prod
```

After deployment, the webhook URL will be:

```text
https://your-project.vercel.app/api/webhook
```

Register it with Telegram:

```text
https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://your-project.vercel.app/api/webhook
```

On the Vercel Hobby plan, automatic Cron jobs more frequent than once per day are not available. This project therefore does not configure a Cron job by default. Users should tap **Check Inbox** to fetch messages immediately. The `/api/cron` endpoint remains available for a future paid Vercel plan or an external scheduler.

To confirm the webhook:

```text
https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo
```

The Vercel implementation stores mailbox credentials and seen message IDs in Supabase. It does not use `tempmail.db`.

---

## 🎛️ Commands and controls

| Command | Action |
|---|---|
| `/start` | Open the main menu |
| `/new` | Generate a new temporary address |
| `/inbox` | Fetch and display up to 10 latest messages |
| `/delete` | Delete the active mailbox |

Inline buttons provide address copying, inbox refresh, opening a message, OTP copying, mailbox replacement, message deletion, and navigation back to the menu.

---

## ⚙️ Operational behavior

- Only one active mailbox is maintained per Telegram user.
- The inbox view displays the 10 latest messages returned by mail.tm.
- New messages are automatically pushed by the scheduled poller.
- OTP detection searches the subject and body for the first standalone sequence of 4–8 digits.
- A 30-second cooldown prevents rapid mailbox creation.
- HTTP clients use a 15-second request timeout.
- A missing or expired mail.tm mailbox is removed from local state and reported to the user.
- Recoverable message/API failures are shown in Telegram and detailed exceptions are logged server-side.

---

## ⚠️ Limitations and security considerations

- This is a disposable mailbox, not a permanent email service.
- mail.tm availability, domain availability, account expiration, and rate limits are outside PoofMail’s control.
- Mailbox passwords and API tokens are stored in the local SQLite database so the bot can restore sessions. Protect the host and database file.
- Do not expose `.env`, `tempmail.db`, or logs containing operational details.
- OTP detection is heuristic. It may identify an unrelated number or miss an OTP with a different format.
- The bot is intended for personal or small-scale use. Review Telegram and mail.tm usage limits before deploying publicly.
- Use a process manager such as systemd, Docker, or a Windows service if the bot must restart automatically in production.

---

## 📁 Project structure

```text
poofmail/
├── bot.py             # Local long-polling bot, mail.tm client, persistence, and poller
├── env.example        # Safe configuration template
├── pyproject.toml      # Vercel Python entrypoint configuration
├── requirements.txt   # Python dependencies
├── .gitignore         # Secrets, database, and runtime-file exclusions
└── tempmail.db        # Generated SQLite data (not committed)
```

---

<div align="center">

Made with ❤️ by **Manish Bhavar**

[GitHub](https://github.com/bmanish55)

</div>
