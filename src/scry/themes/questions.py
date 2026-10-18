"""The theme set: what scry asks about every card, and how answers become themes.

JEV:    40 yes/no questions answered by a decision model reading the card's rules text.
free_tags(): 23 tags read straight from card data (type line, keywords, cost, regex).
THEMES: theme -> tags; a card fits a theme if any of its tags applies.
ROLES:  staple roles (removal, wipes, …) treated like themes.

Editing a question's wording invalidates only that question's answers (see tag.py).
"""
import re

JEV = {
    # Tokens / counters (enabler + payoff)
    "creature_tokens": "Does this card create creature tokens?",
    "token_payoff": "Does this card reward you for creating tokens or creatures entering, or multiply the tokens you create?",
    "plus_counters": "Does this card put +1/+1 counters on creatures?",
    "counters_payoff": "Does this card reward you for having counters on permanents, or add extra counters when counters are placed?",
    # Artifacts / spells
    "artifact_payoff": "Does this card reward you for casting, controlling, or sacrificing artifacts?",
    "mana_rock": "Is this a non-land artifact that produces mana?",
    "spellslinger": "Does this card reward you for casting instant or sorcery spells?",
    # Graveyard
    "reanimation": "Does this card return creature cards from a graveyard to the battlefield?",
    "recursion": "Does this card return cards from your graveyard to your hand or let you play them from your graveyard?",
    "self_mill": "Does this card put cards from your library into your graveyard?",
    # Life / sacrifice
    "lifegain": "Does this card cause you to gain life?",
    "lifegain_payoff": "Does this card reward you for gaining life (triggers or bonuses when you gain life)?",
    "sac_outlet": "Does this card let you sacrifice creatures or other permanents as a cost or effect you control?",
    "death_trigger": "Does this card trigger when creatures die or are put into a graveyard?",
    "drain": "Does this card make opponents lose life without dealing combat damage?",
    "burn": "Does this card deal noncombat damage to creatures, players, or planeswalkers?",
    # Mana / lands
    "land_ramp": "Does this card search for land cards and put them onto the battlefield, put lands onto the battlefield from your hand, let you play additional lands, or add mana when lands enter?",
    "mana_dork": "Is this a creature that can tap to add mana?",
    "cost_reduction": "Does this card make your spells or abilities cost less mana?",
    "land_payoff": "Does this card reward you when lands enter the battlefield under your control or for playing lands, or let you play lands from your graveyard or the top of your library? (Being a land yourself does not count.)",
    # Permanent types as themes
    "voltron_payoff": "Does this card reward attaching Equipment or Auras, or make a single creature much stronger or harder to remove?",
    "enchantment_payoff": "Does this card reward you for casting or controlling enchantments?",
    "legends_payoff": "Does this card reward you for casting or controlling legendary or historic permanents or spells?",
    # Blink / copies
    "blink": "Does this card exile a permanent and return it to the battlefield (blink or flicker)?",
    "etb_value": "Does this card copy, double, or repeat enter-the-battlefield abilities?",
    "clone": "Does this card become or create a copy of a permanent?",
    # Cards in hand
    "draw": "Does this card make you draw cards (not counting a draw that is immediately balanced by a discard)?",
    "discard": "Does this card make opponents discard cards?",
    "wheel": "Does this card make each player discard their hand and draw new cards, or make every player draw cards?",
    # Multiplayer / control
    "stax": "Does this card create an ongoing restriction or tax on opponents (extra costs, can't cast, can't untap, can't search), as opposed to a one-time effect like countering a single spell?",
    "steal": "Does this card gain control of an opponent's permanent, let you cast or play cards you don't own, or reward you for controlling permanents you don't own?",
    "group_hug": "Does this card give cards, mana, or other resources to opponents or to each player?",
    "pillow_fort": "Does this card make it harder or costlier for opponents to attack you (attack taxes, fogs, preventing combat damage to you)? Having defender does not count.",
    # Enablers EDHREC themes are built from (round 2)
    "discard_payoff": "Does this card let you discard cards as a cost, or reward you when you discard?",
    "draw_payoff": "Does this card trigger or reward when a player draws cards, or punish opponents for drawing?",
    "etb_creature": "Is this a creature with an enter-the-battlefield ability that gives you value?",
    "tutor": "Does this card search your library for a card?",
    # Staple interaction (not EDHREC themes, but every deck needs them)
    "removal": "Does this card destroy, exile, or neutralize a single target opponent's permanent?",
    "wipe": "Does this card destroy, exile, damage, or shrink all or most creatures at once (a board wipe), even if only some creatures or only on one mode?",
    "protection": "Does this card protect your creatures from removal or damage (indestructible, hexproof, prevention)?",
}
assert len(JEV) == 40, len(JEV)


def mana_value(cost: str) -> int:
    mv = 0
    for s in re.findall(r"\{([^}]*)\}", cost or ""):
        mv += int(s) if s.isdigit() else (0 if s in ("X", "Y") else 1)
    return mv


def free_tags(card: dict) -> set[str]:
    faces = card.get("card_faces") or [card]
    types = " ".join(f.get("type_line", "") for f in faces)
    text = "\n".join(f.get("oracle_text", "") for f in faces)
    cost = faces[0].get("mana_cost", "")
    kw = {k.lower() for k in card.get("keywords", [])}
    t = set()
    if "Equipment" in types: t.add("is_equipment")
    if "Aura" in types: t.add("is_aura")
    if "Artifact" in types: t.add("is_artifact")
    if "Enchantment" in types: t.add("is_enchantment")
    if "Legendary" in types: t.add("is_legendary")
    if "Legendary" in types or "Artifact" in types or "Saga" in types: t.add("is_historic")
    if "flying" in kw: t.add("kw_flying")
    if kw & {"infect", "toxic", "poisonous"} or "poison counter" in text: t.add("kw_infect")
    if "storm" in kw: t.add("kw_storm")
    if "landfall" in kw: t.add("kw_landfall")
    if re.search(r"\bmills?\b", text, re.I): t.add("kw_mill")
    if "Treasure" in text: t.add("kw_treasure")
    if re.search(r"additional combat", text, re.I): t.add("kw_extra_combat")
    if re.search(r"extra turn", text, re.I): t.add("kw_extra_turn")
    if "goad" in kw or re.search(r"\bgoad", text, re.I): t.add("kw_goad")
    if "-1/-1 counter" in text: t.add("kw_minus")
    if "proliferate" in kw: t.add("kw_proliferate")
    if re.search(r"\bcounter target\b[^.]*spell", text, re.I): t.add("kw_counterspell")
    if re.search(r"return ((up to \w+ )?(other |another )?target|each|all) [^.]*?(creature|permanent|artifact|enchantment|planeswalker)s?(?! cards?)[^.]* to (its|their) owner(?:'s|s'|s)? hands?", text, re.I): t.add("kw_bounce")
    if "{X}" in cost: t.add("kw_x")
    if mana_value(cost) >= 7: t.add("big_spell")
    if ("Instant" in types or "Sorcery" in types) and mana_value(cost) <= 2: t.add("cheap_spell")
    if ("Instant" in types or "Sorcery" in types or "Artifact" in types) and re.search(r"Add \{[WUBRGC]\}\{", text) and "{T}" not in text: t.add("ritual")
    if kw & {"flashback", "escape", "unearth", "embalm", "eternalize", "disturb", "jump-start", "retrace", "aftermath"}: t.add("kw_gy_cast")
    return t


# Theme name -> tags whose union means "this card fits the theme". Names follow EDHREC's
# theme vocabulary (https://edhrec.com/tags/themes) so results line up with what players
# call these decks; the mapping itself is ours.
THEMES = {
    "Tokens": ["creature_tokens", "token_payoff"],
    "+1/+1 Counters": ["plus_counters", "counters_payoff", "kw_proliferate"],
    "Artifacts": ["artifact_payoff", "mana_rock", "is_artifact"],
    "Spellslinger": ["spellslinger", "cheap_spell"],
    "Reanimator": ["reanimation", "self_mill"],
    "Lifegain": ["lifegain", "lifegain_payoff"],
    "Aristocrats": ["sac_outlet", "death_trigger", "drain"],
    "Burn": ["burn"],
    "Ramp": ["land_ramp", "mana_dork", "mana_rock", "cost_reduction"],
    "Lands Matter": ["land_payoff", "land_ramp", "kw_landfall"],
    "Voltron": ["voltron_payoff", "is_equipment", "is_aura", "protection"],
    "Equipment": ["is_equipment", "voltron_payoff"],
    "Auras": ["is_aura", "voltron_payoff", "enchantment_payoff"],
    "Enchantress": ["enchantment_payoff", "is_enchantment"],
    "Mill": ["kw_mill"],
    "Blink": ["blink", "etb_value", "etb_creature"],
    "Treasure": ["kw_treasure"],
    "Graveyard": ["self_mill", "reanimation", "recursion", "kw_gy_cast"],
    "Discard": ["discard", "wheel", "discard_payoff"],
    "Sacrifice": ["sac_outlet", "death_trigger"],
    "Clones": ["clone"],
    "Card Draw": ["draw", "wheel", "draw_payoff"],
    "Wheels": ["wheel", "draw_payoff"],
    "Group Slug": ["drain", "burn", "draw_payoff"],
    "Storm": ["kw_storm", "spellslinger", "cheap_spell", "ritual"],
    "Landfall": ["land_payoff", "kw_landfall"],
    "Stax": ["stax"],
    "Self-Mill": ["self_mill"],
    "Theft": ["steal"],
    "Extra Combats": ["kw_extra_combat"],
    "Group Hug": ["group_hug"],
    "Big Mana": ["kw_x", "big_spell", "mana_rock"],
    "X Spells": ["kw_x"],
    "Lifedrain": ["drain", "lifegain"],
    "Pillow Fort": ["pillow_fort"],
    "-1/-1 Counters": ["kw_minus"],
    "Forced Combat": ["kw_goad"],
    "Extra Turns": ["kw_extra_turn"],
    "Infect": ["kw_infect", "kw_proliferate"],
    "Flying": ["kw_flying"],
    "Legends": ["legends_payoff", "is_legendary"],
    "Historic": ["legends_payoff", "is_historic"],
    "ETB": ["etb_value", "blink", "etb_creature"],
}

# Staple roles every deck needs; not EDHREC themes, but asked about every card.
ROLES = {
    "Removal": ["removal"],
    "Board Wipe": ["wipe"],
    "Protection": ["protection"],
    "Tutor": ["tutor"],
    "Counterspell": ["kw_counterspell"],
    "Bounce": ["kw_bounce"],
}

THRESHOLD = 0.5  # a Jev answer counts as "yes" at P(yes) >= this


def slug(name: str) -> str:
    """"+1/+1 Counters" -> "plus1-counters", "Card Draw" -> "card-draw"."""
    s = name.lower().replace("+1/+1", "plus1").replace("-1/-1", "minus1")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


GROUPS = {slug(n): (n, tags, "theme") for n, tags in THEMES.items()} | {slug(n): (n, tags, "role") for n, tags in ROLES.items()}
