"""Theme data inside scry's card database.

Published theme data is one gzipped CSV: a "# {json metadata}" line, a header (name plus
one column per Jev question), then one row per card with P(yes) to two decimals. Free
tags aren't shipped: they're computed from card data whenever the data is loaded, so
they also cover cards printed after the theme data was made.

Table: themes(card, tag, p) — Jev answers with p >= STORE_MIN, free tags at p = 1.0
(WEAK card-type tags at the threshold).
"""

import csv
import gzip
import io
import json
import os
import sqlite3
import urllib.error
from pathlib import Path

from .. import api
from .questions import GROUPS, JEV, THRESHOLD, free_tags

URL = os.environ.get("SCRY_THEMES_URL") or "https://github.com/jeffcampbell/mtg-taxonomy/releases/latest/download/scry-themes.csv.gz"
FILE = "scry-themes.csv.gz"
STORE_MIN = 0.3  # keep near-misses so scores can be inspected; "fits" needs THRESHOLD
# Card-type tags that make a card fit a theme without saying it cares about the theme
# (a cheap instant "fits" Spellslinger). Scored at the threshold, so they count as fits
# but rank below cards the model actually confirmed.
WEAK = {"cheap_spell", "is_artifact", "is_enchantment", "is_legendary", "is_historic"}


def read(path: Path) -> tuple[dict, list[tuple[str, dict[str, float]]]]:
    with gzip.open(path, "rt", newline="") as f:
        first = f.readline()
        if not first.startswith("# "):
            raise ValueError(f"{path}: not a scry theme file (no metadata line)")
        meta = json.loads(first[2:])
        reader = csv.reader(f)
        header = next(reader)
        cols = [(i, t) for i, t in enumerate(header[1:], 1) if t in JEV]
        rows = [(r[0], {t: float(r[i]) for i, t in cols if r[i]}) for r in reader if r]
    return meta, rows


def write(path: Path, meta: dict, rows):
    """rows: iterable of (name, {tag: p}). Columns follow JEV's order."""
    buf = io.StringIO()
    buf.write("# " + json.dumps(meta, separators=(",", ":")) + "\n")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["name"] + list(JEV))
    for name, ps in rows:
        w.writerow([name] + [f"{ps[t]:.2f}" if t in ps else "" for t in JEV])
    path.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))


def download(directory: Path, log) -> bool:
    """Fetch the latest published theme file into directory. Keeps any cached copy on failure."""
    target = Path(directory) / FILE
    try:
        with api.open_stream(URL) as resp:
            body = resp.read()
        if gzip.decompress(body)[:2] != b"# ":
            raise ValueError("unexpected content")
    except (urllib.error.URLError, OSError, ValueError) as e:
        have = "using the cached copy" if target.exists() else "free tags only"
        log(f"scry: theme data not downloaded ({getattr(e, 'reason', e)}); {have}")
        return False
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(body)
    os.replace(tmp, target)
    return True


def load(conn: sqlite3.Connection, path: Path | None) -> dict:
    """(Re)build the themes table from a theme file (or free tags only if path is None)."""
    from ..db import norm  # late import: db imports this module during sync

    conn.executescript("""
        DROP TABLE IF EXISTS themes;
        CREATE TABLE themes (card TEXT, tag TEXT, p REAL);
    """)
    real = conn.execute("SELECT c.id, c.data FROM cards c WHERE EXISTS (SELECT 1 FROM names n WHERE n.card = c.id AND n.rank = 0)").fetchall()
    conn.executemany("INSERT INTO themes VALUES (?, ?, ?)",
                     [(cid, t, THRESHOLD if t in WEAK else 1.0) for cid, data in real for t in free_tags(json.loads(data))])
    meta, matched, unmatched = {}, 0, 0
    if path and Path(path).exists():
        meta, rows = read(Path(path))
        ids: dict[str, set[str]] = {}
        for key, cid in conn.execute("SELECT key, card FROM names WHERE rank = 0"):
            ids.setdefault(key, set()).add(cid)  # a few distinct cards share a name: tag them all
        batch = []
        for name, ps in rows:
            cids = ids.get(norm(name))
            if not cids:
                unmatched += 1
                continue
            matched += 1
            batch += [(cid, t, p) for cid in cids for t, p in ps.items() if p >= STORE_MIN]
        conn.executemany("INSERT INTO themes VALUES (?, ?, ?)", batch)
    conn.execute("CREATE INDEX themes_tag ON themes (tag, p)")
    conn.execute("CREATE INDEX themes_card ON themes (card)")
    info = {**meta, "matched": matched, "unmatched": unmatched, "cards": len(real)}
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('themes', ?)", (json.dumps(info),))
    conn.commit()
    return info


def info(conn) -> dict | None:
    row = conn.execute("SELECT v FROM meta WHERE k = 'themes'").fetchone()
    return json.loads(row[0]) if row else None


def card_tags(conn, card_id: str) -> dict[str, float]:
    try:
        return dict(conn.execute("SELECT tag, p FROM themes WHERE card = ?", (card_id,)).fetchall())
    except sqlite3.OperationalError:  # database from before themes existed
        return {}


def fits(tags: dict[str, float]) -> tuple[list[str], list[str]]:
    """(theme slugs, role slugs) the card fits, given its {tag: p}."""
    themes, roles = [], []
    for s, (_, group, kind) in GROUPS.items():
        if max((tags.get(t, 0) for t in group), default=0) >= THRESHOLD:
            (themes if kind == "theme" else roles).append(s)
    return themes, roles


def scores(conn, slug: str) -> dict[str, float]:
    """{card id: score} for every card fitting a group; score = best P(yes) over its tags."""
    _, group, _ = GROUPS[slug]
    q = f"SELECT card, MAX(p) FROM themes WHERE tag IN ({','.join('?' * len(group))}) GROUP BY card HAVING MAX(p) >= ?"
    return dict(conn.execute(q, (*group, THRESHOLD)).fetchall())


def counts(conn) -> dict[str, int]:
    return {s: len(scores(conn, s)) for s in GROUPS}
