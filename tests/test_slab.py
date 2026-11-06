# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Sticker Slab inside Blender, with the demo slab and the demo stickers
(tests/fixtures): sticker library, sticker layer, label color and text,
operators, duplicates and the synced finish groups."""

import json
import os
import sys
import unittest

import bpy

from cs_charm import utils
from cs_charm.library import patterns, registry, sticker_registry
from cs_charm.library import shading as S
from cs_charm.library import stickers as ST
from cs_charm.nodes import groups, slab
from cs_charm.nodes import material as M
from cs_charm.nodes import sticker_groups as SG
from cs_charm.ops import spawn

from test_blender import CharmTestCase

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SlabTestCase(CharmTestCase):
    def setUp(self):
        super().setUp()
        prefs = utils.get_prefs()
        prefs.sticker_path = ""
        sticker_registry.invalidate()
        self.slab_charm = self.catalog.get("demo_sticker_slab")
        self.lib = sticker_registry.get_library()
        self.paper = self.lib.get("demo_star")
        self.holo = self.lib.get("demo_star_holo")
        self.state = bpy.context.window_manager.cs_charm
        self.state.sticker_id = ""

    def spawn_slab(self, sticker, pattern=1337):
        self.state.sticker_id = sticker.id if sticker else ""
        obj, warnings = spawn.create_charm_object(bpy.context, self.slab_charm, pattern)
        return obj, warnings

    @staticmethod
    def slab_mat(obj):
        return slab.slab_materials(obj)[0]

    @staticmethod
    def evaluated(obj):
        bpy.context.view_layer.update()
        ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh = ev.to_mesh()
        data = ([v.co.copy() for v in mesh.vertices], [m.name for m in mesh.materials if m])
        ev.to_mesh_clear()
        return data


class StickerLibraryTest(SlabTestCase):
    def test_demo_stickers_and_slab(self):
        self.assertIsNotNone(self.slab_charm)
        self.assertTrue(slab.is_slab_charm(self.slab_charm))
        self.assertFalse(slab.is_slab_charm(self.gem))
        self.assertIn(utils.CORE_STICKER_DIR, utils.sticker_library_dirs())
        self.assertEqual(self.paper.label_text(), "Demo Star | cs.charm Demo 2026")
        self.assertEqual(self.holo.finish, "HOLO")
        self.assertEqual(self.holo.rarity, "mythical")

    def test_picker_list(self):
        sticker_registry.sync_items(self.state)
        self.assertGreaterEqual(len(self.state.sticker_items), 2)
        self.state.sticker_search = "holo"
        self.assertEqual([i.sticker_id for i in self.state.sticker_items], ["demo_star_holo"])
        self.state.sticker_index = 0
        self.assertEqual(self.state.sticker_id, "demo_star_holo")
        self.assertEqual(sticker_registry.selected_sticker(bpy.context).id, "demo_star_holo")
        self.state.sticker_search = ""
        self.state.sticker_finish = "PAPER"
        self.assertEqual([i.sticker_id for i in self.state.sticker_items], ["demo_star"])
        self.state.sticker_finish = "ALL"

    def test_thumbnail(self):
        # Picker icons as in cs.sticker: cut out, with a finish hint.
        import tempfile
        from cs_charm.library import sticker_thumbs as thumbs
        px = thumbs.compose(self.holo, 64)
        self.assertEqual(px.shape, (64, 64, 4))
        self.assertLess(px[..., 3].min(), 0.01)
        self.assertGreater(px[..., 3].max(), 0.99)
        plain = thumbs.compose(self.paper, 64)
        self.assertGreater(abs(px[..., :3] - plain[..., :3]).max(), 0.05)  # holo hint
        with tempfile.TemporaryDirectory() as root:
            path = thumbs.build(self.holo, os.path.join(root, "t.png"), 64)
            self.assertTrue(os.path.isfile(path))
        self.assertNotEqual(thumbs.cache_path(self.holo), thumbs.cache_path(self.paper))
        self.assertFalse([i for i in bpy.data.images if i.name.startswith(thumbs.TEMP_IMAGE)])
        # Drawing queues a missing thumbnail; the timer builds the cache file.
        cached = thumbs.cache_path(self.holo)
        if os.path.isfile(cached):
            os.remove(cached)
        sticker_registry.preview_icon(self.holo)  # base texture meanwhile (icon ids are 0 in -b)
        self.assertIn(self.holo, sticker_registry._thumb_queue)
        while sticker_registry._thumb_queue:
            sticker_registry._build_thumbs()
        self.assertTrue(os.path.isfile(cached))

    def test_selecting_slab_fills_picker(self):
        self.state.sticker_items.clear()
        sticker_registry.invalidate()
        self.state.search = "slab"
        self.state.index = 0
        self.assertGreaterEqual(len(self.state.sticker_items), 2)
        self.state.search = ""


class SlabSpawnTest(SlabTestCase):
    def test_spawn_with_sticker(self):
        obj, warnings = self.spawn_slab(self.holo)
        self.assertEqual(warnings, [])
        self.assertTrue(slab.is_slab(obj))
        self.assertIn(slab.STICKER_UV, obj.data.uv_layers)
        self.assertEqual(slab.sticker_of(obj).id, "demo_star_holo")
        mat = self.slab_mat(obj)
        nodes = mat.node_tree.nodes
        self.assertEqual(nodes[slab.NODE_STICKER].node_tree.name, SG.group_name("HOLO"))
        self.assertEqual(nodes["SLAB_UV"].uv_map, slab.STICKER_UV)
        self.assertTrue(nodes[slab.NODE_MIX].inputs[0].is_linked)
        self.assertEqual(nodes["SLAB_TEX_BASE"].extension, "CLIP")
        self.assertIn("SLAB_TEX_HOLOMASK", nodes)
        self.assertIn("SLAB_HOLO_SPECTRUM", nodes)  # no spectrum texture: procedural
        # Mix sits between the card and the glass.
        glass = nodes[S.NODE_GLASS]
        self.assertEqual(glass.inputs["Shader"].links[0].from_node.name, slab.NODE_MIX)
        self.assertTrue(glass.inputs["Refract Mask"].is_linked)
        self.assertEqual(mat.surface_render_method, "DITHERED")
        # Label frame in the rarity color (sRGB -> linear), only inside the tint mask.
        main = nodes[S.NODE_MAIN]
        r, g, b = ST.rarity_color("mythical")
        expected = [S.srgb_to_linear(c) for c in (r, g, b)]
        for got, want in zip(main.inputs["Color Tint"].default_value[:3], expected):
            self.assertAlmostEqual(got, want, places=4)
        self.assertTrue(main.inputs["Tint Mask"].is_linked)

    @staticmethod
    def label_input(obj, name):
        mod = slab.label_modifier(obj)
        key = slab._input_ids(mod.node_group)[name]
        props = getattr(mod, "properties", None)
        return getattr(props.inputs, key).value if props is not None else mod[key]

    def test_serial_is_kit_id(self):
        obj, _ = self.spawn_slab(self.paper, pattern=6666)
        self.assertEqual(self.label_input(obj, "Serial"), "0000002026")
        obj.cs_charm.pattern = 1  # the pattern does not touch the serial
        self.assertEqual(self.label_input(obj, "Serial"), "0000002026")
        spawn.select_only(bpy.context, obj)
        self.state.sticker_id = self.holo.id
        bpy.ops.cs_charm.set_sticker()
        self.assertEqual(self.label_input(obj, "Serial"), "0000002027")

    def test_label_text(self):
        obj, _ = self.spawn_slab(self.paper, pattern=6666)
        mod = slab.label_modifier(obj)
        self.assertIsNotNone(mod)
        self.assertEqual(mod.node_group.name, slab.LABEL_GROUP)
        plane = json.loads(obj.data[utils.PROP_LABEL])
        width = sum(c * c for c in plane["x"]) ** 0.5
        height = sum(c * c for c in plane["y"]) ** 0.5
        self.assertAlmostEqual(width / height, 488 / 101, delta=0.05)
        verts, mats = self.evaluated(obj)
        self.assertGreater(len(verts), len(obj.data.vertices))
        self.assertIn(slab.TEXT_MATERIAL, mats)
        self.assertIn(slab.SERIAL_MATERIAL, mats)
        # Text lies on the label: in front of it, inside its rectangle.
        text = verts[len(obj.data.vertices):]
        ox, oy, oz = plane["origin"]
        self.assertTrue(all(abs(v.x - ox - slab.LABEL_LIFT) < 1e-4 for v in text))
        self.assertTrue(all(oy - 1e-4 <= v.y <= oy + width + 1e-4 for v in text))
        self.assertTrue(all(oz - 1e-4 <= v.z <= oz + height + 1e-4 for v in text))
        count = len(text)
        obj.cs_charm.label_text = "A much longer custom label text that has to shrink | Somewhere 2099"
        verts, _ = self.evaluated(obj)
        longer = verts[len(obj.data.vertices):]
        self.assertGreater(len(longer), count)
        self.assertTrue(all(oy - 1e-4 <= v.y <= oy + width + 1e-4 for v in longer))  # Scale To Fit

    def test_settings_update(self):
        obj, _ = self.spawn_slab(self.paper)
        mat = self.slab_mat(obj)
        obj.cs_charm.sticker_wear = 0.4
        self.assertAlmostEqual(mat.node_tree.nodes[slab.NODE_WEAR].inputs["Wear"].default_value, 0.4)
        obj.cs_charm.label_color = (1.0, 0.0, 0.0)
        obj.cs_charm.use_label_color = True
        tint = mat.node_tree.nodes[S.NODE_MAIN].inputs["Color Tint"].default_value
        self.assertAlmostEqual(tint[0], 1.0, places=4)
        self.assertAlmostEqual(tint[1], 0.0, places=4)
        # Pattern changes keep the color (stored on the material).
        obj.cs_charm.pattern = 42
        tint = mat.node_tree.nodes[S.NODE_MAIN].inputs["Color Tint"].default_value
        self.assertAlmostEqual(tint[1], 0.0, places=4)
        self.assertEqual(M.material_env(mat)[slab.ENV_RARITY], (1.0, 0.0, 0.0))

    def test_without_sticker(self):
        obj, warnings = self.spawn_slab(None)
        self.assertEqual(len(warnings), 1)
        self.assertIsNone(slab.sticker_of(obj))
        mat = self.slab_mat(obj)
        self.assertNotIn(slab.NODE_STICKER, mat.node_tree.nodes)
        glass = mat.node_tree.nodes[S.NODE_GLASS]
        self.assertEqual(glass.inputs["Shader"].links[0].from_node.name, S.NODE_MAIN)
        # Tint without rarity color: white, like the game.
        tint = mat.node_tree.nodes[S.NODE_MAIN].inputs["Color Tint"].default_value
        self.assertAlmostEqual(tint[2], 1.0, places=4)

    def test_set_sticker_operator(self):
        obj, _ = self.spawn_slab(self.holo)
        spawn.select_only(bpy.context, obj)
        self.state.sticker_id = self.paper.id
        self.assertEqual(bpy.ops.cs_charm.set_sticker(), {"FINISHED"})
        mat = self.slab_mat(obj)
        self.assertEqual(mat.node_tree.nodes[slab.NODE_STICKER].node_tree.name, SG.group_name("PAPER"))
        self.assertNotIn("SLAB_TEX_HOLOMASK", mat.node_tree.nodes)
        self.assertEqual(slab.label_text(obj), self.paper.label_text())

    def test_rebuild_keeps_sticker(self):
        obj, _ = self.spawn_slab(self.holo)
        obj.cs_charm.sticker_wear = 0.3
        warnings = spawn.rebuild_materials(obj)
        self.assertEqual(warnings, [])
        mat = self.slab_mat(obj)
        self.assertEqual(mat.node_tree.nodes[slab.NODE_STICKER].node_tree.name, SG.group_name("HOLO"))
        self.assertAlmostEqual(mat.node_tree.nodes[slab.NODE_WEAR].inputs["Wear"].default_value, 0.3)

    def test_works_without_library(self):
        """Wear, color and text come from the object, not the library."""
        obj, _ = self.spawn_slab(self.paper)
        prefs = utils.get_prefs()
        prefs.sticker_path = os.path.join(ROOT, "does_not_exist")
        sticker_registry.invalidate()
        obj.cs_charm.label_text = ""
        obj.cs_charm.sticker_wear = 0.2
        self.assertEqual(slab.label_text(obj), self.paper.label_text())
        self.assertEqual(spawn.rebuild_materials(obj), [])
        self.assertIn(slab.NODE_STICKER, self.slab_mat(obj).node_tree.nodes)

    def test_duplicate_keeps_sticker(self):
        from cs_charm.ops import duplicates
        obj, _ = self.spawn_slab(self.holo)
        copy = obj.copy()
        copy.data = obj.data.copy()
        obj.users_collection[0].objects.link(copy)
        duplicates.make_unique(bpy.context)
        self.assertIsNot(self.slab_mat(copy), self.slab_mat(obj))
        self.assertEqual(slab.sticker_of(copy).id, self.holo.id)
        self.assertIsNotNone(slab.label_modifier(copy))
        copy.cs_charm.use_label_color = True
        copy.cs_charm.label_color = (0.0, 1.0, 0.0)
        tint = self.slab_mat(obj).node_tree.nodes[S.NODE_MAIN].inputs["Color Tint"].default_value
        self.assertLess(tint[1], 0.5)


class SlabNodesTest(unittest.TestCase):
    def test_glass_bindings(self):
        tree = groups.ensure_group("GLASS")
        names = {s.name for s in tree.interface.items_tree if getattr(s, "in_out", "") == "INPUT"}
        for b in S.GLASS_BINDINGS:
            self.assertIn(b.input, names)

    def test_finish_groups_build(self):
        for key in SG.FINISH_GROUP_KEYS:
            tree = SG.ensure_group(key)
            self.assertTrue(tree.name.startswith(SG.PREFIX), tree.name)
            self.assertEqual(tree.get(SG.VERSION_KEY), SG.GROUP_VERSION)
            inputs = {s.name for s in tree.interface.items_tree if getattr(s, "in_out", "") == "INPUT"}
            self.assertTrue({"Base Color", "Alpha", "Normal Color", "Wear", "Alpha Clip"} <= inputs, key)
            outputs = {s.name for s in tree.interface.items_tree if getattr(s, "in_out", "") == "OUTPUT"}
            self.assertEqual(outputs, {"Shader"})
        wear = SG.ensure_group("WEAR")
        self.assertIn("Alpha", {s.name for s in wear.interface.items_tree if getattr(s, "in_out", "") == "OUTPUT"})

    def test_rarity_env(self):
        dynamic = {"g_vColorTint": "return exists($sticker_rarity_color) ? $sticker_rarity_color : float3(1,1,1);"}
        values, _ = patterns.evaluate_dynamic(dynamic, 0)
        self.assertEqual(values, {})  # no seed, no item input: static value
        values, _ = patterns.evaluate_dynamic(dynamic, 0, env={slab.ENV_RARITY: (1.0, 0.5, 0.0)})
        self.assertEqual(values["g_vColorTint"], (1.0, 0.5, 0.0))


class SyncScriptTest(unittest.TestCase):
    def test_sticker_groups_up_to_date(self):
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import sync_sticker_nodes as sync
        src = os.path.join(sync.DEFAULT_SOURCE, sync.SOURCE_FILE)
        if not os.path.isfile(src):
            self.skipTest("cs.sticker repository not next to cs.charm")
        with open(src, encoding="utf-8") as fh:
            wanted = sync.transform(fh.read())
        with open(sync.TARGET, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), wanted, "run tools/sync_sticker_nodes.py")

    def test_transform_rules(self):
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import sync_sticker_nodes as sync
        text = '"""Doc."""\nGROUP_VERSION = 7\nVERSION_KEY = "cs_sticker_version"\n\nPREFIX = "CS2 "\n'
        out = sync.transform(text)
        self.assertIn('PREFIX = "CS2 Slab "', out)
        self.assertIn('VERSION_KEY = "cs_charm_sticker_version"', out)
        self.assertTrue(out.startswith('"""Generated by'))
        self.assertEqual(sync.source_version(out), 7)
        with self.assertRaises(ValueError):
            sync.transform('"""x"""\nPREFIX = "Other"\n')


if __name__ == "__main__":
    unittest.main()
