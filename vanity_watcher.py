"""
Discord Vanity URL Availability Watcher (fingerprint-evading version)
-------------------------------------------------------------------------------
Runs a tiny web server (so free hosts like Northflank/Render will host it)
while a background thread keeps polling Discord's invite-resolve endpoint
for one or more vanity codes.

Key fix: uses curl_cffi (which impersonates a real Chrome browser's TLS/HTTP
fingerprint) instead of plain `requests` for calls to discord.com. Cloudflare
was blocking us based on the recognizable "bot-like" fingerprint of Python's
requests library, regardless of IP address or proxy.

- Uses an authenticated Discord bot token.
- Optionally routes through a residential proxy (PROXY_URL env var).
- Checks every CHECK_INTERVAL_SECONDS (default: 5 min).
- Sends a STATUS UPDATE to the webhook every STATUS_UPDATE_EVERY_N_CHECKS
  checks (default: every 12th check = hourly), with no ping.
- Sends a SEPARATE @everyone-pinging message immediately the moment a
  code actually becomes available.
"""

import os
import time
import threading
from curl_cffi import requests as cf_requests
import requests  # still used for the plain webhook POSTs, which aren't blocked
from flask import Flask

# --- Config ---
VANITY_CODES = ["stealanegg", "sae"]
WEBHOOK_URL = "https://discord.com/api/webhooks/1549272234005237870/pyDj7Uyca3X36Ayt-BoNx9Humtfxt-l-QODqEop6Uq9LSM6xV3DIRGHoMwO7-u2zi7xC"
CHECK_INTERVAL_SECONDS = 60 * 5  # 5 minutes between checks
STATUS_UPDATE_EVERY_N_CHECKS = 12  # 12 checks * 5 min = status update every hour

BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")

# Optional residential proxy, format: http://user:pass@gw.dataimpulse.com:823
PROXY_URL = os.environ.get("PROXY_URL", "")
PROXIES = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None

INVITE_API = "https://discord.com/api/v10/invites/{code}"
GATEWAY_API = "https://discord.com/api/v10/gateway"

REQUEST_HEADERS = {"Accept": "application/json"}
if BOT_TOKEN:
    REQUEST_HEADERS["Authorization"] = f"Bot {BOT_TOKEN}"

app = Flask(__name__)
status = {
    "last_check": None,
    "remaining": list(VANITY_CODES),
    "checks_done": 0,
    "authenticated": bool(BOT_TOKEN),
    "proxy_enabled": bool(PROXY_URL),
}


def cf_get(url):
    """GET request impersonating a real Chrome browser's fingerprint."""
    kwargs = {"headers": REQUEST_HEADERS, "timeout": 15, "impersonate": "chrome124"}
    if PROXIES:
        kwargs["proxies"] = PROXIES
    return cf_requests.get(url, **kwargs)


@app.route("/")
def home():
    return {
        "status": "running",
        "watching": status["remaining"],
        "last_check": status["last_check"],
        "checks_done": status["checks_done"],
        "status_update_every_n_checks": STATUS_UPDATE_EVERY_N_CHECKS,
        "authenticated": status["authenticated"],
        "proxy_enabled": status["proxy_enabled"],
    }


@app.route("/test-gateway")
def test_gateway():
    """Diagnostic: hit a public Discord endpoint using the impersonated
    Chrome fingerprint, to check if this fixes the 403/40333 block."""
    try:
        resp = cf_get(GATEWAY_API)
        return {
            "endpoint": GATEWAY_API,
            "status_code": resp.status_code,
            "body": resp.text[:500],
            "via_proxy": bool(PROXY_URL),
            "method": "curl_cffi (chrome124 impersonation)",
        }
    except Exception as e:
        return {"error": str(e)}


def is_available(code: str):
    resp = cf_get(INVITE_API.format(code=code))
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
    r = requests.post(WEBHOOK_URL, json=payload, proxies=PROXIES, timeout=15)
    r.raise_for_status()


def send_availability_ping(code: str):
    payload = {
        "content": f"@everyone 🎉 The vanity URL **discord.gg/{code}** is now available!",
        "allowed_mentions": {"parse": ["everyone"]},
    }
    r = requests.post(WEBHOOK_URL, json=payload, proxies=PROXIES, timeout=15)
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
                    print(f"[{code}] Available! Sending @everyone ping...", flush=True)
                    send_availability_ping(code)
                    remaining.discard(code)
                elif result is False:
                    print(f"[{code}] Still taken.", flush=True)
            except Exception as e:
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
