"""scry: Magic card lookups for AI agents, in as few tokens as possible."""

import argparse
import json
import re
import signal
import sys

from collections import Counter

from . import api, db as dbm, deck as deckm, render
from .lookup import Lookup
from .themes import data as tdata
from .themes.questions import GROUPS, slug

EPILOG = """\
output: "Name · cost · type · P/T" then rules text. cost 2WW = {2}{W}{W}; ~ = this card;
reminder text dropped (--raw keeps it). "// " starts another face. "# " lines are notes,
"? " lines are misses (exit 1). Card data is local (synced from Scryfall bulk data);
search and rulings call the API. Themes are a model's judgment from rules text (see README).
fields (-f, comma list or "all"): """ + ",".join(render.FIELDS)


def fields_arg(s: str) -> list[str]:
    fs = render.FIELDS if s == "all" else [f.strip() for f in s.split(",") if f.strip()]
    bad = [f for f in fs if f not in render.FIELDS]
    if bad:
        raise argparse.ArgumentTypeError(f"unknown field {','.join(bad)}; choose from {','.join(render.FIELDS)}")
    return fs


def main(argv=None) -> int:
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # `scry … | head` exits quietly
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-f", "--fields", type=fields_arg, default=[], help="extra fields: " + ",".join(render.FIELDS) + " or all")
    common.add_argument("-s", "--short", action="store_true", help="header line only, no rules text")
    common.add_argument("--raw", action="store_true", help="keep reminder text and the card's own name")

    p = argparse.ArgumentParser(prog="scry", description=__doc__, epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--offline", action="store_true", help="never call the API")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<command>")
    c = sub.add_parser("card", parents=[common], help="look up cards by name (args, or stdin one per line)")
    c.add_argument("names", nargs="*")
    s = sub.add_parser("search", parents=[common], help="Scryfall search syntax, e.g. 'id<=wb o:\"gain life\" t:creature'")
    s.add_argument("query", nargs="+")
    s.add_argument("-n", "--limit", type=int, default=20, help="max results (default 20; 0 = count only)")
    s.add_argument("-t", "--text", action="store_true", help="include rules text (default: header lines only)")
    s.add_argument("-o", "--order", default="edhrec", help="name, edhrec (default), cmc, usd, released, …")
    d = sub.add_parser("deck", parents=[common], help="every card in a deck: Archidekt URL, list file, or - for stdin")
    d.add_argument("source")
    d.add_argument("--all", action="store_true", help="include sideboard and maybeboard")
    d.add_argument("--themes", action="store_true", help="only a summary: how many cards fit each theme and role")
    t = sub.add_parser("themes", parents=[common], help="list themes, or top cards for themes: scry themes aristocrats --ci wb")
    t.add_argument("names", nargs="*", help="theme or role names (several = cards fitting all)")
    t.add_argument("--ci", help="color identity limit, e.g. wb (C = colorless)")
    t.add_argument("-n", "--limit", type=int, default=20, help="max cards (default 20; 0 = count only)")
    t.add_argument("-t", "--text", action="store_true", help="include rules text")
    r = sub.add_parser("rulings", help="official rulings for cards")
    r.add_argument("names", nargs="+")
    r.add_argument("-g", "--grep", help="only rulings matching this regex (case-insensitive)")
    r.add_argument("-n", "--limit", type=int, default=0, help="max rulings per card")
    y = sub.add_parser("sync", help="re-download the card database (~25 MB)")
    y.add_argument("--check", action="store_true", help="only report whether Scryfall has new cards (exit 1 if so)")
    y.add_argument("--if-needed", action="store_true", help="sync only if Scryfall has new cards or data is >14 days old (for cron)")
    m = sub.add_parser("maintain", help="maintainer tools: tag cards with Jev, export or load theme data")
    msub = m.add_subparsers(dest="action", required=True, metavar="<action>")
    mt = msub.add_parser("tag", help="ask the theme questions (needs decide + a TypeSafe key)")
    which = mt.add_mutually_exclusive_group(required=True)
    which.add_argument("--names", help="file with one card name per line")
    which.add_argument("--sample", type=int, help="random sample of N cards")
    which.add_argument("--all", action="store_true", help="every card")
    mt.add_argument("--seed", type=int, default=1)
    mt.add_argument("--dry-run", action="store_true", help="show what would be asked and the cost; send nothing")
    me = msub.add_parser("export", help="write the publishable theme file")
    me.add_argument("out")
    for x in (mt, me):
        x.add_argument("--store", default=None, help="answer store (default ~/.cache/scry/themes/tags.json)")
    ml = msub.add_parser("load", help="load a theme file into the card database")
    ml.add_argument("file")
    a = p.parse_args(argv)

    db = dbm.DB()
    try:
        if a.cmd == "sync" and db.exists and (a.check or a.if_needed):
            return cmd_sync_check(a, db)
        if a.cmd == "sync" or not db.exists:
            if a.offline and not db.exists:
                print("scry: no card database yet; run `scry sync` online", file=sys.stderr)
                return 2
            db.sync()
            if a.cmd == "sync":
                return 0
        warn_stale(db, online=not a.offline)
        look = Lookup(db, online=not a.offline)
        cmds = {"card": cmd_card, "search": cmd_search, "deck": cmd_deck, "rulings": cmd_rulings, "themes": cmd_themes, "maintain": cmd_maintain}
        return cmds[a.cmd](a, look)
    except api.ApiError as e:
        print(f"scry: {e}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0


def warn_stale(db, online: bool):
    """One stderr line when the local data is behind. Never fails a command."""
    try:
        behind = db.behind() if online else json.loads(db.meta("behind") or "[]")
    except api.ApiError:
        behind = None  # offline or rate-limited: check again next time
    if behind:
        more = f" +{len(behind) - 5} more sets" if len(behind) > 5 else ""
        print(f"scry: Scryfall has cards newer than your data ({', '.join(behind[:5])}{more}); "
              "run `scry sync` (names still resolve online meanwhile)", file=sys.stderr)
    elif (db.age_days() or 0) > dbm.STALE_DAYS:
        print(f"scry: card data is {db.age_days():.0f} days old (oracle errata, prices); `scry sync` to refresh", file=sys.stderr)


def cmd_sync_check(a, db) -> int:
    behind = db.behind(force=True)
    old = (db.age_days() or 0) > dbm.STALE_DAYS
    if a.check:
        print(f"behind: {', '.join(behind)}" if behind else f"up to date (synced {db.age_days():.1f} days ago)")
        return 1 if behind else 0
    if behind or old:
        db.sync()
    else:
        print("scry: up to date", file=sys.stderr)
    return 0


def annotate(look, card: dict, a) -> dict:
    """Attach the card's themes and roles when -f themes asked for them."""
    if "themes" in getattr(a, "fields", ()) and card.get("id"):
        card["_fits"] = tdata.fits(tdata.card_tags(look.db.conn, card["id"]))
    return card


def blocks(look, names, a, missed, qtys=None):
    """Render each name as one block: card, preceded by a "# " note if the match was inexact;
    or a "? " line if not found (and recorded in missed)."""
    for n in names:
        card, note = look.find(n)
        if not card:
            missed.append(n)
            yield note
            continue
        text = render.render(annotate(look, card, a), a.fields, a.short, a.raw, qty=(qtys or {}).get(n, 1))
        yield f"# {note}\n{text}" if note else text


def emit(lines, short: bool):
    """Print blocks as they come; full blocks get a blank line between them."""
    for i, b in enumerate(lines):
        print(("" if short or not i else "\n") + b, flush=True)


def cmd_card(a, look) -> int:
    names = a.names or [n for _, n, _ in deckm.parse_text(sys.stdin.read())]
    missed = []
    emit(blocks(look, dict.fromkeys(names), a, missed), a.short)  # dedupe, keep order
    return 1 if missed else 0


def cmd_search(a, look) -> int:
    if a.offline:
        print("scry: search needs the API", file=sys.stderr)
        return 2
    q = " ".join(a.query)
    try:
        page = api.get("/cards/search", {"q": q, "unique": "cards", "order": a.order})
    except api.ApiError as e:
        if e.status == 404:
            print("# 0 cards")
            return 0
        raise
    total, cards = page.get("total_cards", 0), []
    while a.limit > 0:
        cards += page["data"]
        if len(cards) >= a.limit or not page.get("has_more"):
            break
        page = api.get(page["next_page"])
    cards = cards[: a.limit]
    print(f"# {total} cards" + (f", top {len(cards)} by {a.order}" if 0 < len(cards) < total else ""))
    for w in page.get("warnings", []):
        print(f"# warning: {w}")
    if cards:
        short = a.short or not a.text
        emit([render.render(annotate(look, dbm.trim(c), a), a.fields, short, a.raw) for c in cards], short)
    return 0


def cmd_deck(a, look) -> int:
    title, entries = deckm.load(a.source, sys.stdin.read)
    order = ["commander", "companion", "main"] + (["side", "maybe"] if a.all else [])
    groups: dict[str, dict[str, int]] = {s: {} for s in order}
    for qty, name, section in entries:
        if section in groups:
            groups[section][name] = groups[section].get(name, 0) + qty
    count = sum(sum(g.values()) for s, g in groups.items() if s not in deckm.EXCLUDED)
    print(f"# {title} · {count} cards")
    if a.themes:
        return deck_themes(look, {n for sec, g in groups.items() if sec not in deckm.EXCLUDED for n in g})
    missed = []
    for section in order:
        if not groups[section]:
            continue
        print(f"## {section}")
        emit(blocks(look, groups[section], a, missed, groups[section]), a.short)
    return 1 if missed else 0


def deck_themes(look, names) -> int:
    """Two summary lines: unique cards per theme (top 12) and per role. Copies don't count twice."""
    themes, roles, missed = Counter(), Counter(), []
    for n in names:
        card, _ = look.find(n)
        if not card:
            missed.append(n)
            continue
        t, r = tdata.fits(tdata.card_tags(look.db.conn, card["id"]))
        themes.update(t)
        roles.update(r)
    print("# themes: " + " · ".join(f"{s} {k}" for s, k in themes.most_common(12)))
    print("# roles: " + " · ".join(f"{s} {roles[s]}" for s, (_, _, kind) in GROUPS.items() if kind == "role"))
    for n in missed:
        print(f'? "{n}": no match')
    return 1 if missed else 0


def cmd_themes(a, look) -> int:
    conn = look.db.conn
    meta = tdata.info(conn) or {}
    if not meta.get("matched"):
        print("# no published theme data loaded: free tags only (`scry sync`, or `scry maintain load FILE`)")
    if not a.names:
        if meta.get("matched"):
            print(f"# themes from {meta.get('date', '?')} ({meta.get('model', '?')}) · {meta['matched']:,} cards · model judgments, see README")
        counts = tdata.counts(conn)
        for kind in ("theme", "role"):
            print(f"## {kind}s")
            for s in sorted((s for s, g in GROUPS.items() if g[2] == kind), key=lambda s: -counts[s]):
                print(f"{s} {counts[s]:,}")
        return 0
    slugs = [slug(n) for n in a.names]
    for n, s in zip(a.names, slugs):
        if s not in GROUPS:
            import difflib
            near = difflib.get_close_matches(s, GROUPS, n=3, cutoff=0.5)
            print(f'? "{n}": no such theme' + (f" (maybe: {' | '.join(near)})" if near else "") + "; `scry themes` lists them")
            return 2
    best = None
    for s in slugs:  # several themes: cards fitting all, scored by their weakest fit
        sc = tdata.scores(conn, s)
        best = sc if best is None else {c: min(p, sc[c]) for c, p in best.items() if c in sc}
    cards = []
    ids = list(best)
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        cards += [json.loads(d) for (d,) in conn.execute(f"SELECT data FROM cards WHERE id IN ({','.join('?' * len(chunk))})", chunk)]
    if a.ci:
        allowed = set(a.ci.upper()) - {"C"}
        cards = [c for c in cards if set(c.get("color_identity", [])) <= allowed]
    cards.sort(key=lambda c: (-round(best[c["id"]], 2), c.get("edhrec_rank") or 10**9, c["name"]))
    label = " + ".join(GROUPS[s][0] for s in slugs)
    shown = cards[: a.limit]
    print(f"# {label}: {len(cards):,} cards" + (f" in {a.ci.upper()}" if a.ci else "") +
          (f", top {len(shown)} by score then popularity" if 0 < len(shown) < len(cards) else ""))
    short = a.short or not a.text
    emit((f"{best[c['id']]:.2f} " + render.render(annotate(look, c, a), a.fields, short, a.raw) for c in shown), short)
    return 0


def cmd_maintain(a, look) -> int:
    from .themes import tag as tagm
    if getattr(a, "store", None) is None:
        a.store = tagm.STORE
    return {"tag": tagm.tag, "export": tagm.export, "load": tagm.load}[a.action](a)


def cmd_rulings(a, look) -> int:
    if a.offline:
        print("scry: rulings need the API", file=sys.stderr)
        return 2
    missed = []
    for n in dict.fromkeys(a.names):
        card, note = look.find(n)
        if note:
            print(note if note.startswith("?") else "# " + note)
        if not card:
            missed.append(n)
            continue
        rulings = list(dict.fromkeys(r["comment"] for r in api.get(f"/cards/{card['id']}/rulings")["data"]))
        total = len(rulings)
        if a.grep:
            rulings = [r for r in rulings if re.search(a.grep, r, re.I)]
        if a.limit:
            rulings = rulings[: a.limit]
        shown = f"{len(rulings)} of {total}" if len(rulings) < total else str(total or "no")
        print(f"{card['name']}: {shown} rulings")
        for text in rulings:
            text = re.sub(r"\s*For more information,? (please )?see https?://\S+", "", text)
            print("- " + render.selfname(text, card))
    return 1 if missed else 0
