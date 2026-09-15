"""
Discord Vanity URL Availability Watcher (Render-ready version)
-----------------------------------------------------------------
Runs a tiny web server (so Render's free tier will host it) while a
background thread keeps polling Discord's invite-resolve endpoint for
one or more vanity codes. Pings a Discord webhook the moment a watched
code becomes available.
"""

import os
import time
import threading
import requests
from flask import Flask

# --- Config ---
VANITY_CODES = ["stealanegg", "sae"]
WEBHOOK_URL = "https://discord.com/api/webhooks/1549272234005237870/pyDj7Uyca3X36Ayt-BoNx9Humtfxt-l-QODqEop6Uq9LSM6xV3DIRGHoMwO7-u2zi7xC"
CHECK_INTERVAL_SECONDS = 60 * 5  # 5 minutes
PING_CONTENT = None  # e.g. "<@123456789012345678>" to ping yourself, or None

INVITE_API = "https://discord.com/api/v10/invites/{code}"

app = Flask(__name__)
status = {"last_check": None, "remaining": list(VANITY_CODES)}


@app.route("/")
def home():
    return {
        "status": "running",
        "watching": status["remaining"],
        "last_check": status["last_check"],
    }


def is_available(code: str):
    resp = requests.get(INVITE_API.format(code=code), timeout=10)
    if resp.status_code == 200:
        return False
    if resp.status_code == 404:
        return True
    print(f"[{code}] Unexpected status {resp.status_code}: {resp.text[:200]}")
    return None


def notify_webhook(code: str):
    payload = {
        "content": f"{PING_CONTENT + ' ' if PING_CONTENT else ''}🎉 The vanity URL **discord.gg/{code}** is now available!"
    }
    r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
    r.raise_for_status()


def watch_loop():
    remaining = set(VANITY_CODES)
    while remaining:
        for code in list(remaining):
            try:
                result = is_available(code)
                status["last_check"] = time.strftime("%Y-%m-%d %H:%M:%S")
                if result is True:
                    print(f"[{code}] Available! Sending webhook notification...")
                    notify_webhook(code)
                    remaining.discard(code)
                elif result is False:
                    print(f"[{code}] Still taken.")
            except requests.RequestException as e:
                print(f"[{code}] Request error: {e}")
        status["remaining"] = list(remaining)
        if remaining:
            time.sleep(CHECK_INTERVAL_SECONDS)
    print("All watched codes have been claimed/notified.")


if __name__ == "__main__":
    threading.Thread(target=watch_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
