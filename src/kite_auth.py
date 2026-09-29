"""
Daily Kite Connect login. Run once each trading day before the bot:

    py src\\kite_auth.py

It opens Zerodha's login page; after you log in, Zerodha redirects your
browser to the app's redirect URL (the page itself may fail to load - that is
fine). Copy the full address from the browser bar and paste it here. The
access token is saved to .cache/kite_session.json and is valid until about
6 AM the next day (Zerodha's rule), so this has to be repeated daily.

Credentials come from .env (never commit it - it is gitignored):
    KITE_API_KEY=...
    KITE_API_SECRET=...
"""

from __future__ import annotations

import json
import os
import webbrowser
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from kiteconnect import KiteConnect
from kiteconnect.exceptions import InputException, TokenException

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SESSION_FILE = PROJECT_ROOT / ".cache" / "kite_session.json"


def _api_key() -> str:
    load_dotenv(PROJECT_ROOT / ".env")
    key = os.getenv("KITE_API_KEY")
    if not key:
        raise SystemExit(f"KITE_API_KEY missing - copy .env.example to .env in {PROJECT_ROOT} and fill it in.")
    return key


def request_token_from(pasted: str) -> str:
    """Accepts the full redirect URL, or just the request token itself."""
    pasted = pasted.strip()
    if "request_token=" in pasted:
        return parse_qs(urlparse(pasted).query)["request_token"][0]
    if "://" in pasted:
        raise SystemExit(
            "That address has no request_token - the login hadn't finished yet. Wait until the browser "
            "reaches https://127.0.0.1/?request_token=... (click Authorize if Zerodha asks), then run this again."
        )
    return pasted


def login() -> None:
    api_key = _api_key()
    api_secret = os.getenv("KITE_API_SECRET")
    if not api_secret:
        raise SystemExit("KITE_API_SECRET missing in .env")

    kite = KiteConnect(api_key=api_key)
    print("Opening Zerodha login in your browser. If it doesn't open, visit:\n")
    print(f"  {kite.login_url()}\n")
    webbrowser.open(kite.login_url())
    pasted = input("After logging in, paste the full address from the browser bar here:\n> ")

    try:
        session = kite.generate_session(request_token_from(pasted), api_secret=api_secret)
    except TokenException as error:
        raise SystemExit(
            f"\nZerodha rejected the login: {error}\n"
            "Paste the WHOLE address starting https://127.0.0.1/?request_token=... (not the sess_id from a\n"
            "kite.zerodha.com/connect/finish address), right after it appears - each one works only once,\n"
            "for a few minutes. Run  py src\\kite_auth.py  again to get a fresh one."
        ) from None
    except InputException as error:
        raise SystemExit(f"\nZerodha rejected the API key/secret: {error}\nCheck KITE_API_KEY and KITE_API_SECRET in .env.") from None
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps({"access_token": session["access_token"], "date": date.today().isoformat()}))
    print(f"\nLogged in as {session.get('user_name', session.get('user_id', '?'))}. Session saved for today.")


def connected_client() -> KiteConnect:
    """A KiteConnect client using today's saved session."""
    api_key = _api_key()
    if not SESSION_FILE.exists():
        raise SystemExit("Not logged in today - run:  py src\\kite_auth.py")
    saved = json.loads(SESSION_FILE.read_text())
    if saved.get("date") != date.today().isoformat():
        raise SystemExit("Saved Zerodha session is from an earlier day - run:  py src\\kite_auth.py")
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(saved["access_token"])
    return kite


if __name__ == "__main__":
    login()
