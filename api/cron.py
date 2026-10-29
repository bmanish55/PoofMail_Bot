import json
import os
from http.server import BaseHTTPRequestHandler

from serverless import poll_users


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        expected = os.environ.get("CRON_SECRET")
        if expected and self.headers.get("Authorization") != f"Bearer {expected}":
            self._respond(401, {"ok": False, "error": "unauthorized"})
            return
        poll_users()
        self._respond(200, {"ok": True})

    def _respond(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
