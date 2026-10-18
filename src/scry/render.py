"""Cards → compact text.

    Blood Artist · 1B · Creature — Vampire · 0/1
    Whenever this creature or another creature dies, target player loses 1 life and you gain 1 life.

Header fields are separated by " · ". Mana costs drop braces for plain symbols
({2}{W}{W} → 2WW) and keep them for hybrid/Phyrexian ({W/B}). Rules text keeps
Scryfall's symbols as-is, minus reminder text, with the card's own name as "~".
Multi-face cards get one header per face; later faces start with "// ".
"""

import re

REMINDER = re.compile(r"\s*\([^()]*\)")
FIELDS = ["ci", "price", "rank", "gc", "kw", "legal", "set", "rarity", "themes"]


def cost(c: str | None) -> str:
    if not c:
        return ""
    return "".join(s if len(s) == 1 or s.isdigit() else "{" + s + "}" for s in re.findall(r"\{([^}]*)\}", c))


def stats(f: dict) -> str:
    if f.get("power") is not None and f.get("toughness") is not None:
        return f"{f['power']}/{f['toughness']}"
    if f.get("loyalty"):
        return f"loyalty {f['loyalty']}"
    if f.get("defense"):
        return f"defense {f['defense']}"
    return ""


def header(f: dict) -> str:
    return " · ".join(p for p in (f["name"], cost(f.get("mana_cost")), f.get("type_line", ""), stats(f)) if p)


def text(f: dict, raw: bool = False) -> str:
    t = f.get("oracle_text") or ""
    if raw:
        return t
    t = REMINDER.sub("", t)
    t = selfname(t, f)
    return "\n".join(line.strip() for line in t.splitlines() if line.strip())


def selfname(t: str, f: dict) -> str:
    """Replace the card's own name with ~. Legendary "Name, Epithet" cards use just "Name"."""
    names = [f["name"]]
    if "Legendary" in f.get("type_line", "") and ", " in f["name"]:
        names.append(f["name"].split(", ")[0])
    for n in names:
        t = re.sub(rf"(?<![\w'-]){re.escape(n)}(?![\w-])", "~", t)
    return t


def extras(card: dict, fields: list[str]) -> str:
    out = []
    for k in fields:
        if k == "ci":
            out.append("ci:" + ("".join(card.get("color_identity", [])) or "C"))
        elif k == "price" and card.get("usd"):
            out.append(f"${card['usd']}")
        elif k == "rank" and card.get("edhrec_rank"):
            out.append(f"edhrec:{card['edhrec_rank']}")
        elif k == "gc" and card.get("game_changer"):
            out.append("game-changer")
        elif k == "kw" and card.get("keywords"):
            out.append("kw:" + ",".join(card["keywords"]))
        elif k == "legal":
            leg = card.get("legal", {})
            out.append("legal:" + (",".join(f for f, s in leg.items() if s == "legal") or "none"))
            banned = [f for f, s in leg.items() if s in ("banned", "restricted")]
            if banned:
                out.append("banned:" + ",".join(f + ("(r)" if leg[f] == "restricted" else "") for f in banned))
        elif k in ("set", "rarity") and card.get(k):
            out.append(f"{k}:{card[k]}")
        elif k == "themes" and card.get("_fits"):
            themes, roles = card["_fits"]
            if themes:
                out.append("themes:" + ",".join(themes))
            if roles:
                out.append("roles:" + ",".join(roles))
    return " ".join(out)


def render(card: dict, fields: list[str] = (), short: bool = False, raw: bool = False, qty: int = 1) -> str:
    fs = card.get("card_faces") or [card]
    prefix = f"{qty}x " if qty > 1 else ""
    ex = extras(card, list(fields))
    if short:
        line = prefix + " // ".join(header(f) for f in fs)
        return line + (" · " + ex if ex else "")
    lines = []
    for i, f in enumerate(fs):
        lines.append(("// " if i else prefix) + header(f))
        if i == 0 and ex:
            lines.append(ex)
        body = text(f, raw)
        if body:
            lines.append(body)
    return "\n".join(lines)
