import html
import logging
import os
import re
import secrets
import sqlite3
import string
import time

import httpx
from dotenv import load_dotenv
from telegram import (
    BotCommand,
    CopyTextButton,
    InlineKeyboardButton as Btn,
    InlineKeyboardMarkup as Markup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

load_dotenv(override=True)
logging.basicConfig(level=logging.INFO)
# Keep tokens out of the logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
log = logging.getLogger("tempmail")

BOT_TOKEN = os.environ["BOT_TOKEN"]
BOT_NAME = "PoofMail"  # change to your final name
API = "https://api.mail.tm"
DB_PATH = os.getenv("DB_PATH", "tempmail.db")
POLL_SECONDS = 20
NEW_COOLDOWN = 30  # seconds between creating new addresses


# ---------- SQLite persistence ----------

db = sqlite3.connect(DB_PATH)
db.execute("PRAGMA journal_mode=WAL")
db.executescript(
    """
    CREATE TABLE IF NOT EXISTS mailboxes (
        user_id    INTEGER PRIMARY KEY,
        chat_id    INTEGER NOT NULL,
        address    TEXT NOT NULL,
        password   TEXT NOT NULL,
        token      TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS seen (
        user_id INTEGER NOT NULL,
        msg_id  TEXT NOT NULL,
        PRIMARY KEY (user_id, msg_id)
    );
    """
)
db.commit()


def db_save_user(u: dict):
    with db:
        db.execute("DELETE FROM seen WHERE user_id = ?", (u["uid"],))
        db.execute(
            "INSERT OR REPLACE INTO mailboxes VALUES (?, ?, ?, ?, ?, ?)",
            (u["uid"], u["chat_id"], u["address"], u["password"], u["token"], time.time()),
        )


def db_save_token(uid: int, token: str):
    with db:
        db.execute("UPDATE mailboxes SET token = ? WHERE user_id = ?", (token, uid))


def db_delete_user(uid: int):
    with db:
        db.execute("DELETE FROM mailboxes WHERE user_id = ?", (uid,))
        db.execute("DELETE FROM seen WHERE user_id = ?", (uid,))


def db_mark_seen(uid: int, msg_id: str):
    with db:
        db.execute("INSERT OR IGNORE INTO seen VALUES (?, ?)", (uid, msg_id))


def db_load_users() -> dict[int, dict]:
    out: dict[int, dict] = {}
    for uid, chat_id, address, password, token in db.execute(
        "SELECT user_id, chat_id, address, password, token FROM mailboxes"
    ):
        seen = {r[0] for r in db.execute("SELECT msg_id FROM seen WHERE user_id = ?", (uid,))}
        out[uid] = {
            "uid": uid,
            "chat_id": chat_id,
            "address": address,
            "password": password,
            "token": token,
            "seen": seen,
        }
    return out


# user_id -> {"uid", "address", "password", "token", "chat_id", "seen": set()}
users: dict[int, dict] = db_load_users()
last_new: dict[int, float] = {}
log.info("Loaded %d mailbox(es) from %s", len(users), DB_PATH)


# ---------- Helpers ----------

def rand(n: int = 10) -> str:
    return "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(n))


async def api(method: str, path: str, token: str | None = None, **kwargs):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.request(method, API + path, headers=headers, **kwargs)
        r.raise_for_status()
        return r.json() if r.content else None


async def uapi(u: dict, method: str, path: str, **kwargs):
    """API call as a user; on 401 re-login once and retry."""
    try:
        return await api(method, path, token=u["token"], **kwargs)
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 401:
            raise
    tok = await api("POST", "/token", json={"address": u["address"], "password": u["password"]})
    u["token"] = tok["token"]
    db_save_token(u["uid"], u["token"])
    return await api(method, path, token=u["token"], **kwargs)


def find_otp(text: str) -> str | None:
    m = re.search(r"\b\d{4,8}\b", text or "")
    return m.group(0) if m else None


def body_of(msg: dict) -> str:
    text = msg.get("text")
    if not text:
        raw = " ".join(msg.get("html") or [])
        text = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", text or msg.get("intro") or "").strip()


def mail_text(msg: dict, header: str = "📩 <b>Email</b>") -> tuple[str, str | None]:
    sender = msg.get("from", {}).get("address", "unknown")
    subject = msg.get("subject") or "(no subject)"
    body = body_of(msg)
    otp = find_otp(f"{subject} {body}")
    short = body[:1200] + ("…" if len(body) > 1200 else "")
    out = f"{header}\n\n<b>From:</b> {html.escape(sender)}\n<b>Subject:</b> {html.escape(subject)}\n"
    if otp:
        out += f"\n🔑 <b>OTP:</b> <code>{otp}</code>\n"
    if short:
        out += f"\n<blockquote>{html.escape(short)}</blockquote>"
    return out, otp


# ---------- Keyboards ----------

def start_kb() -> Markup:
    return Markup([[Btn("✨ Generate Email", callback_data="new")]])


def mailbox_kb(address: str) -> Markup:
    return Markup([
        [Btn("📋 Copy Address", copy_text=CopyTextButton(text=address))],
        [Btn("📥 Check Inbox", callback_data="inbox")],
        [Btn("♻️ New Address", callback_data="new"), Btn("🗑 Delete", callback_data="delete")],
    ])


def kb_for(uid: int) -> Markup:
    u = users.get(uid)
    return mailbox_kb(u["address"]) if u else start_kb()


async def show(update: Update, text: str, kb: Markup | None = None):
    """Edit the message if triggered by a button, otherwise send a new one."""
    q = update.callback_query
    if q:
        try:
            await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        except BadRequest:
            pass  # "message is not modified"
    else:
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)


# ---------- Screens ----------

async def show_menu(update: Update):
    uid = update.effective_user.id
    u = users.get(uid)
    if u:
        await show(
            update,
            f"✨ <b>Your temporary email</b>\n\n<code>{u['address']}</code>\n\n"
            "Tap the address to copy. New mail and OTPs arrive here automatically.",
            mailbox_kb(u["address"]),
        )
    else:
        await show(
            update,
            f"👻 <b>Welcome to {BOT_NAME}</b>\n\n"
            "Get a disposable email in one tap and receive OTPs right here in Telegram.\n\n"
            "• No signup\n• OTP auto-detected\n• Delete anytime",
            start_kb(),
        )


async def new_mailbox(update: Update):
    uid = update.effective_user.id
    wait = NEW_COOLDOWN - (time.time() - last_new.get(uid, 0))
    if wait > 0:
        await show(update, f"⏳ Please wait {int(wait) + 1}s before creating another address.", kb_for(uid))
        return

    try:
        domains = await api("GET", "/domains")
        domain = domains["hydra:member"][0]["domain"]
        address, password = f"{rand()}@{domain}", rand(16)
        await api("POST", "/accounts", json={"address": address, "password": password})
        tok = await api("POST", "/token", json={"address": address, "password": password})
    except Exception:
        log.exception("create failed")
        await show(update, "❌ Could not create a mailbox right now. Please try again.", kb_for(uid))
        return

    await drop_account(users.get(uid))  # remove the previous one, if any
    last_new[uid] = time.time()
    u = {
        "uid": uid,
        "address": address,
        "password": password,
        "token": tok["token"],
        "chat_id": update.effective_chat.id,
        "seen": set(),
    }
    users[uid] = u
    db_save_user(u)
    await show_menu(update)


async def show_inbox(update: Update):
    uid = update.effective_user.id
    u = users.get(uid)
    if not u:
        await show(update, "You don't have a mailbox yet.", start_kb())
        return
    try:
        msgs = (await uapi(u, "GET", "/messages"))["hydra:member"][:10]
    except Exception:
        await show(update, "❌ Could not fetch your inbox.", mailbox_kb(u["address"]))
        return

    stamp = time.strftime("%H:%M:%S")
    rows = []
    for m in msgs:
        sender = m.get("from", {}).get("address", "?").split("@")[0][:16]
        subject = (m.get("subject") or "(no subject)")[:24]
        rows.append([Btn(f"📩 {sender} · {subject}", callback_data=f"read:{m['id']}")])
    rows.append([Btn("🔄 Refresh", callback_data="inbox"), Btn("⬅️ Back", callback_data="menu")])

    if msgs:
        text = f"📥 <b>Inbox</b> ({len(msgs)})\n<code>{u['address']}</code>\n\nTap a mail to open it.\n<i>Checked {stamp}</i>"
    else:
        text = f"📭 <b>Inbox is empty</b>\n<code>{u['address']}</code>\n\nWaiting for new mail…\n<i>Checked {stamp}</i>"
    await show(update, text, Markup(rows))


async def read_mail(update: Update, msg_id: str):
    u = users.get(update.effective_user.id)
    if not u:
        await show(update, "You don't have a mailbox yet.", start_kb())
        return
    try:
        full = await uapi(u, "GET", f"/messages/{msg_id}")
    except Exception:
        await show(update, "❌ Could not open that email.", Markup([[Btn("⬅️ Inbox", callback_data="inbox")]]))
        return

    text, otp = mail_text(full)
    rows = []
    if otp:
        rows.append([Btn(f"📋 Copy OTP {otp}", copy_text=CopyTextButton(text=otp))])
    rows.append([Btn("⬅️ Inbox", callback_data="inbox"), Btn("🗑 Delete mail", callback_data=f"del:{msg_id}")])
    await show(update, text, Markup(rows))


async def delete_mail(update: Update, msg_id: str):
    u = users.get(update.effective_user.id)
    if u:
        try:
            await uapi(u, "DELETE", f"/messages/{msg_id}")
        except Exception:
            pass
    await show_inbox(update)


async def drop_account(u: dict | None):
    if not u:
        return
    try:
        acc = await uapi(u, "GET", "/me")
        await uapi(u, "DELETE", f"/accounts/{acc['id']}")
    except Exception:
        pass


async def delete_mailbox(update: Update):
    uid = update.effective_user.id
    u = users.pop(uid, None)
    await drop_account(u)
    db_delete_user(uid)
    await show(update, "🗑 <b>Mailbox deleted.</b>\n\nTap below to create a fresh one.", start_kb())


# ---------- Handlers ----------

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await show_menu(update)


async def cmd_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await new_mailbox(update)


async def cmd_inbox(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await show_inbox(update)


async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await delete_mailbox(update)


async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data == "new":
        await new_mailbox(update)
    elif data == "inbox":
        await show_inbox(update)
    elif data == "menu":
        await show_menu(update)
    elif data == "delete":
        await delete_mailbox(update)
    elif data.startswith("read:"):
        await read_mail(update, data[5:])
    elif data.startswith("del:"):
        await delete_mail(update, data[4:])


# ---------- Background poller: auto-forward new mail / OTP ----------

async def poll(ctx: ContextTypes.DEFAULT_TYPE):
    for uid, u in list(users.items()):
        try:
            msgs = (await uapi(u, "GET", "/messages"))["hydra:member"]
            for m in reversed(msgs):
                if m["id"] in u["seen"]:
                    continue
                full = await uapi(u, "GET", f"/messages/{m['id']}")
                text, otp = mail_text(full, header="🔔 <b>New email received</b>")
                rows = []
                if otp:
                    rows.append([Btn(f"📋 Copy OTP {otp}", copy_text=CopyTextButton(text=otp))])
                rows.append([Btn("📥 Inbox", callback_data="inbox")])
                await ctx.bot.send_message(
                    u["chat_id"], text, parse_mode=ParseMode.HTML, reply_markup=Markup(rows)
                )
                u["seen"].add(m["id"])
                db_mark_seen(uid, m["id"])
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 404):
                # Mailbox no longer exists on mail.tm: clean up and tell the user
                users.pop(uid, None)
                db_delete_user(uid)
                try:
                    await ctx.bot.send_message(
                        u["chat_id"],
                        "⚠️ Your temporary mailbox has expired.\nTap below to create a new one.",
                        reply_markup=start_kb(),
                    )
                except Exception:
                    pass
            else:
                log.warning("poll HTTP error for %s: %s", uid, e.response.status_code)
        except Exception:
            log.exception("poll failed for %s", uid)


async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "Open the menu"),
        BotCommand("new", "Generate a new temp email"),
        BotCommand("inbox", "Check your inbox"),
        BotCommand("delete", "Delete your mailbox"),
    ])


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("inbox", cmd_inbox))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(CallbackQueryHandler(on_button))
    app.job_queue.run_repeating(poll, interval=POLL_SECONDS, first=POLL_SECONDS)
    app.run_polling()


if __name__ == "__main__":
    main()
