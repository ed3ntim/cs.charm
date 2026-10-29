# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Unit tests for the pure-Python charm library: DynamicParams evaluator,
patterns, glTF extras, catalog and the shader parameter mapping.

The expressions below are copied from real CS2 charm materials
(DynamicParams of the decompiled .vmat files)."""

import json
import math
import os
import struct
import tempfile
import unittest

from cs_charm.library import catalog as C
from cs_charm.library import expr, gltf, patterns
from cs_charm.library import shading as S

BUTANE_BUDDY = {
    "g_flLiquidColorHueShift": "return lerp(0,320,$KeychainSeed);",
    "g_flLiquidLevelHeight": "return lerp(.45,.8,frac($KeychainSeed*100));",
    "g_flTestAgitation": "return clamp(pow(1-$bone_upvector$liquid_surface.z,.65)*2.5,.25,1)*1.5;",
    "g_vTestGravityDir": "return -lerp(float3(0,0,1),$bone_upvector$liquid_surface,1.25);",
}
# That's Bananas: multi-statement with local variables and comparisons,
# stored with escaped line breaks like in the .vmat file.
BANANA_HUE = ("v0 = pow(sin($KeychainSeed*3.14159),.5)*.5;\\nv1 = v0*($KeychainSeed<=.5)+.5*($KeychainSeed>.5);"
              "\\nv2 = .5+(.5-v0)*($KeychainSeed>.5);\\nreturn lerp(lerp(-90,0,v1),50,v2);")
EIGHT_BALL_OFFSET = ("v0 = $ent_weapon_shake.y%3;\\nreturn (v0>2) ? float2(-.681,-.777) : "
                     "(v0>1) ? float2(-.184,-.777) : float2(-.681,-.278);")
SLAB_TINT = "return exists($sticker_rarity_color) ? $sticker_rarity_color : float3(1,1,1);"


class ExprTest(unittest.TestCase):
    def ev(self, text, **env):
        return expr.evaluate(text, {f"${k}": v for k, v in env.items()})

    def test_arithmetic_precedence(self):
        self.assertAlmostEqual(self.ev("return 1+2*3-4/2;"), 5.0)
        self.assertAlmostEqual(self.ev("return -(2+3)*2;"), -10.0)
        self.assertAlmostEqual(self.ev("return 7%3;"), 1.0)
        self.assertAlmostEqual(self.ev("return .5+1.;"), 1.5)

    def test_functions(self):
        self.assertAlmostEqual(self.ev("return lerp(.45,.8,.5);"), 0.625)
        self.assertAlmostEqual(self.ev("return frac(2.75);"), 0.75)
        self.assertAlmostEqual(self.ev("return frac(-0.25);"), 0.75)
        self.assertAlmostEqual(self.ev("return clamp(5,0,1);"), 1.0)
        self.assertAlmostEqual(self.ev("return pow(2,10);"), 1024.0)
        self.assertAlmostEqual(self.ev("return abs(cos(3.14159265));"), 1.0, places=6)
        self.assertAlmostEqual(self.ev("return saturate(-2);"), 0.0)

    def test_vectors_and_swizzle(self):
        self.assertEqual(self.ev("return float2(1,2)*2;"), (2.0, 4.0))
        self.assertEqual(self.ev("return -lerp(float3(0,0,1),float3(0,0,3),.5);"), (-0.0, -0.0, -2.0))
        self.assertAlmostEqual(self.ev("return $v.z*2;", v=(1, 2, 3)), 6.0)
        self.assertEqual(self.ev("return $v.yx;", v=(1, 2, 3)), (2.0, 1.0))

    def test_locals_ternary_and_escaped_newlines(self):
        self.assertEqual(self.ev(EIGHT_BALL_OFFSET, ent_weapon_shake=(0, 2.5, 0)), (-0.681, -0.777))
        self.assertEqual(self.ev(EIGHT_BALL_OFFSET, ent_weapon_shake=(0, 1.5, 0)), (-0.184, -0.777))
        self.assertEqual(self.ev(EIGHT_BALL_OFFSET), (-0.681, -0.278))

    def test_exists(self):
        self.assertEqual(self.ev(SLAB_TINT), (1.0, 1.0, 1.0))
        self.assertEqual(self.ev(SLAB_TINT, sticker_rarity_color=(1, 0, 0)), (1.0, 0.0, 0.0))

    def test_unknown_variables_default_to_zero(self):
        self.assertEqual(self.ev("return $nothing+1;"), 1.0)

    def test_errors(self):
        for bad in ("return eval(1);", "return 1 +;", "return __import__('os');", "return (1;", "x"):
            with self.assertRaises(expr.ExprError, msg=bad):
                expr.evaluate(bad)

    def test_variables_used(self):
        self.assertEqual(expr.variables_used(BUTANE_BUDDY["g_flTestAgitation"]), {"$bone_upvector$liquid_surface"})


class PatternTest(unittest.TestCase):
    def test_seed_range(self):
        self.assertEqual(patterns.seed_from_pattern(0), 0.0)
        self.assertEqual(patterns.seed_from_pattern(100000), 1.0)
        self.assertEqual(patterns.seed_from_pattern(50000), 0.5)
        self.assertEqual(patterns.seed_from_pattern(-5), 0.0)
        self.assertEqual(patterns.seed_from_pattern(10 ** 9), 1.0)

    def test_butane_buddy(self):
        values, errors = patterns.evaluate_dynamic(BUTANE_BUDDY, 12345)
        self.assertEqual(errors, {})
        # Only seed-driven params; sloshing / gravity keep their rest values.
        self.assertEqual(set(values), {"g_flLiquidColorHueShift", "g_flLiquidLevelHeight"})
        self.assertAlmostEqual(values["g_flLiquidColorHueShift"], 320 * 0.12345)
        self.assertAlmostEqual(values["g_flLiquidLevelHeight"], 0.45 + 0.35 * 0.345, places=6)
        # Fill level repeats every 1000 patterns, color does not.
        a, _ = patterns.evaluate_dynamic(BUTANE_BUDDY, 345)
        self.assertAlmostEqual(a["g_flLiquidLevelHeight"], values["g_flLiquidLevelHeight"], places=6)
        self.assertNotAlmostEqual(a["g_flLiquidColorHueShift"], values["g_flLiquidColorHueShift"])

    def test_runtime_params_with_rest_env(self):
        values, errors = patterns.evaluate_dynamic(BUTANE_BUDDY, 0, only_seed=False)
        self.assertEqual(errors, {})
        self.assertAlmostEqual(values["g_flTestAgitation"], 0.25 * 1.5)  # surface level -> minimum
        self.assertEqual(values["g_vTestGravityDir"], (-0.0, -0.0, -1.0))

    def test_banana(self):
        values, errors = patterns.evaluate_dynamic({"g_fHueShift": BANANA_HUE}, 25000)
        self.assertEqual(errors, {})
        seed = 0.25  # seed <= .5: v1 = v0, v2 = .5
        v0 = math.sqrt(math.sin(seed * 3.14159)) * 0.5
        self.assertAlmostEqual(values["g_fHueShift"], ((-90 + 90 * v0) + 50) / 2, places=6)
        high, _ = patterns.evaluate_dynamic({"g_fHueShift": BANANA_HUE}, 100000)
        self.assertAlmostEqual(high["g_fHueShift"], 50.0, delta=0.1)  # seed 1: v2 ~ 1

    def test_seed_params(self):
        self.assertEqual(patterns.seed_params(BUTANE_BUDDY), ["g_flLiquidColorHueShift", "g_flLiquidLevelHeight"])
        self.assertFalse(patterns.uses_seed("return 1 +;"))

    def test_random_pattern(self):
        for _ in range(50):
            self.assertTrue(0 <= patterns.random_pattern() <= patterns.PATTERN_MAX)


def _write_glb(path, data):
    payload = json.dumps(data).encode("utf-8")
    payload += b" " * (-len(payload) % 4)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", gltf.GLB_MAGIC, 2, 12 + 8 + len(payload)))
        fh.write(struct.pack("<II", len(payload), gltf.CHUNK_JSON))
        fh.write(payload)


S2V_MATERIAL = {
    "name": "kc_test",
    "extras": {"vmat": {
        "Name": "weapons/keychains/test/materials/kc_test.vmat",
        "ShaderName": "csgo_weapon.vfx",
        "IntParams": {"F_ENABLE_ADJUSTMENTS": 1, "F_TINT_MASK": 1},
        "FloatParams": {"g_fHueShift": 30, "g_fSaturation": 1.2},
        "VectorParams": {"g_vMetalnessRemapRange": [0.1, 0.9, 0, 0]},
        "TextureParams": {"g_tColor": "kc_test_color_png_1234abcd.vtex",
                          "g_tTintMask": "kc_test_mask_png_99.vtex"},
    }},
}


class GltfTest(unittest.TestCase):
    def test_glb_extras_to_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            glb = os.path.join(tmp, "kc_test.glb")
            _write_glb(glb, {"asset": {"version": "2.0"},
                             "materials": [S2V_MATERIAL, {"name": "plain"}]})
            open(os.path.join(tmp, "kc_test_color_png_1234abcd.png"), "wb").close()
            mats = gltf.material_extras(gltf.read_json(glb))
            self.assertEqual([m[0] for m in mats], ["kc_test", "plain"])
            self.assertIsNone(mats[1][1])
            spec = gltf.spec_from_vmat_extras(mats[0][1], tmp)
            self.assertEqual(spec["shader"], "csgo_weapon.vfx")
            self.assertEqual(spec["params"]["g_fHueShift"], 30)
            self.assertEqual(spec["params"]["g_vMetalnessRemapRange"], [0.1, 0.9, 0, 0])
            # Only textures that exist next to the model are kept.
            self.assertEqual(list(spec["textures"]), ["g_tColor"])

    def test_bad_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.glb")
            with open(path, "wb") as fh:
                fh.write(b"not a model")
            with self.assertRaises(ValueError):
                gltf.read_json(path)


def _catalog_json(tmp):
    os.makedirs(os.path.join(tmp, "drboom"))
    for name in ("kc_db_lighter.glb", "liquid_color.png", "chain_color.png"):
        open(os.path.join(tmp, "drboom", name), "wb").close()
    data = {
        "version": 1,
        "charms": [
            {"id": "cs2_81_kc_db_lighter", "def_index": 81, "name": "Butane Buddy",
             "collection": "Dr Boom Charm Collection", "rarity": "ancient",
             "model": "drboom/kc_db_lighter.glb", "display_seed": 1,
             "slots": {"kc_db_chain": "chain.vmat", "kc_db_lighter": "lighter.vmat"}},
            {"id": "cs2_7_kc_missinglink_howl", "name": "Hot Howl", "collection": "Missing Link Charm Collection",
             "rarity": "ancient", "model": "missinglink/kc_missinglink_howl.glb",
             "slots": {"kc_missinglink_howl": "nope.vmat"}},
            {"name": "No Model"},
        ],
        "materials": {
            "chain.vmat": {"shader": "csgo_weapon.vfx", "textures": {"g_tColor": "drboom/chain_color.png"}},
            "lighter.vmat": {"shader": "csgo_simple_liquid.vfx",
                             "textures": {"g_tColorA": "drboom/liquid_color.png",
                                          "g_tLiquidMask": "drboom/missing_mask.png"},
                             "params": {"g_flLiquidLevelHeight": 0.761},
                             "dynamic": BUTANE_BUDDY},
        },
    }
    with open(os.path.join(tmp, C.CATALOG_FILE), "w", encoding="utf-8") as fh:
        json.dump(data, fh)


class CatalogTest(unittest.TestCase):
    def test_load_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            _catalog_json(tmp)
            cat = C.Catalog().load(user_dir=tmp)
            self.assertEqual(len(cat.charms), 2)
            bb = cat.get("cs2_81_kc_db_lighter")
            self.assertEqual(bb.rarity_label, "Extraordinary")
            self.assertEqual(bb.def_index, 81)
            self.assertEqual(bb.display_seed, 1)
            self.assertTrue(bb.model.endswith(os.path.join("drboom", "kc_db_lighter.glb")))
            self.assertTrue(bb.has_pattern())
            self.assertIn("Liquid", bb.effects())
            self.assertIn("Pattern Fill Level", bb.effects())
            self.assertEqual(bb.missing_files(), ["lighter.vmat:g_tLiquidMask"])
            howl = cat.get("cs2_7_kc_missinglink_howl")
            self.assertEqual(howl.missing_files(), ["model"])
            self.assertTrue(any("unknown material" in w for w in cat.report.warnings))
            self.assertTrue(any("no model" in w for w in cat.report.warnings))

    def test_filter_and_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            _catalog_json(tmp)
            cat = C.Catalog().load(user_dir=tmp)
            self.assertEqual([c.name for c in cat.filter("butane")], ["Butane Buddy"])
            self.assertEqual([c.name for c in cat.filter("liquid")], ["Butane Buddy"])
            self.assertEqual([c.name for c in cat.filter("extraordinary howl")], ["Hot Howl"])
            self.assertEqual(len(list(cat.filter(rarity="ancient"))), 2)
            self.assertEqual(len(list(cat.filter(rarity="rare"))), 0)
            self.assertEqual([c.name for c in cat.filter(collection="Dr Boom Charm Collection")], ["Butane Buddy"])
            self.assertEqual(cat.rarities(), ["ancient"])
            self.assertEqual(len(cat.collections()), 2)

    def test_loose_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "My Charms", "icons"))
            for name in ("lil_thing.glb", "lil_thing_physics.glb", "notes.txt"):
                open(os.path.join(tmp, "My Charms", name), "wb").close()
            open(os.path.join(tmp, "My Charms", "icons", "lil_thing.png"), "wb").close()
            open(os.path.join(tmp, "root.gltf"), "w").close()
            cat = C.Catalog().load(user_dir=tmp)
            names = {c.name: c for c in cat.charms}
            self.assertEqual(set(names), {"Lil Thing", "Root"})
            self.assertEqual(names["Lil Thing"].collection, "My Charms")
            self.assertTrue(names["Lil Thing"].icon.endswith("lil_thing.png"))
            self.assertEqual(names["Root"].collection, C.DEFAULT_COLLECTION)

    def test_user_overrides_core_by_id(self):
        with tempfile.TemporaryDirectory() as core, tempfile.TemporaryDirectory() as user:
            for root, name in ((core, "Core Name"), (user, "User Name")):
                with open(os.path.join(root, C.CATALOG_FILE), "w") as fh:
                    json.dump({"charms": [{"id": "same", "name": name, "model": "a.glb"}]}, fh)
            cat = C.Catalog().load(core_dir=core, user_dir=user)
            self.assertEqual([c.name for c in cat.charms], ["User Name"])

    def test_core_demo_catalog(self):
        core = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "cs_charm", "charms", "core")
        cat = C.Catalog().load(core_dir=core)
        self.assertEqual(len(cat.charms), 2)
        self.assertEqual(cat.report.warnings, [])
        for charm in cat.charms:
            self.assertEqual(charm.missing_files(), [], charm.name)
            self.assertTrue(charm.has_pattern(), charm.name)
            self.assertTrue(os.path.isfile(charm.icon), charm.name)


class ShadingTest(unittest.TestCase):
    def spec(self, shader, params=None, dynamic=None):
        return C.MaterialSpec("k", shader, {}, params or {}, dynamic or {})

    def test_weapon_values(self):
        spec = self.spec(C.SHADER_WEAPON,
                         {"F_ENABLE_ADJUSTMENTS": 1, "F_GLITTER": 1, "g_fHueShift": 10, "g_fGlitterIntensity": 0.25,
                          "g_vMetalnessRemapRange": [0.2, 0.7, 0, 0], "g_vColorTint": [1, 0.5, 0.25, 0],
                          "g_fGlitterScale": 4.0},
                         {"g_fHueShift": "return lerp(0,300,$KeychainSeed);"})
        values = S.node_values(spec, 50000)
        self.assertAlmostEqual(values[(S.NODE_MAIN, "Hue Shift")], 150.0)
        self.assertEqual(values[(S.NODE_MAIN, "Metal Min")], 0.2)
        self.assertEqual(values[(S.NODE_MAIN, "Metal Max")], 0.7)
        # sRGB parameters become linear socket values.
        for got, want in zip(values[(S.NODE_MAIN, "Color Tint")], (1.0, 0.2140, 0.0509, 1.0)):
            self.assertAlmostEqual(got, want, places=4)
        self.assertEqual(values[(S.NODE_MAIN, "Glitter Intensity")], 0.25)
        self.assertEqual(values[(S.NODE_GLITTER_UV, "Scale X")], 4.0)
        self.assertEqual(values[(S.NODE_MAIN, "Iridescence")], 0.0)  # F_IRIDESCENCE off

    def test_feature_switches(self):
        spec = self.spec(C.SHADER_WEAPON, {"g_fHueShift": 99, "g_fGlitterIntensity": 1.0})
        values = S.node_values(spec)
        self.assertEqual(values[(S.NODE_MAIN, "Hue Shift")], 0.0)
        self.assertEqual(values[(S.NODE_MAIN, "Glitter Intensity")], 0.0)

    def test_liquid_values(self):
        spec = self.spec(C.SHADER_LIQUID, {"g_vLiquidColor": [0.8, 0.078, 0.188, 0], "g_flLiquidLevelHeight": 0.761},
                         BUTANE_BUDDY)
        values = S.node_values(spec, 99999)
        self.assertAlmostEqual(values[(S.NODE_MAIN, "Liquid Hue Shift")], 319.9968, places=3)
        self.assertAlmostEqual(values[(S.NODE_MAIN, "Fill Level")], 0.79965, places=4)
        for got, want in zip(values[(S.NODE_MAIN, "Liquid Color")], (0.6038, 0.0069, 0.0295, 1.0)):
            self.assertAlmostEqual(got, want, places=4)
        summary = dict(S.pattern_summary(spec, 99999))
        self.assertEqual(set(summary), {"Liquid Hue", "Fill Level"})
        self.assertEqual(S.format_value("Fill Level", summary["Fill Level"]), "80 %")

    def test_liquid_geometry(self):
        # Butane Buddy: Source inches, Source Y -> Blender X.
        spec = self.spec(C.SHADER_LIQUID, {"g_flLiquidCenterOffset": [0.0, 0.6, -1.3, 0.0],
                                           "g_vLiquidLevelUpwardsMinMidMax": [-0.7, 0.1, 0.8, 0.0]})
        values = S.node_values(spec)
        for got, want in zip(values[(S.NODE_MAIN, "Liquid Center")], (0.01524, 0.0, -0.03302)):
            self.assertAlmostEqual(got, want, places=6)
        for got, want in zip(values[(S.NODE_MAIN, "Level Upright")], (-0.01778, 0.00254, 0.02032)):
            self.assertAlmostEqual(got, want, places=6)
        geo = S.liquid_geometry_from_bounds((-0.01, -0.01, -0.04), (0.01, 0.01, -0.01))
        self.assertEqual(set(geo), set(S.LIQUID_GEOMETRY_INPUTS))
        self.assertAlmostEqual(geo["Liquid Center"][2], -0.025)
        self.assertEqual(geo["Level Upright"], (-0.015, 0.0, 0.015))

    def test_detail_uv_vectors(self):
        spec = self.spec(C.SHADER_WEAPON, {"F_ENABLE_ADJUSTMENTS": 1}, {
            "g_vDetailTexCoordOffset": "return float2(frac($KeychainSeed*7),frac($KeychainSeed*13));",
            "g_vDetailTexCoordScale": "v0 = lerp(2,.95,$KeychainSeed*$KeychainSeed);\\nreturn float2(v0,v0);",
            "g_flDetailTexCoordRotation": "return frac($KeychainSeed*11)*360;",
        })
        values = S.node_values(spec, 10000)
        self.assertAlmostEqual(values[(S.NODE_DETAIL_UV, "Offset X")], 0.7)
        self.assertAlmostEqual(values[(S.NODE_DETAIL_UV, "Offset Y")], 0.3)
        self.assertAlmostEqual(values[(S.NODE_DETAIL_UV, "Rotation")], 0.1 * 360, places=4)
        self.assertAlmostEqual(values[(S.NODE_DETAIL_UV, "Scale X")], 2 - 1.05 * 0.01)


if __name__ == "__main__":
    unittest.main()
