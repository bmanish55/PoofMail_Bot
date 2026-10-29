import os

from flask import Flask, jsonify, request

from serverless import poll_users

app = Flask(__name__)


@app.get("/")
def cron():
    expected = os.environ.get("CRON_SECRET")
    if expected and request.headers.get("Authorization") != f"Bearer {expected}":
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    poll_users()
    return jsonify({"ok": True})
