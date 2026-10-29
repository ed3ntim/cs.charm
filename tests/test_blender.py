# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Integration tests inside Blender: registration, spawning the demo charms,
materials and patterns, placement, attachment and physics."""

import math
import os
import unittest

import bpy
from mathutils import Vector

from cs_charm import utils
from cs_charm.library import registry
from cs_charm.library import shading as S
from cs_charm.nodes import groups
from cs_charm.nodes import material as M
from cs_charm.ops import physics
from cs_charm.ops import placement as P
from cs_charm.ops import spawn


def _clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for block in list(coll):
            if block.users == 0:
                coll.remove(block)
    spawn._templates.clear()
    scene = bpy.context.scene
    if scene.rigidbody_world is not None:
        bpy.ops.rigidbody.world_remove()


def _cube(name="Target", size=1.0, location=(0, 0, 0)):
    mesh = bpy.data.meshes.new(name)
    half = size / 2
    verts = [(x, y, z) for x in (-half, half) for y in (-half, half) for z in (-half, half)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    bpy.context.view_layer.update()
    return obj


class CharmTestCase(unittest.TestCase):
    def setUp(self):
        _clear_scene()
        registry.refresh(bpy.context)
        self.catalog = registry.get_catalog()
        self.gem = self.catalog.get("demo_gem_drop")
        self.flask = self.catalog.get("demo_fuel_flask")
        self.settings = bpy.context.scene.cs_charm_place
        bpy.ops.cs_charm.reset_placement()

    def spawn(self, charm, pattern=0):
        obj, warnings = spawn.create_charm_object(bpy.context, charm, pattern)
        self.assertEqual(warnings, [])
        return obj


class RegistrationTest(CharmTestCase):
    def test_registered(self):
        self.assertTrue(hasattr(bpy.types.Object, "cs_charm"))
        self.assertTrue(hasattr(bpy.types.Scene, "cs_charm_place"))
        for op in ("place_interactive", "spawn_on_selected", "spawn_at_cursor", "add_physics", "attach"):
            self.assertTrue(hasattr(bpy.ops.cs_charm, op), op)
        for panel in ("CSCHARM_PT_library", "CSCHARM_PT_placement", "CSCHARM_PT_active"):
            self.assertTrue(hasattr(bpy.types, panel), panel)

    def test_library_list(self):
        state = bpy.context.window_manager.cs_charm
        self.assertGreaterEqual(len(state.items), 2)
        state.search = "flask"
        self.assertEqual([i.name for i in state.items], ["Demo Fuel Flask"])
        self.assertTrue(state.items[0].has_pattern)
        state.search = ""
        state.filter_rarity = "mythical"
        self.assertEqual([i.name for i in state.items], ["Demo Gem Drop"])
        state.filter_rarity = "ALL"

    def test_node_groups(self):
        for tree in groups.ensure_all():
            self.assertEqual(tree.get(groups.VERSION_KEY), groups.GROUP_VERSION)
        # Every bound input exists on its group.
        node_groups = {S.NODE_MAIN: None, S.NODE_DETAIL_UV: groups.ensure_group("UV"),
                       S.NODE_GLITTER_UV: groups.ensure_group("UV")}
        for shader, key in ((None, "WEAPON"), ("csgo_simple_liquid.vfx", "LIQUID")):
            tree = groups.ensure_group(key)
            names = {s.name for s in tree.interface.items_tree if getattr(s, "in_out", "") == "INPUT"}
            for b in S.bindings(shader or ""):
                if b.node == S.NODE_MAIN:
                    self.assertIn(b.input, names, f"{key}: {b.input}")
                else:
                    uv = {s.name for s in node_groups[b.node].interface.items_tree
                          if getattr(s, "in_out", "") == "INPUT"}
                    self.assertIn(b.input, uv)


class SpawnTest(CharmTestCase):
    def test_spawn_gem(self):
        obj = self.spawn(self.gem, pattern=50000)
        self.assertTrue(utils.is_charm(obj))
        self.assertEqual(obj.cs_charm.pattern, 50000)
        self.assertAlmostEqual(obj.cs_charm.base_height, 0.0337, delta=0.004)
        # Attachment point at the origin, charm hangs down.
        zs = [v.co.z for v in obj.data.vertices]
        self.assertAlmostEqual(max(zs), 0.0, delta=0.0015)
        self.assertLess(min(zs), -0.02)
        mats = [m for m in obj.data.materials]
        self.assertEqual(len(mats), 2)
        for mat in mats:
            self.assertTrue(M.is_charm_material(mat), mat.name)
        gem_mat = next(m for m in mats if "gem" in m.name)
        main = M.main_node(gem_mat)
        self.assertEqual(main.node_tree.name, groups.WEAPON_GROUP)
        self.assertAlmostEqual(main.inputs["Hue Shift"].default_value, 0.0, places=4)  # lerp(-150,150,.5)
        self.assertAlmostEqual(main.inputs["Glitter Intensity"].default_value, 0.35, places=5)
        # Packed metal map is wired to the Metal Pack input (R rough, G metal).
        self.assertTrue(main.inputs["Metal Pack"].is_linked)
        self.assertTrue(main.inputs["Tint Mask"].is_linked)
        glitter = gem_mat.node_tree.nodes["TEX_GLITTER"]
        self.assertEqual(glitter.inputs["Vector"].links[0].from_node.name, S.NODE_GLITTER_UV)
        self.assertEqual(glitter.image.colorspace_settings.name, "Non-Color")
        color = gem_mat.node_tree.nodes["TEX_COLOR"]
        self.assertEqual(color.image.colorspace_settings.name, "sRGB")

    def test_pattern_update(self):
        obj = self.spawn(self.gem)
        gem_mat = next(m for m in obj.data.materials if "gem" in m.name)
        hue = M.main_node(gem_mat).inputs["Hue Shift"]
        self.assertAlmostEqual(hue.default_value, -150.0, places=3)
        obj.cs_charm.pattern = 100000
        self.assertAlmostEqual(hue.default_value, 150.0, places=3)
        sat = M.main_node(gem_mat).inputs["Saturation"]
        self.assertAlmostEqual(sat.default_value, 1.6, places=4)

    def test_liquid(self):
        obj = self.spawn(self.flask, pattern=12345)
        flask_mat = next(m for m in obj.data.materials if "flask" in m.name)
        main = M.main_node(flask_mat)
        self.assertEqual(main.node_tree.name, groups.LIQUID_GROUP)
        self.assertAlmostEqual(main.inputs["Liquid Hue Shift"].default_value, 39.504, places=3)
        self.assertAlmostEqual(main.inputs["Fill Level"].default_value, 0.57075, places=4)
        bottom, top = main.inputs["Bottom"].default_value, main.inputs["Top"].default_value
        self.assertLess(bottom, top)
        self.assertAlmostEqual(top - bottom, 0.026, delta=0.002)
        self.assertTrue(main.inputs["Color Alpha"].is_linked)
        self.assertEqual(flask_mat.node_tree.nodes["TEX_COLOR"].image.alpha_mode, "CHANNEL_PACKED")
        obj.cs_charm.pattern = 345  # same fill level every 1000 patterns
        self.assertAlmostEqual(main.inputs["Fill Level"].default_value, 0.57075, places=4)

    def test_template_reuse_and_unique_materials(self):
        a = self.spawn(self.gem, 1)
        meshes = len(bpy.data.meshes)
        b = self.spawn(self.gem, 2)
        self.assertEqual(len(bpy.data.meshes), meshes + 1)  # copy, no re-import
        self.assertNotEqual(a.data, b.data)
        self.assertTrue(set(a.data.materials).isdisjoint(set(b.data.materials)))
        # Importer leftovers are cleaned up.
        self.assertFalse([m for m in bpy.data.materials if m.users == 0 and not M.is_charm_material(m)])

    def test_pattern_without_library(self):
        obj = self.spawn(self.gem)
        obj[utils.PROP_CHARM_ID] = "not_in_library"
        obj.cs_charm.pattern = 100000  # spec stored on the material
        gem_mat = next(m for m in obj.data.materials if "gem" in m.name)
        self.assertAlmostEqual(M.main_node(gem_mat).inputs["Hue Shift"].default_value, 150.0, places=3)

    def test_reset_materials(self):
        obj = self.spawn(self.gem, 100000)
        gem_mat = next(m for m in obj.data.materials if "gem" in m.name)
        M.main_node(gem_mat).inputs["Glitter Intensity"].default_value = 3.0
        spawn.rebuild_materials(obj)
        gem_mat = next(m for m in obj.data.materials if "gem" in m.name)
        self.assertAlmostEqual(M.main_node(gem_mat).inputs["Glitter Intensity"].default_value, 0.35, places=5)
        self.assertAlmostEqual(M.main_node(gem_mat).inputs["Hue Shift"].default_value, 150.0, places=3)

    def test_fallback_pbr_for_plain_gltf(self):
        # A charm without catalog specs keeps the importer's material.
        from cs_charm.library import catalog as C
        plain = C.Charm(id="plain", name="Plain", collection="User", model=self.gem.model)
        obj, warnings = spawn.create_charm_object(bpy.context, plain)
        self.assertEqual(warnings, [])
        self.assertTrue(all(m is not None and not M.is_charm_material(m) for m in obj.data.materials))


class PlacementTest(CharmTestCase):
    def test_orientation_hang(self):
        m = P.orientation_matrix(Vector((1, 2, 3)), Vector((0, -1, 0)), "HANG")
        self.assertAlmostEqual((m.to_3x3() @ Vector((0, 0, 1)) - Vector((0, 0, 1))).length, 0.0, places=6)
        # Face (+X) looks along the surface normal.
        self.assertAlmostEqual((m.to_3x3() @ Vector((1, 0, 0)) - Vector((0, -1, 0))).length, 0.0, places=6)
        self.assertEqual(m.translation, Vector((1, 2, 3)))

    def test_orientation_surface_and_scale(self):
        m = P.orientation_matrix(Vector(), Vector((1, 0, 0)), "SURFACE", scale=2.0)
        down = m.to_3x3() @ Vector((0, 0, -1))
        self.assertAlmostEqual((down.normalized() - Vector((1, 0, 0))).length, 0.0, places=6)
        self.assertAlmostEqual(down.length, 2.0, places=6)

    def test_spawn_on_selected_parent(self):
        target = _cube(location=(0, 0, 0))
        bpy.context.view_layer.objects.active = target
        target.select_set(True)
        bpy.context.scene.cursor.location = (0, -3, 0)
        self.settings.attach = "PARENT"
        self.assertEqual(bpy.ops.cs_charm.spawn_on_selected(), {"FINISHED"})
        obj = bpy.context.active_object
        self.assertTrue(utils.is_charm(obj))
        self.assertEqual(obj.parent, target)
        self.assertEqual(obj.cs_charm.target, target)
        loc = obj.matrix_world.translation.copy()
        self.assertAlmostEqual(loc.y, -0.5, places=4)  # on the -Y face
        # Moving the target moves the charm.
        target.location.x += 2.0
        bpy.context.view_layer.update()
        self.assertAlmostEqual(obj.matrix_world.translation.x, loc.x + 2.0, places=4)

    def test_child_of_and_edit(self):
        target = _cube(location=(0, 0, 0))
        obj = self.spawn(self.gem)
        self.settings.attach = "CHILD_OF"
        P.place(obj, Vector((0, -0.5, 0)), Vector((0, -1, 0)), self.settings, target)
        bpy.context.view_layer.update()
        self.assertIsNone(obj.parent)
        self.assertEqual(obj.constraints[0].type, "CHILD_OF")
        self.assertAlmostEqual((obj.matrix_world.translation - Vector((0, -0.5, 0))).length, 0.0, places=4)
        target.location.z = 1.0
        bpy.context.view_layer.update()
        self.assertAlmostEqual(obj.matrix_world.translation.z, 1.0, places=4)
        # Editing the placement keeps the charm on the (moved) target.
        obj.cs_charm.offset = 100.0
        bpy.context.view_layer.update()
        expected = Vector((0, -0.5 - obj.cs_charm.base_height, 1.0))
        self.assertAlmostEqual((obj.matrix_world.translation - expected).length, 0.0, places=4)
        obj.cs_charm.rotation = math.radians(90)
        obj.cs_charm.scale = 2.0
        bpy.context.view_layer.update()
        self.assertAlmostEqual(obj.matrix_world.to_scale().x, 2.0, places=4)

    def test_relative_size(self):
        target = _cube(size=2.0)
        obj = self.spawn(self.gem)
        self.settings.size_mode = "RELATIVE"
        self.settings.size_relative = 10.0
        P.place(obj, Vector((0, -1, 0)), Vector((0, -1, 0)), self.settings, target)
        self.assertAlmostEqual(obj.cs_charm.scale * obj.cs_charm.base_height, 0.2, places=5)

    def test_spawn_at_cursor_manual(self):
        bpy.context.scene.cursor.location = (1, 1, 1)
        for o in bpy.context.selected_objects:
            o.select_set(False)
        self.assertEqual(bpy.ops.cs_charm.spawn_at_cursor(), {"FINISHED"})
        obj = bpy.context.active_object
        self.assertEqual(obj.cs_charm.attach, "NONE")
        self.assertAlmostEqual((obj.matrix_world.translation - Vector((1, 1, 1))).length, 0.0, places=5)

    def test_attach_detach_operators(self):
        target = _cube()
        obj = self.spawn(self.gem)
        P.place(obj, Vector((0, -0.5, 0)), Vector((0, -1, 0)), self.settings)
        for o in bpy.context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        target.select_set(True)
        bpy.context.view_layer.objects.active = target
        self.assertEqual(bpy.ops.cs_charm.attach(mode="CHILD_OF"), {"FINISHED"})
        self.assertEqual(obj.cs_charm.attach, "CHILD_OF")
        bpy.context.view_layer.objects.active = obj
        self.assertEqual(bpy.ops.cs_charm.detach(), {"FINISHED"})
        self.assertEqual(obj.cs_charm.attach, "NONE")
        self.assertEqual(len(obj.constraints), 0)
        self.assertAlmostEqual((obj.matrix_world.translation - Vector((0, -0.5, 0))).length, 0.0, places=4)


class PhysicsTest(CharmTestCase):
    def test_add_simulate_remove(self):
        scene = bpy.context.scene
        target = _cube()
        obj = self.spawn(self.flask)
        self.settings.attach = "PARENT"
        P.place(obj, Vector((0, -0.5, 0)), Vector((0, -1, 0)), self.settings, target)
        obj.cs_charm.lean = math.radians(40)  # start swinging
        bpy.context.view_layer.update()
        physics.add_physics(bpy.context, obj)
        self.assertTrue(obj.cs_charm.physics)
        self.assertIsNotNone(obj.rigid_body)
        self.assertIsNone(obj.parent)
        anchor = obj.cs_charm.physics_anchor
        pivot = obj.cs_charm.physics_pivot
        self.assertEqual(anchor.parent, target)
        self.assertTrue(anchor.rigid_body.kinematic)
        self.assertEqual(pivot.rigid_body_constraint.type, "POINT")
        self.assertEqual(pivot.rigid_body_constraint.object2, obj)
        self.assertIsNone(target.rigid_body_constraint)  # not on whatever was active

        start = obj.matrix_world.translation.copy()
        scene.frame_set(scene.frame_start)
        for f in range(scene.frame_start, scene.frame_start + 20):
            scene.frame_set(f)
        moved = obj.matrix_world.copy()
        # It swung, but the attachment point stayed put.
        self.assertGreater((moved.to_3x3() @ Vector((0, 0, 1)) - Vector((0, 0, 1))).length, 1e-3)
        self.assertLess((moved.translation - start).length, 0.002)
        scene.frame_set(scene.frame_start)

        physics.remove_physics(bpy.context, obj)
        self.assertFalse(obj.cs_charm.physics)
        self.assertIsNone(obj.rigid_body)
        self.assertEqual(obj.parent, target)
        self.assertNotIn(anchor, list(bpy.data.objects))

    def test_delete_charm(self):
        obj = self.spawn(self.gem)
        P.place(obj, Vector(), Vector((0, -1, 0)), self.settings)
        physics.add_physics(bpy.context, obj)
        helpers = [obj.cs_charm.physics_anchor.name, obj.cs_charm.physics_pivot.name]
        physics.delete_charm(bpy.context, obj)
        for name in helpers:
            self.assertNotIn(name, bpy.data.objects)


class BuildZipTest(unittest.TestCase):
    def test_zip_contents(self):
        import sys
        import zipfile
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, os.path.join(root, "tools"))
        import build_zip
        path = build_zip.main()
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
        self.assertIn("cs_charm/blender_manifest.toml", names)
        self.assertIn("cs_charm/LICENSE.md", names)
        self.assertIn("cs_charm/charms/core/catalog.json", names)
        self.assertFalse([n for n in names if "__pycache__" in n or n.startswith("cs_charm/charms/bundled")])
        self.assertFalse([n for n in names if not n.startswith("cs_charm/")])
