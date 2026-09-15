"""
Discord Vanity URL Availability Watcher (Render-ready version, authenticated)
-------------------------------------------------------------------------------
Runs a tiny web server (so Render's free tier will host it) while a
background thread keeps polling Discord's invite-resolve endpoint for
one or more vanity codes.

- Uses an authenticated Discord bot token to avoid shared-IP rate limits.
- Checks every CHECK_INTERVAL_SECONDS (default: 5 min).
- Sends a STATUS UPDATE to the webhook every STATUS_UPDATE_EVERY_N_CHECKS
  checks (default: every 12th check = hourly), with no ping.
- Sends a SEPARATE @everyone-pinging message immediately the moment a
  code actually becomes available.
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

# The bot token is read from a Render environment variable named
# DISCORD_BOT_TOKEN, never hardcoded here. Set it in Render's dashboard
# under Settings -> Environment.
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")

INVITE_API = "https://discord.com/api/v10/invites/{code}"
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "application/json",
}
if BOT_TOKEN:
    REQUEST_HEADERS["Authorization"] = f"Bot {BOT_TOKEN}"

app = Flask(__name__)
status = {
    "last_check": None,
    "remaining": list(VANITY_CODES),
    "checks_done": 0,
    "authenticated": bool(BOT_TOKEN),
}


@app.route("/")
def home():
    return {
        "status": "running",
        "watching": status["remaining"],
        "last_check": status["last_check"],
        "checks_done": status["checks_done"],
        "status_update_every_n_checks": STATUS_UPDATE_EVERY_N_CHECKS,
        "authenticated": status["authenticated"],
    }


def is_available(code: str):
    resp = requests.get(
        INVITE_API.format(code=code), headers=REQUEST_HEADERS, timeout=10
    )
    if resp.status_code == 200:
        return False
    if resp.status_code == 404:
        return True
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "unknown")
        print(f"[{code}] Rate limited (429). Retry-After: {retry_after}", flush=True)
        return None
    print(
        f"[{code}] Unexpected status {resp.status_code}: {resp.text[:300]}",
        flush=True,
    )
    return None


def send_status_update(results: dict):
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
        "allowed_mentions": {"parse": []},
    }
    r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
    r.raise_for_status()


def send_availability_ping(code: str):
    payload = {
        "content": f"@everyone 🎉 The vanity URL **discord.gg/{code}** is now available!",
        "allowed_mentions": {"parse": ["everyone"]},
    }
    r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
    r.raise_for_status()


def watch_loop():
    if not BOT_TOKEN:
        print(
            "WARNING: DISCORD_BOT_TOKEN not set. Requests will be unauthenticated "
            "and may hit shared-IP rate limits on Render.",
            flush=True,
        )

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
                    print(f"[{code}] Available! Sending @everyone ping...", flush=True)
                    send_availability_ping(code)
                    remaining.discard(code)
                elif result is False:
                    print(f"[{code}] Still taken.", flush=True)
            except requests.RequestException as e:
                print(f"[{code}] Request error: {e}", flush=True)
                results[code] = None

        checks_done += 1
        status["checks_done"] = checks_done
        status["remaining"] = list(remaining)

        if checks_done % STATUS_UPDATE_EVERY_N_CHECKS == 0:
            try:
                send_status_update(results)
            except requests.RequestException as e:
                print(f"Failed to send status update: {e}", flush=True)

        if remaining:
            time.sleep(CHECK_INTERVAL_SECONDS)

    print("All watched codes have been claimed/notified.", flush=True)


if __name__ == "__main__":
    threading.Thread(target=watch_loop, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
