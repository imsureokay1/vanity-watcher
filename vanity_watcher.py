"""
Discord Vanity URL Availability Watcher (Render-ready version)
-----------------------------------------------------------------
Runs a tiny web server (so Render's free tier will host it) while a
background thread keeps polling Discord's invite-resolve endpoint for
one or more vanity codes.

- Checks every CHECK_INTERVAL_SECONDS (default: 5 min).
- Sends a STATUS UPDATE to the webhook every STATUS_UPDATE_EVERY_N_CHECKS
  checks (default: every 12th check = hourly), with no ping.
- Sends a SEPARATE @everyone-pinging message immediately the moment a
  code actually becomes available (this always fires right away,
  regardless of the status update schedule).
"""

import os
import time
import threading
import requests
from flask import Flask

# --- Config ---
VANITY_CODES = ["stealanegg", "sae"]
WEBHOOK_URL = "https://discord.com/api/webhooks/1549272234005237870/pyDj7Uyca3X36Ayt-BoNx9Humtfxt-l-QODqEop6Uq9LSM6xV3DIRGHoMwO7-u2zi7xC"
CHECK_INTERVAL_SECONDS = 60 * 5  # 5 minutes between checks
STATUS_UPDATE_EVERY_N_CHECKS = 12  # 12 checks * 5 min = status update every hour

INVITE_API = "https://discord.com/api/v10/invites/{code}"

app = Flask(__name__)
status = {"last_check": None, "remaining": list(VANITY_CODES), "checks_done": 0}


@app.route("/")
def home():
    return {
        "status": "running",
        "watching": status["remaining"],
        "last_check": status["last_check"],
        "checks_done": status["checks_done"],
        "status_update_every_n_checks": STATUS_UPDATE_EVERY_N_CHECKS,
    }


def is_available(code: str):
    resp = requests.get(INVITE_API.format(code=code), timeout=10)
    if resp.status_code == 200:
        return False
    if resp.status_code == 404:
        return True
    print(f"[{code}] Unexpected status {resp.status_code}: {resp.text[:200]}")
    return None


def send_status_update(results: dict):
    """Send a plain status update, guaranteed NOT to ping anyone."""
    lines = []
    for code, result in results.items():
        if result is True:
            lines.append(f"✅ discord.gg/{code} — AVAILABLE")
        elif result is False:
            lines.append(f"❌ discord.gg/{code} — still taken")
        else:
            lines.append(f"⚠️ discord.gg/{code} — check inconclusive")

    payload = {
        "content": "**Vanity check update:**\n" + "\n".join(lines),
        "allowed_mentions": {"parse": []},  # hard block on any mentions/pings
    }
    r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
    r.raise_for_status()


def send_availability_ping(code: str):
    """Send the @everyone-pinging alert when a code frees up."""
    payload = {
        "content": f"@everyone 🎉 The vanity URL **discord.gg/{code}** is now available!",
        "allowed_mentions": {"parse": ["everyone"]},  # explicitly allow this ping
    }
    r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
    r.raise_for_status()


def watch_loop():
    remaining = set(VANITY_CODES)
    checks_done = 0

    while remaining:
        results = {}
        for code in list(remaining):
            try:
                result = is_available(code)
                results[code] = result
                status["last_check"] = time.strftime("%Y-%m-%d %H:%M:%S")
                if result is True:
                    print(f"[{code}] Available! Sending @everyone ping...")
                    send_availability_ping(code)
                    remaining.discard(code)
                elif result is False:
                    print(f"[{code}] Still taken.")
            except requests.RequestException as e:
                print(f"[{code}] Request error: {e}")
                results[code] = None

        checks_done += 1
        status["checks_done"] = checks_done
        status["remaining"] = list(remaining)

        # Only send the no-ping status update every Nth check
        if checks_done % STATUS_UPDATE_EVERY_N_CHECKS == 0:
            try:
                send_status_update(results)
            except requests.RequestException as e:
                print(f"Failed to send status update: {e}")

        if remaining:
            time.sleep(CHECK_INTERVAL_SECONDS)

    print("All watched codes have been claimed/notified.")


if __name__ == "__main__":
    threading.Thread(target=watch_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
