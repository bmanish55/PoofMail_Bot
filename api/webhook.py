import json
import logging
from http.server import BaseHTTPRequestHandler

from serverless import handle

log = logging.getLogger(__name__)


class handler(BaseHTTPRequestHandler):
    def _respond(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._respond(200, {"ok": True, "service": "PoofMail Telegram webhook"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            update = json.loads(self.rfile.read(length))
            if not isinstance(update, dict):
                self._respond(400, {"ok": False, "error": "invalid Telegram update"})
                return
            handle(update)
            self._respond(200, {"ok": True})
        except Exception:
            log.exception("Telegram webhook failed")
            self._respond(500, {"ok": False})
