import logging

from flask import Flask, jsonify, request

from serverless import handle

app = Flask(__name__)
log = logging.getLogger(__name__)


@app.get("/")
def health():
    return jsonify({"ok": True, "service": "PoofMail Telegram webhook"})


@app.post("/")
def webhook():
    try:
        update = request.get_json(silent=True)
        if not isinstance(update, dict):
            return jsonify({"ok": False, "error": "invalid Telegram update"}), 400
        handle(update)
        return jsonify({"ok": True})
    except Exception:
        log.exception("Telegram webhook failed")
        return jsonify({"ok": False}), 500
