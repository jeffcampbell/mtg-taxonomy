"""Deck sources → (title, [(qty, name, section)]).

Accepts an Archidekt URL, or a text list in any of the common export shapes:
"1 Sol Ring", "1x Sol Ring (CMR) 263 *F*", "Sol Ring", with optional section
headers ("Commander", "Sideboard:", "// Maybeboard").
"""

import re

from . import api

LINE = re.compile(
    r"^(?:(?P<qty>\d+)\s*x?\s+)?(?P<name>.+?)"
    r"(?:\s+\([A-Za-z0-9]{2,6}\)(?:\s+[\w-]+)?)?"  # (SET) 123
    r"(?:\s+\*[A-Z]+\*)*(?:\s+\[[^\]]*\])*(?:\s+\^[^^]*\^)*\s*$"  # *F*, [Category], ^tag^
)
SECTIONS = {
    "commander": "commander", "commanders": "commander", "companion": "companion",
    "deck": "main", "main": "main", "mainboard": "main", "main deck": "main",
    "sideboard": "side", "side": "side", "maybeboard": "maybe", "maybe": "maybe", "considering": "maybe",
}
EXCLUDED = {"companion", "side", "maybe"}  # not counted toward deck size


def parse_text(text: str) -> list[tuple[int, str, str]]:
    out, section = [], "main"
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head = line.lstrip("/ ").rstrip(":").strip().lower()
        if head in SECTIONS:
            section = SECTIONS[head]
            continue
        if line.startswith("//"):
            continue
        m = LINE.match(line)
        if m:
            out.append((int(m["qty"] or 1), m["name"].strip(), section))
    return out


def archidekt(deck_id: str) -> tuple[str, list[tuple[int, str, str]]]:
    d = api.get(f"https://archidekt.com/api/decks/{deck_id}/")
    cats = {c["name"]: c for c in d.get("categories", [])}
    out = []
    for c in d["cards"]:
        names = c.get("categories") or []
        oracle = c["card"]["oracleCard"]
        if "Commander" in names or any(cats.get(n, {}).get("isPremier") for n in names):
            section = "commander"
        elif any(not cats.get(n, {}).get("includedInDeck", True) for n in names):
            section = "maybe"  # Archidekt: one excluded category (Maybeboard) excludes the card
        elif "Sideboard" in names:
            section = "companion" if "Companion —" in (oracle.get("text") or "") else "side"
        else:
            section = "main"
        out.append((c.get("quantity", 1), oracle["name"], section))
    return d.get("name", f"archidekt {deck_id}"), out


def load(source: str, read_stdin) -> tuple[str, list[tuple[int, str, str]]]:
    m = re.search(r"archidekt\.com/(?:api/)?decks/(\d+)", source)
    if m:
        return archidekt(m.group(1))
    if "moxfield.com" in source:
        raise SystemExit("scry: Moxfield blocks scripted access; export the deck as text and pipe it in: scry deck - < list.txt")
    if source == "-":
        return "stdin", parse_text(read_stdin())
    with open(source) as f:
        return source, parse_text(f.read())
