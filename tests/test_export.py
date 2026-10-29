# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Tests for tools/export_cs2_charms.py with synthetic game data (no Valve
assets): KeyValues parsing, item metadata, vmat parsing and the library
build, including a round trip through the add-on's catalog loader."""

import importlib.util
import json
import os
import struct
import tempfile
import unittest

from cs_charm.library import catalog as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_tool():
    path = os.path.join(ROOT, "tools", "export_cs2_charms.py")
    spec = importlib.util.spec_from_file_location("export_cs2_charms", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


X = _load_tool()

ITEMS_GAME = r'''
"items_game"
{
    // comment
    "client_loot_lists"
    {
        "keychain_pack_test_rare"
        {
            "[kc_dog]keychain"      "1"
        }
        "keychain_pack_test_ancient"
        {
            "[kc_flask]keychain"    "1"
        }
    }
    "keychain_definitions"
    {
        "1"
        {
            "name"      "kc_dog"
            "loc_name"  "#keychain_kc_dog"
            "item_rarity"   "rare"
            "image_inventory"   "econ/keychains/test/kc_dog"
            "pedestal_display_model"    "weapons/keychains/test/kc_dog.vmdl"
            "display_seed"  "1234"
        }
    }
    "keychain_definitions"
    {
        "2"
        {
            "name"      "kc_flask"
            "loc_name"  "#keychain_kc_flask"
            "item_rarity"   "ancient"
            "pedestal_display_model"    "weapons/keychains/test/kc_flask.vmdl"
        }
        "3"
        {
            "name"      "kc_community"
            "loc_name"  "#keychain_kc_community"
            "item_rarity"   "rare"
            "pedestal_display_model"    "weapons/keychains/workshop_blanks/kc_blank.vmdl"
            "keychain_material" "weapons/keychains/community/kc_community.vmat"
            "tags"
            {
                "KeychainCapsule"
                {
                    "tag_text"  "#CSGO_community_capsule"
                }
            }
        }
        "4"
        {
            "name"      "kc_reel"
            "highlight_reel"    "1"
            "base"      "kc_dog"
            "pedestal_display_model"    "weapons/keychains/test/kc_dog.vmdl"
        }
        "5"
        {
            "name"      "kc_unexported"
            "pedestal_display_model"    "weapons/keychains/test/kc_missing.vmdl"
        }
    }
}
'''

TOKENS = '''"lang"
{
    "Language"  "english"
    "Tokens"
    {
        "keychain_kc_dog"   "Test Dog"
        "keychain_kc_flask" "Test Flask"
        "keychain_kc_community" "Community Thing"
        "CSGO_crate_keychain_pack_test_capsule" "Test Charms"
        "CSGO_community_capsule"    "Community Charms"
    }
}
'''

DOG_VMAT = r'''// generated
Layer0
{
    shader "csgo_weapon.vfx"
    F_ENABLE_ADJUSTMENTS 1
    g_fHueShift "12.5"
    g_vColorTint "[1.000000 0.500000 0.250000 0.000000]"
    TextureColor "ignored"
    DynamicParams
    {
        g_fHueShift "return lerp(0, 360, $KeychainSeed);\nreturn 0;"
    }
    "Compiled Textures"
    {
        g_tColor "weapons/keychains/test/kc_dog_color_png_1a2b.vtex"
        g_tTintMask "weapons/keychains/test/kc_dog_mask_png_3c4d.vtex"
    }
}
'''

COMMUNITY_VMAT = '''Layer0
{
    shader "csgo_weapon.vfx"
    "Compiled Textures"
    {
        g_tColor "weapons/keychains/community/kc_community_color_png_aa.vtex"
    }
}
'''


def _write_glb(path, data):
    payload = json.dumps(data).encode("utf-8")
    payload += b" " * (-len(payload) % 4)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(payload)))
        fh.write(struct.pack("<II", len(payload), 0x4E4F534A))
        fh.write(payload)


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"png")


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _vmat_extras(name, shader, textures):
    return {"vmat": {"Name": name, "ShaderName": shader, "IntParams": {"F_TEST": 1},
                     "TextureParams": textures}}


def _fake_export(raw):
    """Lay out what Source2Viewer would have written to raw/."""
    test = os.path.join(raw, "weapons", "keychains", "test")
    _write_glb(os.path.join(test, "kc_dog.glb"), {
        "asset": {"version": "2.0"},
        "images": [{"uri": "kc_dog_color_png_1a2b.png"}],
        "materials": [
            {"name": "kc_dog", "extras": _vmat_extras("weapons/keychains/test/kc_dog.vmat", "csgo_weapon.vfx",
                                                      {"g_tColor": "kc_dog_color_png_1a2b.vtex"})},
            {"name": "kc_chain", "extras": _vmat_extras("weapons/keychains/shared/kc_chain.vmat",
                                                        "csgo_weapon.vfx", {"g_tColor": "kc_chain_png_ff.vtex"})},
        ]})
    _touch(os.path.join(test, "kc_dog_color_png_1a2b.png"))
    _touch(os.path.join(test, "kc_dog_mask_png_3c4d.png"))
    _touch(os.path.join(test, "kc_chain_png_ff.png"))
    _write(os.path.join(test, "kc_dog.vmat"), DOG_VMAT)
    _write_glb(os.path.join(test, "kc_flask.glb"), {
        "asset": {"version": "2.0"},
        "materials": [{"name": "kc_flask", "extras": _vmat_extras(
            "weapons/keychains/test/kc_flask.vmat", "csgo_simple_liquid.vfx", {})}]})
    blanks = os.path.join(raw, "weapons", "keychains", "workshop_blanks")
    _write_glb(os.path.join(blanks, "kc_blank.glb"), {
        "asset": {"version": "2.0"},
        "materials": [
            {"name": "kc_blank", "extras": _vmat_extras("weapons/keychains/workshop_blanks/kc_blank.vmat",
                                                        "csgo_weapon.vfx", {})},
            {"name": "kc_chain", "extras": _vmat_extras("weapons/keychains/shared/kc_chain.vmat",
                                                        "csgo_weapon.vfx", {"g_tColor": "kc_chain_png_ff.vtex"})},
        ]})
    _touch(os.path.join(blanks, "kc_chain_png_ff.png"))
    community = os.path.join(raw, "weapons", "keychains", "community")
    _write(os.path.join(community, "kc_community.vmat"), COMMUNITY_VMAT)
    _touch(os.path.join(community, "kc_community_color_png_aa.png"))
    _touch(X.icon_raw_path(raw, "econ/keychains/test/kc_dog"))


class KeyValuesTest(unittest.TestCase):
    def test_parse_kv_keeps_duplicates_and_skips_comments(self):
        data = X.parse_kv(ITEMS_GAME)
        blocks = list(X.find_blocks(data, "keychain_definitions"))
        self.assertEqual(len(blocks), 2)
        self.assertNotIn("comment", json.dumps(data))

    def test_escaped_quotes(self):
        data = X.parse_kv(r'"a" "say \"hi\""')
        self.assertEqual(data, [("a", r'say \"hi\"')])

    def test_load_items_and_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            items, tokens = os.path.join(tmp, "items_game.txt"), os.path.join(tmp, "english.txt")
            _write(items, ITEMS_GAME)
            _write(tokens, TOKENS)
            defs, packs = X.load_items(items)
            toks = X.load_tokens(tokens)
        self.assertEqual(sorted(defs), ["1", "2", "3", "4", "5"])
        self.assertEqual(packs, {"kc_dog": "test", "kc_flask": "test"})
        self.assertEqual(toks["keychain_kc_dog"], "Test Dog")
        self.assertEqual(X.describe("1", defs["1"], toks, packs), ("Test Dog", "Test Charms"))
        # No loot list: collection from the KeychainCapsule tag.
        self.assertEqual(X.describe("3", defs["3"], toks, packs), ("Community Thing", "Community Charms"))
        # Unknown token and no pack: pretty name and folder name.
        self.assertEqual(X.describe("5", defs["5"], toks, packs), ("Kc Unexported", "Test"))
        # Highlight reels are skipped.
        self.assertEqual([i for i, _e in X.charm_entries(defs)], ["1", "2", "3", "5"])


class VmatTest(unittest.TestCase):
    def test_parse_vmat(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "kc_dog.vmat")
            _write(path, DOG_VMAT)
            spec = X.parse_vmat(path)
        self.assertEqual(spec["shader"], "csgo_weapon.vfx")
        self.assertEqual(spec["params"]["F_ENABLE_ADJUSTMENTS"], 1)
        self.assertEqual(spec["params"]["g_fHueShift"], 12.5)
        self.assertEqual(spec["params"]["g_vColorTint"], [1.0, 0.5, 0.25, 0.0])
        self.assertNotIn("TextureColor", spec["params"])
        self.assertIn("\n", spec["dynamic"]["g_fHueShift"])
        self.assertEqual(set(spec["compiled"]), {"g_tColor", "g_tTintMask"})

    def test_raw_paths(self):
        raw = os.path.join("r")
        self.assertEqual(X.model_raw_path(raw, "weapons/keychains/a/b.vmdl"),
                         os.path.join("r", "weapons", "keychains", "a", "b.glb"))
        self.assertEqual(X._vpk_to_raw(raw, "x/y.vtex_c", ".png"), os.path.join("r", "x", "y.png"))


class BuildLibraryTest(unittest.TestCase):
    def test_build_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw, out = os.path.join(tmp, "raw"), os.path.join(tmp, "lib")
            items, tokens = os.path.join(tmp, "items_game.txt"), os.path.join(tmp, "english.txt")
            _write(items, ITEMS_GAME)
            _write(tokens, TOKENS)
            _fake_export(raw)
            defs, packs = X.load_items(items)
            toks = X.load_tokens(tokens)
            self.assertEqual(X.needed_textures(raw, defs),
                             {"weapons/keychains/community/kc_community_color_png_aa.vtex_c"})

            charms, skipped, warnings = X.build_library(out, raw, defs, toks, packs)
            self.assertEqual(skipped, 1)
            self.assertTrue(any("kc_missing" in w for w in warnings))
            self.assertEqual([c["name"] for c in charms], ["Test Dog", "Test Flask", "Community Thing"])

            with open(os.path.join(out, C.CATALOG_FILE), encoding="utf-8") as fh:
                data = json.load(fh)
            mats = data["materials"]
            dog = mats["weapons/keychains/test/kc_dog.vmat"]
            # vmat params win over glTF extras, both are kept.
            self.assertEqual(dog["params"]["g_fHueShift"], 12.5)
            self.assertEqual(dog["params"]["F_TEST"], 1)
            self.assertIn("$KeychainSeed", dog["dynamic"]["g_fHueShift"])
            self.assertEqual(dog["textures"], {"g_tColor": "test/kc_dog_color_png_1a2b.png",
                                               "g_tTintMask": "test/kc_dog_mask_png_3c4d.png"})
            # The community charm uses the blank model with its override material,
            # the chain keeps its own.
            community = data["charms"][2]
            self.assertEqual(community["model"], "workshop_blanks/kc_blank.glb")
            self.assertEqual(community["slots"]["kc_blank"], "weapons/keychains/community/kc_community.vmat")
            self.assertEqual(community["slots"]["kc_chain"], "weapons/keychains/shared/kc_chain.vmat")
            self.assertEqual(mats["weapons/keychains/community/kc_community.vmat"]["textures"]["g_tColor"],
                             "workshop_blanks/kc_community_color_png_aa.png")
            self.assertEqual(data["charms"][0]["icon"], "icons/kc_dog_png.png")
            self.assertEqual(data["charms"][1]["icon"], "")

            # Round trip through the add-on loader.
            cat = C.Catalog().load(user_dir=out)
            self.assertEqual(cat.report.warnings, [])
            dog_charm = cat.get(charms[0]["id"])
            self.assertEqual(dog_charm.collection, "Test Charms")
            self.assertEqual(dog_charm.rarity, "rare")
            self.assertTrue(dog_charm.has_pattern())
            self.assertEqual(dog_charm.missing_files(), [])
            self.assertTrue(os.path.isfile(dog_charm.model))
            flask = cat.get(charms[1]["id"])
            self.assertTrue(any(m.is_liquid for m in flask.materials()))


if __name__ == "__main__":
    unittest.main()
