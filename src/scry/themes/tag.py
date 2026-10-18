"""Maintainer tools: ask Jev the theme questions, and export the published theme file.

    scry maintain tag --all --dry-run     # what would be asked, estimated cost
    scry maintain tag --sample 500        # spot-check a random sample
    scry maintain tag --all               # every card not yet answered (~$18 from scratch)
    scry maintain export scry-themes.csv.gz

Answers accumulate in a store (default ~/.cache/scry/themes/tags.json). Each answer
records a hash of the question wording it came from, so editing a question in
questions.py re-asks only that question. Cards needing the same questions go to Jev
together, 1,000 per checkpoint; decide's own cache makes re-running after a failure free.

Needs `decide` (https://github.com/jeffcampbell/Decide) and a TypeSafe API key. Users of
scry never need either: they download the exported file via `scry sync`.
"""

import hashlib
import json
import os
import random
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

from .. import render
from ..db import DEFAULT_DIR, DB
from ..lookup import Lookup
from . import data
from .questions import JEV, THRESHOLD, free_tags

STORE = DEFAULT_DIR / "themes" / "tags.json"
USD_PER_MTOK = 0.42
# Calibrated on billed runs (Oct 2026): ~314 tokens per request (fixed overhead + card
# text) plus question text at ~3.64 characters per token.
EST_BASE, EST_CHARS_PER_TOKEN = 314, 3.64
BATCH = 1000


def import_decide():
    try:
        import decide  # noqa: F401
    except ImportError:
        src = Path(os.environ.get("DECIDE_SRC") or Path.home() / "development" / "decide" / "src")
        if not (src / "decide").exists():
            raise SystemExit("scry: tagging needs decide: pip install git+https://github.com/jeffcampbell/Decide.git (or set DECIDE_SRC)")
        sys.path.insert(0, str(src))
    from decide.cache import Cache
    from decide.config import get_backend
    from decide.engine import Document, Engine
    from decide.questions import noul
    return Cache, get_backend, Document, Engine, noul


def qhash(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:8]


def estimate(n_cards: int, questions) -> int:
    return round(n_cards * (EST_BASE + sum(len(JEV[k]) for k in questions) / EST_CHARS_PER_TOKEN))


def pool(db: DB) -> list[str]:
    """Every real card (tokens and art cards excluded), one name per Oracle card."""
    rows = db.conn.execute("SELECT c.name FROM cards c JOIN names n ON n.card = c.id AND n.rank = 0 GROUP BY c.id ORDER BY c.name")
    return [r[0] for r in rows]


def load_store(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def save_store(path: Path, tags: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(tags, separators=(",", ":"), sort_keys=True))
    os.replace(tmp, path)


def tag(a) -> int:
    db = DB()
    look = Lookup(db, online=False)
    if a.names:
        names = [l.strip() for l in Path(a.names).read_text().splitlines() if l.strip()]
    else:
        names = pool(db)
        if a.sample:
            names = random.Random(a.seed).sample(names, a.sample)

    store = Path(a.store)
    tags = load_store(store)
    hashes = {k: qhash(q) for k, q in JEV.items()}
    groups: dict[tuple, list] = defaultdict(list)
    for n in names:
        card, note = look.find(n)
        if not card or note:
            print(f"skip: {note or n}", file=sys.stderr)
            continue
        entry = tags.setdefault(card["name"], {"jev": {}, "asked": {}})
        entry["free"] = sorted(free_tags(card))
        todo = tuple(k for k in JEV if entry["asked"].get(k) != hashes[k])
        if todo:
            groups[todo].append((card["name"], card))

    n_cards = sum(len(v) for v in groups.values())
    est = sum(estimate(len(v), k) for k, v in groups.items())
    print(f"{len(names)} cards · {n_cards} need questions in {len(groups)} group(s) · est {est:,} tokens ≈ ${est * USD_PER_MTOK / 1e6:.2f}", file=sys.stderr)
    for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:5]:
        print(f"  {len(v):>6} cards × {len(k)} questions" + (f": {', '.join(k)}" if len(k) <= 6 else ""), file=sys.stderr)
    if a.dry_run or not groups:
        if not a.dry_run:
            save_store(store, tags)
        return 0

    Cache, get_backend, Document, Engine, noul = import_decide()
    engine = Engine(get_backend("jev"), Cache())
    billed = errors = done = 0
    start = time.monotonic()
    for todo, items in groups.items():
        questions = {k: noul(JEV[k]) for k in todo}
        for i in range(0, len(items), BATCH):
            batch = items[i:i + BATCH]
            docs = [Document(n, "Magic: The Gathering card.\n" + render.render(c)) for n, c in batch]
            for r in engine.run(docs, questions):
                billed += r.input_tokens
                if r.error:
                    errors += 1
                    print(f"error: {r.label}: {r.error}", file=sys.stderr)
                    continue
                entry = tags[r.label]
                for k in todo:
                    entry["jev"][k] = round(r.answers[k]["noul"], 4)
                    entry["asked"][k] = hashes[k]
            save_store(store, tags)
            done += len(batch)
            rate = done / (time.monotonic() - start)
            print(f"  {done:,}/{n_cards:,} cards · ${billed * USD_PER_MTOK / 1e6:.2f} · {errors} errors · "
                  f"ETA {(n_cards - done) / rate / 60:.0f} min", file=sys.stderr, flush=True)
    print(f"done · {billed:,} tokens billed (${billed * USD_PER_MTOK / 1e6:.3f}) · {errors} errors → {store}", file=sys.stderr)
    return 1 if errors else 0


def export(a) -> int:
    tags = load_store(Path(a.store))
    hashes = {k: qhash(q) for k, q in JEV.items()}
    rows = [(n, {k: p for k, p in e["jev"].items() if k in JEV and e["asked"].get(k) == hashes[k]}) for n, e in sorted(tags.items())]
    complete = sum(len(ps) == len(JEV) for _, ps in rows)
    meta = {"format": 1, "date": date.today().isoformat(), "model": "jev-latest", "threshold": THRESHOLD,
            "cards": len(rows), "complete": complete, "questions": {k: hashes[k] for k in JEV}}
    out = Path(a.out)
    data.write(out, meta, rows)
    print(f"{len(rows):,} cards ({complete:,} with all {len(JEV)} answers) → {out} ({out.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)
    if complete < len(rows):
        print("scry: some cards have stale or missing answers; run `scry maintain tag --all` first", file=sys.stderr)
    return 0


def load(a) -> int:
    """Load a theme file into the card database and keep it as the cached copy for future syncs."""
    db = DB()
    src, cached = Path(a.file), db.path.parent / data.FILE
    if src.resolve() != cached.resolve():
        cached.write_bytes(src.read_bytes())
    info = data.load(db.conn, cached)
    print(f"loaded theme data from {info.get('date', '?')}: {info['matched']:,} cards matched, {info['unmatched']} unmatched", file=sys.stderr)
    return 0
