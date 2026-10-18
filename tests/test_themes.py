"""Offline tests for themes: no network, no Jev."""

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scry import cli, db as dbm, render
from scry.lookup import Lookup
from scry.themes import data
from scry.themes.questions import GROUPS, JEV, free_tags, slug

from test_scry import make_db

ARTIST = {"id": "a1", "name": "Blood Artist", "layout": "normal", "mana_cost": "{1}{B}", "type_line": "Creature — Vampire",
          "oracle_text": "Whenever this creature or another creature dies, target player loses 1 life and you gain 1 life.",
          "color_identity": ["B"], "edhrec_rank": 90}
BOLT = {"id": "b1", "name": "Lightning Bolt", "layout": "normal", "mana_cost": "{R}", "type_line": "Instant",
        "oracle_text": "Lightning Bolt deals 3 damage to any target.", "color_identity": ["R"], "edhrec_rank": 10}
TALRAND = {"id": "t1", "name": "Talrand, Sky Summoner", "layout": "normal", "mana_cost": "{2}{U}{U}", "type_line": "Legendary Creature — Merfolk Wizard",
           "oracle_text": "Whenever you cast an instant or sorcery spell, create a 2/2 blue Drake creature token with flying.",
           "color_identity": ["U"], "edhrec_rank": 500}
SWORDS = {"id": "s1", "name": "Swords to Plowshares", "layout": "normal", "mana_cost": "{W}", "type_line": "Instant",
          "oracle_text": "Exile target creature. Its controller gains life equal to its power.", "color_identity": ["W"]}
SWORDS2 = dict(SWORDS, id="s2", layout="prepare")  # a second card with the same name


def theme_file(rows) -> Path:
    path = Path(tempfile.mkdtemp()) / data.FILE
    data.write(path, {"format": 1, "date": "2026-10-18", "model": "test"}, rows)
    return path


class Questions(unittest.TestCase):
    def test_slugs(self):
        self.assertEqual(slug("+1/+1 Counters"), "plus1-counters")
        self.assertEqual(slug("Card Draw"), "card-draw")
        self.assertIn("aristocrats", GROUPS)
        self.assertEqual(GROUPS["removal"][2], "role")

    def test_every_group_tag_exists(self):
        free = {"is_equipment", "is_aura", "is_artifact", "is_enchantment", "is_legendary", "is_historic", "kw_flying", "kw_infect",
                "kw_storm", "kw_landfall", "kw_mill", "kw_treasure", "kw_extra_combat", "kw_extra_turn", "kw_goad", "kw_minus",
                "kw_proliferate", "kw_counterspell", "kw_bounce", "kw_x", "big_spell", "cheap_spell", "ritual", "kw_gy_cast"}
        for name, (_, tags, _) in GROUPS.items():
            for t in tags:
                self.assertTrue(t in JEV or t in free, f"{name}: unknown tag {t}")

    def test_free_tags(self):
        self.assertEqual(free_tags({"type_line": "Instant", "mana_cost": "{U}{U}", "oracle_text": "Counter target spell."}),
                         {"kw_counterspell", "cheap_spell"})
        self.assertIn("kw_mill", free_tags({"type_line": "Sorcery", "mana_cost": "{U}", "oracle_text": "Mill three cards."}))
        self.assertIn("kw_bounce", free_tags({"type_line": "Instant", "mana_cost": "{1}{U}",
                                              "oracle_text": "Return target creature an opponent controls to its owner's hand."}))
        self.assertNotIn("kw_bounce", free_tags({"type_line": "Sorcery", "mana_cost": "{1}{B}",
                                                 "oracle_text": "Return target creature card from your graveyard to your hand."}))


class Data(unittest.TestCase):
    def setUp(self):
        self.db = make_db([ARTIST, BOLT, TALRAND, SWORDS, SWORDS2])
        self.path = theme_file([
            ("Blood Artist", {"death_trigger": 0.84, "drain": 0.97, "lifegain": 0.97, "removal": 0.02}),
            ("Lightning Bolt", {"burn": 0.98, "spellslinger": 0.03}),
            ("Talrand, Sky Summoner", {"spellslinger": 0.99, "creature_tokens": 0.99}),
            ("Swords to Plowshares", {"removal": 0.83}),
            ("Not A Card", {"burn": 0.9}),
        ])
        self.info = data.load(self.db.conn, self.path)

    def test_round_trip_and_matching(self):
        meta, rows = data.read(self.path)
        self.assertEqual(meta["model"], "test")
        self.assertEqual(rows[1], ("Lightning Bolt", {"burn": 0.98, "spellslinger": 0.03}))
        self.assertEqual((self.info["matched"], self.info["unmatched"]), (4, 1))

    def test_low_answers_not_stored(self):
        self.assertNotIn("removal", data.card_tags(self.db.conn, "a1"))

    def test_fits(self):
        themes, roles = data.fits(data.card_tags(self.db.conn, "a1"))
        self.assertIn("aristocrats", themes)
        self.assertIn("lifegain", themes)
        self.assertEqual(roles, [])

    def test_cards_sharing_a_name_both_tagged(self):
        for cid in ("s1", "s2"):
            self.assertEqual(data.card_tags(self.db.conn, cid)["removal"], 0.83)

    def test_weak_tags_fit_but_rank_below_confirmed(self):
        sc = data.scores(self.db.conn, "spellslinger")
        self.assertEqual(sc["b1"], 0.5)  # cheap instant: fits by type alone
        self.assertGreater(sc["t1"], sc["b1"])

    def test_render_field(self):
        card = dbm.trim(ARTIST)
        card["_fits"] = data.fits(data.card_tags(self.db.conn, "a1"))
        out = render.render(card, ["themes"], short=True)
        self.assertIn(" · themes:", out)
        self.assertIn("aristocrats", out)


class Commands(unittest.TestCase):
    def setUp(self):
        self.db = make_db([ARTIST, BOLT, TALRAND, SWORDS])
        data.load(self.db.conn, theme_file([("Talrand, Sky Summoner", {"spellslinger": 0.99}), ("Blood Artist", {"drain": 0.97})]))
        self.look = Lookup(self.db, online=False)

    def run_cmd(self, fn, **kw):
        a = argparse.Namespace(**{"fields": [], "short": False, "raw": False, "ci": None, "limit": 20, "text": False, **kw})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = fn(a, self.look) if fn is cli.cmd_themes else fn(self.look, kw["names"])
        return code, out.getvalue()

    def test_theme_ranking_and_colors(self):
        code, out = self.run_cmd(cli.cmd_themes, names=["Spellslinger"])
        lines = out.splitlines()
        self.assertEqual(code, 0)
        self.assertTrue(lines[1].startswith("0.99 Talrand"))
        self.assertTrue(lines[2].startswith("0.50 Lightning Bolt"))
        _, out = self.run_cmd(cli.cmd_themes, names=["spellslinger"], ci="u")
        self.assertNotIn("Lightning Bolt", out)

    def test_unknown_theme(self):
        code, out = self.run_cmd(cli.cmd_themes, names=["aristocats"])
        self.assertEqual(code, 2)
        self.assertIn("maybe: aristocrats", out)

    def test_deck_summary(self):
        code, out = self.run_cmd(cli.deck_themes, names=["Blood Artist", "Swords to Plowshares", "Lightning Bolt"])
        self.assertIn("aristocrats 1", out)
        self.assertIn("removal 0", out)


if __name__ == "__main__":
    unittest.main()
