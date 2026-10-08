"""
Daily Kite login without copy-paste (owner, 2026-10-08).

You still log in yourself (password + TOTP) - Zerodha requires a manual login
every day. This only removes the copy-paste step: it opens the login page and
catches the redirect on this PC, then saves today's session like kite_auth.py.

One-time setup on developers.kite.trade -> app "Sniper_Bot" -> Redirect URL:
    http://127.0.0.1:5000/callback

    py src\\auto_login.py            (exit code 0 = logged in, 1 = gave up)
"""

from __future__ import annotations

import json
import os
import sys
import threading
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from kiteconnect import KiteConnect

from kite_auth import SESSION_FILE, _api_key

PORT = 5000
WAIT_MINUTES = 30


def session_is_today() -> bool:
    try:
        return json.loads(SESSION_FILE.read_text()).get("date") == date.today().isoformat()
    except (OSError, ValueError):
        return False


def main() -> int:
    if session_is_today():
        print("Already logged in today.", flush=True)
        return 0
    api_key = _api_key()
    api_secret = os.getenv("KITE_API_SECRET")
    if not api_secret:
        print("KITE_API_SECRET missing in .env", flush=True)
        return 1
    kite = KiteConnect(api_key=api_key)
    result: dict[str, str] = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server API
            token = parse_qs(urlparse(self.path).query).get("request_token", [""])[0]
            if not token:
                self._reply(400, "No request_token in this address - log in again from the Zerodha page.")
                return
            try:
                session = kite.generate_session(token, api_secret=api_secret)
            except Exception as error:  # show it in the browser, keep waiting for another try
                self._reply(500, f"Zerodha rejected the login: {error}. Log in again.")
                return
            SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            SESSION_FILE.write_text(json.dumps({"access_token": session["access_token"],
                                                "date": date.today().isoformat()}))
            result["user"] = str(session.get("user_name", session.get("user_id", "?")))
            self._reply(200, f"Logged in as {result['user']}. The 4 paper bots are starting - you can close this tab.")
            done.set()

        def _reply(self, code: int, text: str) -> None:
            body = f"<html><body style='font-family:sans-serif;font-size:20px;padding:40px'>{text}</body></html>"
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def log_message(self, *args):  # keep the console quiet
            pass

    server = HTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Opening Zerodha login - waiting up to {WAIT_MINUTES} minutes for it to finish.", flush=True)
    webbrowser.open(kite.login_url())
    ok = done.wait(WAIT_MINUTES * 60)
    server.shutdown()
    if not ok:
        print("Login not completed in time - bots not started.", flush=True)
        return 1
    print(f"Logged in as {result['user']}. Session saved for today.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
