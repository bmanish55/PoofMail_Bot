import html
import os
import re
import secrets
import string
import time
import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_NAME = "Mãnish Bhavar"
ADMIN_USERNAME = "B_Manishh"
MAIL_API = "https://api.mail.tm"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]


class APIError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.response = type("Response", (), {"status_code": status_code})()


def request_json(method, url, headers=None, payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urlopen(request, timeout=15) as response:
            content = response.read()
            return json.loads(content) if content else None
    except HTTPError as error:
        raise APIError(error.code, error.read().decode("utf-8", errors="replace")) from error


def supabase(method, table, **kwargs):
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    headers.update(kwargs.pop("headers", {}))
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    params = kwargs.pop("params", {})
    if params:
        url += "?" + urlencode(params)
    return request_json(method, url, headers, kwargs.pop("json", None))


def telegram(method, **kwargs):
    data = request_json("POST", f"{TELEGRAM_API}/{method}", {"Content-Type": "application/json"}, kwargs.get("json"))
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Telegram API request failed"))
    return data.get("result")


def mail_api(method, path, token=None, **kwargs):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if "json" in kwargs:
        headers["Content-Type"] = "application/json"
    return request_json(method, MAIL_API + path, headers, kwargs.get("json"))


def user(uid):
    rows = supabase("GET", "mailboxes", params={"user_id": f"eq.{uid}", "limit": "1"})
    return rows[0] if rows else None


def save_user(value):
    supabase(
        "POST",
        "mailboxes",
        params={"on_conflict": "user_id"},
        headers={"Prefer": "resolution=merge-duplicates"},
        json=value,
    )


def update_token(uid, token):
    supabase("PATCH", "mailboxes", params={"user_id": f"eq.{uid}"}, json={"token": token})


def delete_user(uid):
    supabase("DELETE", "mailboxes", params={"user_id": f"eq.{uid}"})


def seen(uid):
    rows = supabase("GET", "seen", params={"user_id": f"eq.{uid}", "select": "msg_id"})
    return {row["msg_id"] for row in rows}


def mark_seen(uid, msg_id):
    supabase(
        "POST",
        "seen",
        params={"on_conflict": "user_id,msg_id"},
        headers={"Prefer": "resolution=ignore-duplicates"},
        json={"user_id": uid, "msg_id": msg_id},
    )


def all_users():
    return supabase("GET", "mailboxes", params={"select": "*"})


def user_api(value, method, path, **kwargs):
    try:
        return mail_api(method, path, value["token"], **kwargs)
    except APIError as error:
        if error.response.status_code != 401:
            raise
        token = mail_api(
            "POST",
            "/token",
            json={"address": value["address"], "password": value["password"]},
        )["token"]
        update_token(value["user_id"], token)
        value["token"] = token
        return mail_api(method, path, token, **kwargs)


def random_value(length=10):
    return "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(length))


def body_of(message):
    text = message.get("text")
    if not text:
        text = re.sub("<[^>]+>", " ", " ".join(message.get("html") or []))
    return re.sub(r"\s+", " ", text or message.get("intro") or "").strip()


def format_mail(message, header="📩 <b>Email</b>"):
    sender = message.get("from", {}).get("address", "unknown")
    subject = message.get("subject") or "(no subject)"
    body = body_of(message)
    match = re.search(r"\b\d{4,8}\b", f"{subject} {body}")
    otp = match.group(0) if match else None
    preview = body[:1200] + ("…" if len(body) > 1200 else "")
    text = (
        f"{header}\n\n<b>From:</b> {html.escape(sender)}\n"
        f"<b>Subject:</b> {html.escape(subject)}"
    )
    if otp:
        text += f"\n\n🔑 <b>OTP:</b> <code>{otp}</code>"
    if preview:
        text += f"\n\n<blockquote>{html.escape(preview)}</blockquote>"
    return text, otp


def keyboard(rows):
    return {"inline_keyboard": rows}


def button(text, callback_data=None, copy_text=None):
    value = {"text": text}
    if callback_data:
        value["callback_data"] = callback_data
    if copy_text:
        value["copy_text"] = {"text": copy_text}
    return value


def command_menu():
    telegram(
        "setMyCommands",
        json={
            "commands": [
                {"command": "start", "description": "Open the menu"},
                {"command": "new", "description": "Generate a new temp email"},
                {"command": "inbox", "description": "Check your inbox"},
                {"command": "delete", "description": "Delete your mailbox"},
                {"command": "contact_admin", "description": "Contact the admin"},
            ]
        },
    )


def send(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return telegram("sendMessage", json=payload)


def edit(query, text, reply_markup=None):
    payload = {"chat_id": query["message"]["chat"]["id"], "message_id": query["message"]["message_id"], "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return telegram("editMessageText", json=payload)


def mailbox_keyboard(address):
    return keyboard([
        [button("📋 Copy Address", copy_text=address)],
        [button("📥 Check Inbox", "inbox")],
        [button("♻️ New Address", "new"), button("🗑 Delete", "delete")],
        [button("👤 Contact Admin", "contact_admin")],
    ])


def menu(chat_id, uid, query=None):
    command_menu()
    value = user(uid)
    if value:
        text = f"✨ <b>Your temporary email</b>\n\n<code>{value['address']}</code>\n\nTap the address to copy. New mail and OTPs arrive here automatically."
        markup = mailbox_keyboard(value["address"])
    else:
        text = "👻 <b>Welcome to PoofMail</b>\n\nGet a disposable email in one tap and receive OTPs right here in Telegram.\n\n• No signup\n• OTP auto-detected\n• Delete anytime"
        markup = keyboard([
            [button("✨ Generate Email", "new")],
            [button("👤 Contact Admin", "contact_admin")],
        ])
    if query:
        edit(query, text, markup)
    else:
        send(chat_id, text, markup)


def create_mailbox(chat_id, uid, query=None):
    domains = mail_api("GET", "/domains")["hydra:member"]
    address = f"{random_value()}@{domains[0]['domain']}"
    password = random_value(16)
    mail_api("POST", "/accounts", json={"address": address, "password": password})
    token = mail_api("POST", "/token", json={"address": address, "password": password})["token"]
    previous = user(uid)
    if previous:
        try:
            account = user_api(previous, "GET", "/me")
            user_api(previous, "DELETE", f"/accounts/{account['id']}")
        except APIError:
            pass
    save_user({"user_id": uid, "chat_id": chat_id, "address": address, "password": password, "token": token, "created_at": time.time()})
    menu(chat_id, uid, query)


def inbox(chat_id, uid, query=None):
    value = user(uid)
    if not value:
        send(chat_id, "You don't have a mailbox yet.", keyboard([[button("✨ Generate Email", "new")]]))
        return
    messages = user_api(value, "GET", "/messages")["hydra:member"][:10]
    rows = [[button(f"📩 {m.get('from', {}).get('address', '?').split('@')[0][:16]} · {(m.get('subject') or '(no subject)')[:24]}", f"read:{m['id']}")] for m in messages]
    rows.append([button("🔄 Refresh", "inbox"), button("⬅️ Back", "menu")])
    text = f"📥 <b>Inbox</b> ({len(messages)})\n<code>{value['address']}</code>\n\nTap a mail to open it."
    if query:
        edit(query, text, keyboard(rows))
    else:
        send(chat_id, text, keyboard(rows))


def handle(update):
    if "callback_query" in update:
        query = update["callback_query"]
        telegram("answerCallbackQuery", json={"callback_query_id": query["id"]})
        uid = query["from"]["id"]
        chat_id = query["message"]["chat"]["id"]
        data = query["data"]
        if data == "new":
            create_mailbox(chat_id, uid, query)
        elif data == "inbox":
            inbox(chat_id, uid, query)
        elif data == "menu":
            menu(chat_id, uid, query)
        elif data == "delete":
            delete_user(uid)
            edit(query, "🗑 <b>Mailbox deleted.</b>\n\nTap below to create a fresh one.", keyboard([[button("✨ Generate Email", "new")]]))
        elif data == "contact_admin":
            contact_message = (
                f"👤 <b>Contact Admin</b>\n\n"
                f"This bot was created by <b>{ADMIN_NAME}</b>.\n"
                "For any query or suggestion, you can message the admin directly:\n\n"
                f"💬 <a href=\"https://t.me/{ADMIN_USERNAME}\">@{ADMIN_USERNAME}</a>"
            )
            edit(query, contact_message)
        elif data.startswith("read:"):
            value = user(uid)
            message = user_api(value, "GET", f"/messages/{data[5:]}")
            text, otp = format_mail(message)
            rows = [[button(f"📋 Copy OTP {otp}", copy_text=otp)]] if otp else []
            rows.append([button("⬅️ Inbox", "inbox")])
            edit(query, text, keyboard(rows))
        return
    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    uid = message.get("from", {}).get("id")
    command = (message.get("text") or "").split("@")[0].split()[0]
    if command in ("/start", "/new", "/contact_admin"):
        if command == "/new":
            create_mailbox(chat_id, uid)
        elif command == "/contact_admin":
            command_menu()
            send(
                chat_id,
                f"👤 <b>Contact Admin</b>\n\nThis bot was created by <b>{ADMIN_NAME}</b>.\n"
                f"For any query or suggestion, you can message the admin directly:\n\n"
                f"💬 <a href=\"https://t.me/{ADMIN_USERNAME}\">@{ADMIN_USERNAME}</a>",
            )
        else:
            menu(chat_id, uid)
    elif command == "/inbox":
        inbox(chat_id, uid)
    elif command == "/delete":
        delete_user(uid)
        send(chat_id, "🗑 <b>Mailbox deleted.</b>\n\nTap below to create a fresh one.", keyboard([[button("✨ Generate Email", "new")]]))


def poll_users():
    for value in all_users():
        try:
            known = seen(value["user_id"])
            messages = user_api(value, "GET", "/messages")["hydra:member"]
            for message in reversed(messages):
                if message["id"] in known:
                    continue
                full = user_api(value, "GET", f"/messages/{message['id']}")
                text, otp = format_mail(full, "🔔 <b>New email received</b>")
                rows = [[button(f"📋 Copy OTP {otp}", copy_text=otp)]] if otp else []
                rows.append([button("📥 Inbox", "inbox")])
                send(value["chat_id"], text, keyboard(rows))
                mark_seen(value["user_id"], message["id"])
        except APIError as error:
            if error.response.status_code in (401, 404):
                delete_user(value["user_id"])
