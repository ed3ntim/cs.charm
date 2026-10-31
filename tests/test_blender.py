# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Integration tests inside Blender: registration, spawning the demo charms,
materials and patterns, placement, attachment and physics."""

import math
import os
import unittest

import bpy
from mathutils import Matrix, Vector

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


def _lifted(obj, point, normal):
    """Charm origin for a surface point: lifted by the model's back depth."""
    return Vector(point) + Vector(normal) * P.back_depth(obj) * obj.cs_charm.scale


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
        # No CS2 level values: the level spans the container's bounding box.
        upright = main.inputs["Level Upright"].default_value
        self.assertAlmostEqual(upright[0], -upright[2], places=6)
        self.assertAlmostEqual(upright[2] - upright[0], 0.026, delta=0.002)
        self.assertLess(main.inputs["Liquid Center"].default_value[2], 0.0)
        if hasattr(flask_mat, "surface_render_method"):
            self.assertEqual(flask_mat.surface_render_method, "DITHERED")
        # The level follows world up: the group reads it through a vector transform.
        vt = [n for n in main.node_tree.nodes if n.bl_idname == "ShaderNodeVectorTransform"]
        self.assertEqual([(n.convert_from, n.convert_to) for n in vt], [("WORLD", "OBJECT")])
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

    def test_orientation_rest_on_top(self):
        m = P.orientation_matrix(Vector(), Vector((0, 0, 1)), "HANG", rest_dir=Vector((1, 0, 0)))
        r = m.to_3x3()
        # Face up, lying toward the rest direction.
        self.assertAlmostEqual((r @ Vector((1, 0, 0)) - Vector((0, 0, 1))).length, 0.0, places=6)
        self.assertAlmostEqual((r @ Vector((0, 0, -1)) - Vector((1, 0, 0))).length, 0.0, places=6)
        # Rotation turns it around the normal.
        r = P.orientation_matrix(Vector(), Vector((0, 0, 1)), "HANG", math.radians(90),
                                 rest_dir=Vector((1, 0, 0))).to_3x3()
        self.assertAlmostEqual((r @ Vector((0, 0, -1)) - Vector((0, 1, 0))).length, 0.0, places=6)

    def test_orientation_rest_on_slope_and_wall_continuity(self):
        n = Vector((0, -0.5, 0.866)).normalized()
        down = P.orientation_matrix(Vector(), n, "HANG", rest_dir=Vector((1, 0, 0))).to_3x3() @ Vector((0, 0, -1))
        self.assertAlmostEqual(down.dot(n), 0.0, places=6)  # lies on the slope
        self.assertLess(down.z, -0.4)                        # pointing downhill
        self.assertLess(down.y, -0.7)
        wall = P.orientation_matrix(Vector(), Vector((0, -1, 0)), "HANG").to_3x3()
        steep = P.orientation_matrix(Vector(), Vector((0, -1, 0.06)).normalized(), "HANG").to_3x3()
        for axis in (Vector((1, 0, 0)), Vector((0, 0, 1))):
            self.assertLess((wall @ axis - steep @ axis).length, 0.1)

    def _world_coords(self, obj):
        bpy.context.view_layer.update()
        return [obj.matrix_world @ v.co for v in obj.data.vertices]

    def _tol(self, obj):
        # The rest solver allows a contact tolerance of a fraction of the size.
        return 0.005 * obj.cs_charm.base_height * obj.cs_charm.scale

    def test_no_clipping_on_top_and_side(self):
        target = _cube(size=1.0)
        self.settings.attach = "PARENT"
        top = self.spawn(self.gem)
        P.place(top, Vector((0.2, 0, 0.5)), Vector((0, 0, 1)), self.settings, target)
        self.assertGreaterEqual(min(c.z for c in self._world_coords(top)), 0.5 - self._tol(top))
        # On a flat top it lies flat, toward the target's center.
        down = top.matrix_world.to_3x3() @ Vector((0, 0, -1))
        self.assertLess(down.x, -0.9)
        self.assertAlmostEqual(down.z, 0.0, delta=0.08)
        side = self.spawn(self.gem)
        P.place(side, Vector((0, -0.5, 0)), Vector((0, -1, 0)), self.settings, target)
        self.assertLessEqual(max(c.y for c in self._world_coords(side)), -0.5 + self._tol(side))
        # Free to hang: straight down as before.
        down = side.matrix_world.to_3x3() @ Vector((0, 0, -1))
        self.assertLess((down.normalized() - Vector((0, 0, -1))).length, 0.05)

    def test_rests_on_sphere(self):
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.05, segments=48, ring_count=24, location=(0, 0, 0))
        sphere = bpy.context.active_object
        self.settings.attach = "PARENT"
        obj = self.spawn(self.gem)
        P.place(obj, Vector((0, 0, 0.05)), Vector((0, 0, 1)), self.settings, sphere)
        coords = self._world_coords(obj)
        self.assertGreaterEqual(min(c.length for c in coords), 0.05 - self._tol(obj) - 0.0005)
        # It follows the curvature down instead of sticking out flat: this
        # 3 cm charm touches a 5 cm sphere about 9 degrees below horizontal.
        down = obj.matrix_world.to_3x3() @ Vector((0, 0, -1))
        self.assertLess(down.normalized().z, -0.12)

    def test_hangs_over_edge(self):
        target = _cube(size=1.0)
        self.settings.attach = "PARENT"
        obj = self.spawn(self.gem)
        scale = obj.cs_charm.scale
        P.place(obj, Vector((0.5 - 0.002 * scale, 0, 0.5)), Vector((0, 0, 1)), self.settings, target)
        # It tips over the edge (about 45 degrees: the rigid charm's back
        # rests on the edge, it cannot hang straight down from a pivot on top).
        down = obj.matrix_world.to_3x3() @ Vector((0, 0, -1))
        self.assertLess(down.normalized().z, -0.5)
        self.assertGreater(down.x, 0.5)
        coords = [c for c in self._world_coords(obj) if c.x < 0.5]
        self.assertGreaterEqual(min(c.z for c in coords), 0.5 - self._tol(obj))

    def test_rest_off_uses_normal_only(self):
        target = _cube(size=1.0)
        self.settings.attach = "PARENT"
        self.settings.rest_on_surface = False
        obj = self.spawn(self.gem)
        P.place(obj, Vector((0.2, 0, 0.5)), Vector((0, 0, 1)), self.settings, target)
        self.assertEqual(obj.cs_charm.rest_key, "")
        self.assertFalse(obj.cs_charm.rest_on_surface)

    def test_operators_act_on_active_only(self):
        a, b = self.spawn(self.gem, 5), self.spawn(self.gem, 6)
        for o in (a, b):
            P.place(o, Vector(), Vector((0, -1, 0)), self.settings)
            o.select_set(True)
        bpy.context.view_layer.objects.active = b
        bpy.ops.cs_charm.randomize_pattern()
        self.assertEqual(a.cs_charm.pattern, 5)
        bpy.ops.cs_charm.add_physics()
        self.assertFalse(a.cs_charm.physics)
        self.assertTrue(b.cs_charm.physics)
        bpy.ops.cs_charm.delete()
        self.assertIn(a, list(bpy.data.objects))
        self.assertNotIn("b", [o.name for o in bpy.data.objects if o == a])

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
        self.assertAlmostEqual(loc.y, _lifted(obj, (0, -0.5, 0), (0, -1, 0)).y, places=4)  # on the -Y face
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
        self.assertAlmostEqual((obj.matrix_world.translation - _lifted(obj, (0, -0.5, 0), (0, -1, 0))).length, 0.0,
                               places=4)
        target.location.z = 1.0
        bpy.context.view_layer.update()
        self.assertAlmostEqual(obj.matrix_world.translation.z, 1.0, places=4)
        # Editing the placement keeps the charm on the (moved) target.
        obj.cs_charm.offset = 100.0
        bpy.context.view_layer.update()
        expected = _lifted(obj, (0, -0.5 - obj.cs_charm.base_height, 1.0), (0, -1, 0))
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
        self.assertAlmostEqual((obj.matrix_world.translation - _lifted(obj, (1, 1, 1), (0, -1, 0))).length, 0.0,
                               places=5)

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
        self.assertAlmostEqual((obj.matrix_world.translation - _lifted(obj, (0, -0.5, 0), (0, -1, 0))).length, 0.0,
                               places=4)


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
        con = pivot.rigid_body_constraint
        self.assertEqual(con.type, "GENERIC_SPRING")
        self.assertTrue(all(getattr(con, f"use_limit_lin_{a}") for a in "xyz"))
        self.assertFalse(con.use_spring_ang_x or con.use_spring_ang_y)  # swings freely
        self.assertTrue(con.use_spring_ang_z)
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

    def test_gravity_swings_back(self):
        # The origin (center of mass for Bullet) is the attachment point:
        # without the weight a tilted charm would stay tilted.
        scene = bpy.context.scene
        target = _cube()
        obj = self.spawn(self.flask)
        self.settings.attach = "PARENT"
        P.place(obj, Vector((0, -0.5, 0)), Vector((0, -1, 0)), self.settings, target)
        obj.cs_charm.lean = math.radians(40)
        obj.cs_charm.physics_collide = False
        bpy.context.view_layer.update()
        physics.add_physics(bpy.context, obj)

        def tilt():
            up = obj.matrix_world.to_3x3() @ Vector((0, 0, 1))
            return math.degrees(up.angle(Vector((0, 0, 1))))

        scene.frame_set(scene.frame_start)
        start = tilt()
        least = start
        for f in range(scene.frame_start, scene.frame_start + 30):
            scene.frame_set(f)
            least = min(least, tilt())
        scene.frame_set(scene.frame_start)
        self.assertGreater(start, 30)
        self.assertLess(least, 0.7 * start)  # without the weight it stays at the start

    def _steps(self, obj, frames):
        scene = bpy.context.scene
        scene.frame_set(scene.frame_start)
        prev, steps = obj.matrix_world.to_quaternion(), []
        for f in range(scene.frame_start + 1, scene.frame_start + frames):
            scene.frame_set(f)
            q = obj.matrix_world.to_quaternion()
            steps.append(math.degrees(prev.rotation_difference(q).angle))
            prev = q
        scene.frame_set(scene.frame_start)
        return steps

    def _resting_flask(self, settle):
        target = _cube(size=1.0)
        self.settings.attach = "PARENT"
        obj = self.spawn(self.gem)
        # On the cube's edge: the charm rests on the top and hangs over it.
        P.place(obj, Vector((0.0, -0.49, 0.5)), Vector((0, -0.3, 1)).normalized(), self.settings, target)
        start = bpy.context.scene.frame_start
        target.keyframe_insert("location", frame=start)
        target.location.z = 0.2
        target.keyframe_insert("location", frame=start + 200)  # slow: hardly moves in 15 frames
        bpy.context.scene.frame_set(start)
        bpy.context.view_layer.update()
        physics.add_physics(bpy.context, obj, settle=settle)
        return obj

    def test_starts_at_rest(self):
        obj = self._resting_flask(settle=True)
        self.assertLess(max(self._steps(obj, 15)), 0.5)
        # The animation frozen while settling is back.
        target = obj.cs_charm.target
        self.assertIsNotNone(target.animation_data.action)
        bpy.context.scene.frame_set(bpy.context.scene.frame_start + 200)
        self.assertAlmostEqual(target.location.z, 0.2, places=4)
        bpy.context.scene.frame_set(bpy.context.scene.frame_start)

    def test_weight_carries_the_body(self):
        target = _cube(size=1.0)
        self.settings.attach = "PARENT"
        obj = self.spawn(self.gem)
        P.place(obj, Vector((0.2, 0, 0.5)), Vector((0, 0, 1)), self.settings, target)
        physics.add_physics(bpy.context, obj)
        weight = obj.cs_charm.physics_weight
        self.assertIsNotNone(weight)
        self.assertGreater(weight.rigid_body.mass, obj.rigid_body.mass)
        con = weight.rigid_body_constraint
        self.assertEqual(con.type, "FIXED")
        self.assertEqual({con.object1, con.object2}, {obj, weight})
        # The body collides in place of the charm.
        self.assertEqual(weight.rigid_body.collision_shape, "CONVEX_HULL")
        self.assertTrue(weight.rigid_body.collision_collections[0])
        self.assertFalse(obj.rigid_body.collision_collections[0])
        # On the hanging axis (model Z), where the rest pose expects it.
        local = obj.matrix_world.inverted() @ weight.matrix_world.translation
        self.assertLess(Vector((local.x, local.y)).length, 1e-5)
        self.assertLess(local.z, 0.0)
        name, mesh = weight.name, weight.data.name
        physics.remove_physics(bpy.context, obj)
        self.assertNotIn(name, bpy.data.objects)
        self.assertNotIn(mesh, bpy.data.meshes)
        self.assertEqual(obj.rigid_body, None)

    def test_body_leaves_out_ring(self):
        # Ring part around the attachment point, body part further down.
        import bmesh
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=0.004)
        ring = list(bm.verts)
        bmesh.ops.create_cube(bm, size=0.02, matrix=Matrix.Translation((0, 0, -0.03)))
        mesh = bpy.data.meshes.new("Two Parts")
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new("Two Parts", mesh)
        bpy.context.collection.objects.link(obj)
        body = physics._body_mesh(obj)
        center = physics._local_center(obj)
        lowest_ring = min(v.co.z for v in mesh.vertices[:len(ring)])
        self.assertEqual(len(body.vertices), 8)
        self.assertTrue(all(v.co.z + center.z < lowest_ring for v in body.vertices))
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(body)
        bpy.data.meshes.remove(mesh)

    def test_world_time_scale(self):
        scene = bpy.context.scene
        if scene.rigidbody_world is not None:
            bpy.ops.rigidbody.world_remove()
        world = physics.ensure_world(bpy.context, 4.0)
        self.assertAlmostEqual(world.time_scale, 2.0, places=5)
        self.assertGreaterEqual(world.solver_iterations, 60)
        world.time_scale = 1.5  # an existing world is left as it is
        self.assertAlmostEqual(physics.ensure_world(bpy.context, 39.37).time_scale, 1.5, places=5)

    def test_delete_charm(self):
        obj = self.spawn(self.gem)
        P.place(obj, Vector(), Vector((0, -1, 0)), self.settings)
        physics.add_physics(bpy.context, obj)
        helpers = [obj.cs_charm.physics_anchor.name, obj.cs_charm.physics_pivot.name,
                   obj.cs_charm.physics_weight.name]
        physics.delete_charm(bpy.context, obj)
        for name in helpers:
            self.assertNotIn(name, bpy.data.objects)


    def test_collides_with_animated_target(self):
        scene = bpy.context.scene
        target = _cube(size=1.0)
        self.settings.attach = "PARENT"
        obj = self.spawn(self.gem)
        P.place(obj, Vector((0.2, 0, 0.5)), Vector((0, 0, 1)), self.settings, target)
        physics.add_physics(bpy.context, obj)
        collider = obj.cs_charm.physics_collider
        self.assertIsNotNone(collider)
        self.assertEqual(collider.parent, target)
        self.assertEqual(collider.data, target.data)
        self.assertEqual(collider.rigid_body.collision_shape, "MESH")
        self.assertTrue(collider.rigid_body.kinematic)
        self.assertIsNone(target.rigid_body)
        # Tip the weapon: without the collider the charm would swing down
        # through it.
        start = scene.frame_start
        target.rotation_euler = (0, 0, 0)
        target.keyframe_insert("rotation_euler", frame=start)
        target.rotation_euler = (math.radians(25), 0, 0)
        target.keyframe_insert("rotation_euler", frame=start + 20)
        depth = 0.0
        for f in range(start, start + 40):
            scene.frame_set(f)
            inv = target.matrix_world.inverted()
            for v in obj.data.vertices:
                p = inv @ (obj.matrix_world @ v.co)
                if abs(p.x) < 0.5 and abs(p.y) < 0.5:
                    depth = max(depth, 0.5 - p.z)
        scene.frame_set(start)
        self.assertLess(depth, 0.1 * obj.cs_charm.base_height)
        # A second charm shares the collider; it goes with the last one.
        other = self.spawn(self.gem)
        P.place(other, Vector((-0.2, 0, 0.5)), Vector((0, 0, 1)), self.settings, target)
        physics.add_physics(bpy.context, other)
        self.assertEqual(other.cs_charm.physics_collider, collider)
        physics.remove_physics(bpy.context, obj)
        self.assertIn(collider, list(bpy.data.objects))
        name = collider.name
        physics.delete_charm(bpy.context, other)
        self.assertNotIn(name, bpy.data.objects)
        self.assertIn(target.data, list(bpy.data.meshes))

    def test_no_collider_when_off(self):
        target = _cube(size=1.0)
        self.settings.attach = "PARENT"
        obj = self.spawn(self.gem)
        P.place(obj, Vector((0, -0.5, 0)), Vector((0, -1, 0)), self.settings, target)
        obj.cs_charm.physics_collide = False
        physics.add_physics(bpy.context, obj)
        self.assertIsNone(obj.cs_charm.physics_collider)

    def _placed_mid_animation(self, nla):
        """Charm placed at frame 50 on a target that moves 2 m from the
        first frame on (#20: it started where the target was at frame 50
        and was pulled across the scene, or vanished right away with NLA)."""
        scene = bpy.context.scene
        start = scene.frame_start
        target = _cube(size=1.0)
        target.keyframe_insert("location", frame=start)
        target.location.x = 2.0
        target.keyframe_insert("location", frame=start + 100)
        if nla:
            ad = target.animation_data
            ad.nla_tracks.new().strips.new("move", start, ad.action)
            ad.action = None
        scene.frame_set(start + 49)
        self.settings.attach = "PARENT"
        obj = self.spawn(self.flask)
        x = target.matrix_world.translation.x
        P.place(obj, Vector((x, -0.5, 0)), Vector((0, -1, 0)), self.settings, target)
        bpy.context.view_layer.update()
        physics.add_physics(bpy.context, obj)
        return obj

    def _assert_follows(self, obj):
        scene = bpy.context.scene
        anchor = obj.cs_charm.physics_anchor

        def gap():
            return (obj.matrix_world.translation - anchor.matrix_world.translation).length

        self.assertEqual(scene.frame_current, scene.frame_start + 49)
        self.assertLess(gap(), 0.002)
        for f in range(scene.frame_start, scene.frame_start + 60):
            scene.frame_set(f)
            self.assertLess(gap(), 0.002, f"frame {f}")
        scene.frame_set(scene.frame_start)

    def test_placed_mid_animation(self):
        obj = self._placed_mid_animation(nla=False)
        self._assert_follows(obj)

    def test_placed_mid_nla_animation(self):
        obj = self._placed_mid_animation(nla=True)
        self._assert_follows(obj)
        self.assertTrue(obj.cs_charm.target.animation_data.use_nla)  # unfrozen again

    def test_mirrored_target(self):
        # Negative scale made the rest pose search sample with ~0 spacing
        # (MemoryError).
        target = _cube(size=1.0)
        target.scale = (-1, 1, 1)
        bpy.context.view_layer.update()
        obj = self.spawn(self.flask)
        self.settings.attach = "PARENT"
        P.place(obj, Vector((0, -0.5, 0)), Vector((0, -1, 0)), self.settings, target)
        physics.add_physics(bpy.context, obj)
        self.assertTrue(obj.cs_charm.physics)


class SurfaceTest(CharmTestCase):
    def test_points_near_samples_only_the_neighborhood(self):
        # A 100 m cube with a 3 cm charm: sampling every edge at charm
        # spacing took seconds (and much longer in scenes in millimeters).
        from cs_charm.ops import settle
        target = _cube(size=100.0)
        surface = settle.Surface(target, bpy.context.evaluated_depsgraph_get())
        center = Vector((50.0, -50.0, 0.0))  # middle of an edge
        points = surface.points_near(center, 0.03, 0.03 / 25.0)
        self.assertLess(len(points), 200)
        self.assertGreater(len(points), 40)  # along the edge through the sphere
        self.assertTrue(all(Vector(p).length <= 0.03 * 1.02 for p in points - tuple(center)))
        corner = surface.points_near(Vector((50.0, 50.0, 50.0)), 0.03, 0.03 / 25.0)
        self.assertIn((50.0, 50.0, 50.0), [tuple(p) for p in corner])


class SceneTest(CharmTestCase):
    def tearDown(self):
        for scene in list(bpy.data.scenes)[1:]:
            bpy.data.scenes.remove(scene)

    def test_scenes_keep_their_charms(self):
        first = bpy.context.scene
        self.settings.attach = "PARENT"
        target = _cube(size=1.0)
        obj = self.spawn(self.gem)
        P.place(obj, Vector((0.2, 0, 0.5)), Vector((0, 0, 1)), self.settings, target)
        physics.add_physics(bpy.context, obj)
        mine = set(first.objects)
        second = bpy.data.scenes.new("Second")
        with bpy.context.temp_override(scene=second, view_layer=second.view_layers[0]):
            context = bpy.context
            settings = second.cs_charm_place
            settings.attach = "PARENT"
            other_target = bpy.data.objects.new("Other", target.data.copy())
            second.collection.objects.link(other_target)
            other = self.spawn(self.gem)
            P.place(other, Vector((0.2, 0, 0.5)), Vector((0, 0, 1)), settings, other_target)
            physics.add_physics(context, other)
        self.assertFalse(mine & set(second.objects))
        self.assertNotIn(other, list(first.objects))
        self.assertEqual(set(first.objects), mine)
        self.assertNotEqual(obj.users_collection[0], other.users_collection[0])
        self.assertIn(other.cs_charm.physics_collider, list(second.objects))
        # Same target in both scenes: each scene gets its own collider.
        second.collection.objects.link(target)
        with bpy.context.temp_override(scene=second, view_layer=second.view_layers[0]):
            third = self.spawn(self.gem)
            P.place(third, Vector((-0.2, 0, 0.5)), Vector((0, 0, 1)), second.cs_charm_place, target)
            physics.add_physics(bpy.context, third)
        self.assertNotEqual(third.cs_charm.physics_collider, obj.cs_charm.physics_collider)
        self.assertNotIn(third.cs_charm.physics_collider, list(first.objects))


class DuplicateTest(CharmTestCase):
    def test_duplicates_get_own_data(self):
        from cs_charm.ops import duplicates
        target = _cube(size=1.0)
        self.settings.attach = "PARENT"
        obj = self.spawn(self.flask, 100)
        P.place(obj, Vector((0, -0.5, 0)), Vector((0, -1, 0)), self.settings, target)
        physics.add_physics(bpy.context, obj)
        coll = obj.users_collection[0]
        # Shift+D: own mesh, shared materials, shared helper pointers.
        copy = obj.copy()
        copy.data = obj.data.copy()
        coll.objects.link(copy)
        # Alt+D: shared mesh.
        linked = obj.copy()
        coll.objects.link(linked)
        bpy.context.view_layer.update()
        changed = duplicates.make_unique(bpy.context)
        self.assertEqual(set(changed), {copy, linked})
        meshes = {o.data for o in (obj, copy, linked)}
        self.assertEqual(len(meshes), 3)
        mats = [m for o in (obj, copy, linked) for m in o.data.materials if m]
        self.assertEqual(len(mats), len(set(mats)))
        for o in (copy, linked):
            self.assertFalse(o.cs_charm.physics)
            self.assertIsNone(o.rigid_body)
            self.assertIsNone(o.cs_charm.physics_weight)
        self.assertTrue(obj.cs_charm.physics)
        self.assertIn(obj.cs_charm.physics_anchor, list(bpy.data.objects))
        self.assertNotIn(utils.PROP_MODEL, copy.data)
        # Changing the copy leaves the original alone.
        def fill(o):
            return [n.inputs["Fill Level"].default_value for m in o.data.materials if m and m.node_tree
                    for n in m.node_tree.nodes if n.type == "GROUP" and "Fill Level" in n.inputs]
        before = fill(obj)
        copy.cs_charm.pattern = 777
        self.assertEqual(fill(obj), before)
        self.assertEqual(duplicates.make_unique(bpy.context), [])

    def test_handler_schedules_check(self):
        from cs_charm.ops import duplicates
        duplicates._on_load(None)
        self.spawn(self.gem)
        duplicates._on_depsgraph(bpy.context.scene, None)
        self.assertTrue(bpy.app.timers.is_registered(duplicates._deferred))
        bpy.app.timers.unregister(duplicates._deferred)


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
