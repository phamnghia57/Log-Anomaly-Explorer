"""Bat DUNG payload ma worker gui cho webhook alert, khong gui email that.

Dung mot HTTP server tam trong chinh container clustering. Tro
ALERT_WEBHOOK_URL cua container vao http://localhost:8099/hook roi tao mot bat
thuong -> payload that duoc ghi ra /tmp/alert-payload.json va server tat.

Chay detached:  docker compose exec -d clustering python /tmp/webhook_capture.py
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

OUT = "/tmp/alert-payload.json"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            body = {"_raw_khong_phai_json": raw.decode("utf-8", "replace")}
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump({"headers": dict(self.headers), "payload": body}, fh,
                      ensure_ascii=False, indent=2)
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")
        self.server._got_one = True

    def log_message(self, *args):
        pass


server = HTTPServer(("0.0.0.0", 8099), Handler)
server._got_one = False
while not server._got_one:
    server.handle_request()
