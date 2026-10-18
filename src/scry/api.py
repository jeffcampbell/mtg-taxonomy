"""Scryfall HTTP: required headers, polite rate limiting, compact errors."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.scryfall.com"
HEADERS = {"User-Agent": "scry/0.1 (+https://github.com/jeffcampbell/mtg-taxonomy)", "Accept": "application/json"}
# Scryfall's limits: 2 req/s for these endpoints, 10 req/s for the rest. A 429 means
# back off; repeated violations get the client blocked.
SLOW = ("/cards/search", "/cards/named", "/cards/random", "/cards/collection")
COOLDOWN_S = 120
_last = 0.0


def _cooldown_file():
    from .db import DEFAULT_DIR  # late import: db imports api
    return DEFAULT_DIR / "cooldown"


class ApiError(Exception):
    def __init__(self, status: int, details: str):
        super().__init__(details)
        self.status = status


def get(url: str, params: dict | None = None, raw: bool = False):
    """GET a Scryfall URL (absolute or a path). Returns parsed JSON, or bytes if raw."""
    global _last
    if not url.startswith("http"):
        url = BASE + url
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    # After a 429 every scry process stays off the API for a while: retrying is what gets clients blocked.
    cool = _cooldown_file()
    try:
        left = float(cool.read_text()) - time.time()
        if left > 0:
            raise ApiError(429, f"Scryfall rate-limited us; API paused {left:.0f} s more (local data still works)")
    except (OSError, ValueError):
        pass
    wait = (0.5 if any(p in url for p in SLOW) else 0.1) - (time.monotonic() - _last)
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()
    try:
        return _fetch(url, raw)
    except ApiError as e:
        if e.status == 429:
            cool.parent.mkdir(parents=True, exist_ok=True)
            cool.write_text(str(time.time() + COOLDOWN_S))
            e.args = (f"Scryfall rate-limited us; API paused {COOLDOWN_S} s (local data still works)",)
        raise


def _fetch(url: str, raw: bool):
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        try:
            details = json.loads(e.read()).get("details", e.reason)
        except Exception:
            details = str(e.reason)
        raise ApiError(e.code, details) from None
    except urllib.error.URLError as e:
        raise ApiError(0, f"network: {e.reason}") from None
    return body if raw else json.loads(body)


def open_stream(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    return urllib.request.urlopen(req, timeout=300)
