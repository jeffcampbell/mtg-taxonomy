"""Local card database: Scryfall's oracle bulk file, trimmed, in SQLite.

One row per Oracle card (reprints collapsed). Every face name and the full
"A // B" name are aliases, so either face finds the card.
"""

import gzip
import io
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

from . import api

DEFAULT_DIR = Path(os.environ.get("SCRY_CACHE_DIR") or Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "scry")
STALE_DAYS = 14
CHECK_HOURS = 24
# Sets whose cards never matter for lookups; their counts churn without new playable cards.
IGNORED_SET_TYPES = {"token", "memorabilia", "minigame", "alchemy", "treasure_chest"}

# Layouts that aren't real cards; the bulk file has art-series cards that share real cards' names.
SKIP_LAYOUTS = {"art_series", "vanguard", "planar", "scheme", "augment", "host", "emblem"}
FORMATS = ["standard", "pioneer", "modern", "legacy", "vintage", "commander", "pauper", "brawl", "historic", "timeless", "oathbreaker"]
FACE_KEYS = ["name", "mana_cost", "type_line", "oracle_text", "power", "toughness", "loyalty", "defense"]
CARD_KEYS = FACE_KEYS + ["id", "layout", "color_identity", "keywords", "edhrec_rank", "game_changer", "set", "rarity"]


def norm(name: str) -> str:
    """Lookup key: accents folded, lowercase, punctuation dropped, spaces collapsed."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9/ ]+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def trim(card: dict) -> dict:
    """Keep only what the renderer can print."""
    out = {k: card[k] for k in CARD_KEYS if card.get(k) not in (None, "", [])}
    if card.get("card_faces"):
        out["card_faces"] = [{k: f[k] for k in FACE_KEYS if f.get(k) not in (None, "")} for f in card["card_faces"]]
    legal = card.get("legalities") or {}
    out["legal"] = {f: legal[f] for f in FORMATS if f in legal}
    usd = (card.get("prices") or {}).get("usd") or (card.get("prices") or {}).get("usd_foil")
    if usd:
        out["usd"] = usd
    return out


def aliases(card: dict) -> set[str]:
    names = {card["name"]} | {f["name"] for f in card.get("card_faces", []) if f.get("name")}
    return {norm(n) for n in names if n}


def set_counts() -> dict[str, int]:
    """{set code: card count} for every set that can hold cards a lookup would want."""
    out, url = {}, "/sets"
    while url:
        page = api.get(url)
        out.update({s["code"]: s["card_count"] for s in page["data"] if s.get("set_type") not in IGNORED_SET_TYPES and s.get("card_count")})
        url = page.get("next_page") if page.get("has_more") else None
    return out


class DB:
    def __init__(self, directory: Path = DEFAULT_DIR):
        self.path = Path(directory) / "cards.db"
        self._conn = None

    @property
    def exists(self) -> bool:
        return self.path.exists()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.path)
        return self._conn

    def age_days(self) -> float | None:
        row = self.conn.execute("SELECT v FROM meta WHERE k='synced'").fetchone()
        return (time.time() - float(row[0])) / 86400 if row else None

    def meta(self, k: str) -> str | None:
        row = self.conn.execute("SELECT v FROM meta WHERE k = ?", (k,)).fetchone()
        return row[0] if row else None

    def set_meta(self, k: str, v: str):
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (k, v))
        self.conn.commit()

    def behind(self, force: bool = False) -> list[str] | None:
        """Sets with more cards on Scryfall than at the last sync, e.g. ["mdd +12", "nau (new)"].

        Scryfall's bulk file is regenerated daily for prices, so its timestamp says nothing
        about new cards; per-set card counts do. Asks the API at most every CHECK_HOURS and
        remembers the answer in between. Returns None if never checked."""
        checked = float(self.meta("checked") or 0)
        if force or time.time() - checked > CHECK_HOURS * 3600:
            now = set_counts()
            if self.meta("sets") is None:  # database from before snapshots existed: start from here
                self.set_meta("sets", json.dumps(now))
            then = json.loads(self.meta("sets"))
            changed = [f"{c} +{n - then[c]}" if c in then else f"{c} (new)" for c, n in now.items() if n > then.get(c, 0)]
            self.set_meta("behind", json.dumps(changed))
            self.set_meta("checked", str(time.time()))
        b = self.meta("behind")
        return json.loads(b) if b is not None else None

    def get(self, key: str) -> dict | None:
        row = self.conn.execute(
            "SELECT c.data FROM names n JOIN cards c ON c.id = n.card WHERE n.key = ? ORDER BY n.rank LIMIT 1", (key,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def prefix(self, key: str, limit: int = 5) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT c.name FROM names n JOIN cards c ON c.id = n.card WHERE n.key >= ? AND n.key < ? AND n.rank = 0 LIMIT ?",
            (key, key + "￿", limit),
        ).fetchall()
        return [r[0] for r in rows]

    def keys(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT DISTINCT key FROM names WHERE rank = 0")]

    def sync(self, log=lambda m: print(m, file=sys.stderr)) -> int:
        meta = api.get("/bulk-data/oracle-cards")
        # Scryfall has served both a JSON array (download_uri) and gzipped JSONL (jsonl_download_uri).
        url = meta.get("jsonl_download_uri") or meta.get("download_uri")
        log(f"scry: downloading {meta.get('name', 'oracle cards')} ({(meta.get('compressed_size') or meta.get('size') or 0) / 1e6:.0f} MB)…")
        with api.open_stream(url) as resp:
            body = resp.read()
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        text = body.decode()
        cards = json.loads(text) if text.lstrip().startswith("[") else (json.loads(l) for l in io.StringIO(text) if l.strip())

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.unlink(missing_ok=True)
        conn = sqlite3.connect(tmp)
        conn.executescript("""
            CREATE TABLE cards (id TEXT PRIMARY KEY, name TEXT, data TEXT);
            CREATE TABLE names (key TEXT, card TEXT, rank INTEGER);
            CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
        """)
        n = 0
        for card in cards:
            if card.get("layout") in SKIP_LAYOUTS:
                continue
            t = trim(card)
            # Tokens share names with real cards ("Spirit", "Treasure"): rank real cards first.
            rank = 1 if card.get("layout") in ("token", "double_faced_token") or card.get("set_type") in ("token", "memorabilia", "funny") else 0
            conn.execute("INSERT OR IGNORE INTO cards VALUES (?, ?, ?)", (t["id"], t["name"], json.dumps(t, separators=(",", ":"))))
            conn.executemany("INSERT INTO names VALUES (?, ?, ?)", [(k, t["id"], rank) for k in aliases(t)])
            n += 1
        conn.execute("CREATE INDEX names_key ON names (key, rank)")
        from .themes import data as themes  # late import: themes.data imports db
        themes.download(self.path.parent, log)
        cached = self.path.parent / themes.FILE
        t = themes.load(conn, cached if cached.exists() else None)
        if t.get("matched"):
            log(f"scry: themes from {t.get('date', '?')} for {t['matched']:,} cards")
        now = str(time.time())
        conn.executemany("INSERT INTO meta VALUES (?, ?)", [
            ("synced", now), ("checked", now), ("behind", "[]"), ("sets", json.dumps(set_counts()))])
        conn.commit()
        conn.close()
        if self._conn:
            self._conn.close()
            self._conn = None
        os.replace(tmp, self.path)
        log(f"scry: {n:,} cards → {self.path}")
        return n
