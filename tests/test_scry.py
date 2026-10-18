"""Offline tests: no network, no real card database."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scry import db as dbm, deck, render
from scry.lookup import Lookup

ARTIST = {"id": "a1", "name": "Blood Artist", "layout": "normal", "mana_cost": "{1}{B}", "type_line": "Creature — Vampire",
          "oracle_text": "Whenever this creature or another creature dies, target player loses 1 life and you gain 1 life.",
          "power": "0", "toughness": "1", "color_identity": ["B"], "edhrec_rank": 90, "legalities": {"commander": "legal", "standard": "not_legal"},
          "prices": {"usd": "0.25"}}
ABIGALE = {"id": "a2", "name": "Abigale, Eloquent First-Year", "layout": "normal", "mana_cost": "{W/B}{W/B}",
           "type_line": "Legendary Creature — Bird Bard", "power": "1", "toughness": "1",
           "oracle_text": "Flying, first strike, lifelink\nWhen Abigale enters, up to one other target creature loses all abilities. (Reminder.)"}
FELL = {"id": "a3", "name": "Fell the Profane // Fell Mire", "layout": "modal_dfc", "card_faces": [
    {"name": "Fell the Profane", "mana_cost": "{2}{B}{B}", "type_line": "Instant", "oracle_text": "Destroy target creature or planeswalker."},
    {"name": "Fell Mire", "mana_cost": "", "type_line": "Land", "oracle_text": "As this land enters, you may pay 3 life.\n({T}: Add {B}.)"}]}
TOKEN = {"id": "t1", "name": "Blood Artist", "layout": "token", "type_line": "Token Creature"}


def make_db(cards) -> dbm.DB:
    d = tempfile.mkdtemp()
    conn = sqlite3.connect(Path(d) / "cards.db")
    conn.executescript("CREATE TABLE cards (id TEXT PRIMARY KEY, name TEXT, data TEXT); CREATE TABLE names (key TEXT, card TEXT, rank INTEGER); CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);")
    for c in cards:
        t = dbm.trim(c)
        conn.execute("INSERT INTO cards VALUES (?,?,?)", (t["id"], t["name"], json.dumps(t)))
        conn.executemany("INSERT INTO names VALUES (?,?,?)", [(k, t["id"], int(c["layout"] == "token")) for k in dbm.aliases(t)])
    conn.commit()
    return dbm.DB(Path(d))


class Render(unittest.TestCase):
    def test_cost(self):
        self.assertEqual(render.cost("{2}{W}{W}"), "2WW")
        self.assertEqual(render.cost("{X}{W/B}{10}"), "X{W/B}10")
        self.assertEqual(render.cost(""), "")

    def test_basic_card(self):
        self.assertEqual(render.render(dbm.trim(ARTIST)), "Blood Artist · 1B · Creature — Vampire · 0/1\n" + ARTIST["oracle_text"])

    def test_reminder_and_short_legendary_name(self):
        out = render.render(dbm.trim(ABIGALE))
        self.assertIn("When ~ enters", out)
        self.assertNotIn("Reminder", out)
        self.assertIn("Abigale", render.render(dbm.trim(ABIGALE), raw=True).split("\n", 1)[1])

    def test_faces(self):
        self.assertEqual(render.render(dbm.trim(FELL)),
                         "Fell the Profane · 2BB · Instant\nDestroy target creature or planeswalker.\n// Fell Mire · Land\nAs this land enters, you may pay 3 life.")
        self.assertEqual(render.render(dbm.trim(FELL), short=True), "Fell the Profane · 2BB · Instant // Fell Mire · Land")

    def test_fields(self):
        out = render.render(dbm.trim(ARTIST), fields=render.FIELDS, short=True)
        self.assertTrue(out.endswith("· ci:B $0.25 edhrec:90 legal:commander"))

    def test_qty(self):
        self.assertTrue(render.render(dbm.trim(ARTIST), short=True, qty=3).startswith("3x Blood Artist"))


class Lookups(unittest.TestCase):
    def setUp(self):
        self.look = Lookup(make_db([ARTIST, ABIGALE, FELL, TOKEN]), online=False)

    def test_exact_prefers_real_card_over_token(self):
        card, note = self.look.find("blood artist")
        self.assertEqual((card["id"], note), ("a1", ""))

    def test_face_name_and_accents(self):
        self.assertEqual(self.look.find("Fell Mire")[0]["id"], "a3")
        self.assertEqual(self.look.find("Fell the Profane // Fell Mire")[0]["id"], "a3")

    def test_prefix_and_misspelling(self):
        self.assertEqual(self.look.find("abigale")[0]["id"], "a2")
        card, note = self.look.find("Blood Artst")
        self.assertEqual(card["id"], "a1")
        self.assertIn("→ Blood Artist", note)

    def test_miss(self):
        card, note = self.look.find("Xyzzy")
        self.assertIsNone(card)
        self.assertTrue(note.startswith('? "Xyzzy"'))


class Decklists(unittest.TestCase):
    def test_formats(self):
        text = """Commander
1 Amalia Benavides Aguirre (OTJ) 2
Deck
1x Sol Ring (CMR) 263 *F*
10 Plains
Swords to Plowshares [Removal]
// Maybeboard
1 Charming Prince
"""
        self.assertEqual(deck.parse_text(text), [
            (1, "Amalia Benavides Aguirre", "commander"), (1, "Sol Ring", "main"), (10, "Plains", "main"),
            (1, "Swords to Plowshares", "main"), (1, "Charming Prince", "maybe")])


if __name__ == "__main__":
    unittest.main()
