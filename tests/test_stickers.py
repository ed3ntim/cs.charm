# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Unit tests for the sticker library loader (library/stickers.py).
Entries mirror the catalog.json that cs.sticker's exporter writes."""

import json
import os
import tempfile
import unittest

from cs_charm.library import stickers as ST

OLD_ENTRIES = [
    {"id": "cs2_kat2015_titan_holo", "name": "Titan (Holo)", "collection": "Katowice 2015",
     "finish": "HOLO", "textures": {"base": "textures/titan_holo.png", "holomask": "textures/titan_mask.png",
                                    "bogus": "x.png"},
     "params": {"Wear Bias": 0.6, "note": "text"}, "tags": ["kat2015/titan_holo", "mythical"]},
    {"id": "cs2_alyx_big_hugs", "name": "Big Hugs", "collection": "Alyx", "finish": "PAPER",
     "textures": {"base": "textures/big_hugs.png"}, "tags": ["alyx/big_hugs", "rare"]},
    {"id": "cs2_howl", "name": "Howling Dawn", "collection": "Community", "finish": "PAPER",
     "textures": {"base": "textures/howl.png"}, "tags": ["community/howl", "immortal"]},
    {"name": "niko (Gold) | Paris 2023", "collection": "Paris 2023",
     "textures": {"base": "textures/niko_gold.png"}, "tags": ["paris2023/sig_niko_gold", "ancient"]},
    {"name": "", "textures": {"base": "a.png"}},
    "not an entry",
]

NEW_ENTRY = {"id": "cs2_new", "name": "Liquid Fire (Holo)", "collection": "Op Riptide", "finish": "HOLO",
             "rarity": "legendary", "event": "", "textures": {"base": "b.png"}, "tags": ["x", "rare"]}


def _write_catalog(folder, entries):
    path = os.path.join(folder, ST.CATALOG_FILE)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "stickers": entries}, fh)
    return path


class StickerEntryTest(unittest.TestCase):
    def entry(self, data, base="C:/lib"):
        return ST.sticker_from_entry(data, base)

    def test_old_catalog_fallbacks(self):
        s = self.entry(OLD_ENTRIES[0])
        self.assertEqual(s.rarity, "mythical")
        self.assertEqual(s.event, "Katowice 2015")
        self.assertEqual(s.label_text(), "Titan (Holo) | Katowice 2015")
        self.assertEqual(s.finish_label, "Holo")
        self.assertEqual(set(s.textures), {"base", "holomask"})
        self.assertTrue(os.path.isabs(s.textures["base"]))
        self.assertEqual(s.params, {"Wear Bias": 0.6})
        self.assertEqual(s.kit_id, 0)  # id without kit number

    def test_kit_id_is_serial(self):
        # In-game views (cs.charm-dev#13): label serial = sticker kit id.
        s = self.entry(dict(OLD_ENTRIES[0], id="cs2_343_eslkatowice2015_titan_holo"))
        self.assertEqual(s.kit_id, 343)
        self.assertEqual(s.serial(), "0000000343")
        # Non-event stickers have a kit id just the same.
        alyx = self.entry(dict(OLD_ENTRIES[1], id="cs2_4602_alyx_art_vort"))
        self.assertEqual(alyx.event, "")
        self.assertEqual(alyx.serial(), "0000004602")
        # An explicit field wins; user stickers without one print zeros.
        self.assertEqual(self.entry(dict(OLD_ENTRIES[1], kit_id=77)).kit_id, 77)
        self.assertEqual(self.entry(dict(OLD_ENTRIES[1], id="my_own")).serial(), "0000000000")

    def test_capsule_without_event(self):
        s = self.entry(OLD_ENTRIES[1])
        self.assertEqual(s.event, "")
        self.assertEqual(s.label_text(), "Big Hugs")
        self.assertEqual(s.rarity, "rare")

    def test_immortal_is_contraband(self):
        s = self.entry(OLD_ENTRIES[2])
        self.assertEqual(s.rarity, "contraband")
        self.assertEqual(s.rarity_label, "Contraband")

    def test_full_market_name_and_finish_guess(self):
        s = self.entry(OLD_ENTRIES[3])
        self.assertEqual(s.name, "niko (Gold)")
        self.assertEqual(s.event, "Paris 2023")
        self.assertEqual(s.finish, "GOLD")
        self.assertTrue(s.id)

    def test_new_fields_win(self):
        s = self.entry(NEW_ENTRY)
        self.assertEqual(s.rarity, "legendary")
        self.assertEqual(s.event, "")  # explicit empty event: no year guessing
        self.assertEqual(s.label_text(), "Liquid Fire (Holo)")

    def test_invalid_entries(self):
        self.assertIsNone(self.entry(OLD_ENTRIES[4]))
        self.assertIsNone(self.entry(OLD_ENTRIES[5]))

    def test_round_trip(self):
        s = self.entry(OLD_ENTRIES[0])
        back = ST.Sticker.from_dict(json.loads(json.dumps(s.to_dict())))
        self.assertEqual((back.id, back.name, back.finish, back.rarity, back.event, back.kit_id, back.textures),
                         (s.id, s.name, s.finish, s.rarity, s.event, s.kit_id, s.textures))
        old = {k: v for k, v in s.to_dict().items() if k != "kit_id"}  # stored by 1.4.0
        self.assertEqual(ST.Sticker.from_dict(dict(old, id="cs2_99_x")).kit_id, 99)
        self.assertEqual(back.label_text(), s.label_text())


class StickerHelpersTest(unittest.TestCase):
    def test_rarity_color(self):
        self.assertEqual(ST.rarity_color("unknown"), (1.0, 1.0, 1.0))
        self.assertNotEqual(ST.rarity_color("rare"), ST.rarity_color("mythical"))
        self.assertEqual(ST.rarity_color("immortal"), ST.rarity_color("contraband"))

    def test_event_detection(self):
        for name in ("Paris 2023", "2020 RMR", "Katowice 2015"):
            self.assertTrue(ST.looks_like_event(name), name)
        for name in ("Alyx", "Op Riptide", "", "Community / Misc"):
            self.assertFalse(ST.looks_like_event(name), name)

    def test_serial(self):
        self.assertEqual(ST.format_serial(1337), "0000001337")
        self.assertEqual(ST.format_serial(-5), "0000000000")
        self.assertEqual(len(ST.format_serial(10 ** 12 + 7)), ST.SERIAL_DIGITS)


class StickerLibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        _write_catalog(root, OLD_ENTRIES)
        os.makedirs(os.path.join(root, "extra"))
        _write_catalog(os.path.join(root, "extra"), [NEW_ENTRY, dict(OLD_ENTRIES[1], name="Big Hugs v2")])
        self.lib = ST.StickerLibrary().load(root, "")

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_and_override(self):
        # 4 valid in the root, 2 in extra; the duplicate id from extra wins.
        self.assertEqual(len(self.lib), 5)
        self.assertEqual(self.lib.get("cs2_alyx_big_hugs").name, "Big Hugs v2")
        self.assertTrue(ST.is_library(self.tmp.name))
        self.assertFalse(ST.is_library(os.path.join(self.tmp.name, "missing")))

    def test_filters(self):
        self.assertEqual([s.id for s in self.lib.filter(search="titan holo")], ["cs2_kat2015_titan_holo"])
        self.assertEqual({s.finish for s in self.lib.filter(finish="HOLO")}, {"HOLO"})
        self.assertEqual(len(list(self.lib.filter(rarity="rare"))), 1)
        self.assertEqual(len(list(self.lib.filter(collection="Paris 2023"))), 1)
        self.assertEqual(len(list(self.lib.filter(search="katowice"))), 1)
        self.assertIn("HOLO", self.lib.finishes())
        self.assertEqual(self.lib.rarities()[0], "rare")
        self.assertIn("Alyx", self.lib.collections())

    def test_broken_catalog(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, ST.CATALOG_FILE), "w") as fh:
                fh.write("{broken")
            lib = ST.StickerLibrary().load(root)
            self.assertEqual(len(lib), 0)
            self.assertTrue(lib.report.warnings)


if __name__ == "__main__":
    unittest.main()
