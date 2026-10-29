from flask import Flask, jsonify, request

from serverless import handle

app = Flask(__name__)


@app.post("/")
def webhook():
    try:
        handle(request.get_json(force=True))
        return jsonify({"ok": True})
    except Exception:
        return jsonify({"ok": False}), 500
