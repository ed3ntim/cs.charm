# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Operators: spawning (on the selected object / at the 3D cursor) and
editing spawned charms (pattern, attachment, physics, materials)."""

import bpy
from mathutils import Vector

from .. import utils
from ..library import patterns, registry
from . import physics
from . import placement as P
from .spawn import (
    create_charm_object, pick_pattern, rebuild_materials, report_warnings, select_only,
)


def _spawn(op, context, location, normal, target):
    charm = registry.selected_charm(context)
    if charm is None:
        op.report({"ERROR"}, "No charm selected in the library")
        return None
    settings = context.scene.cs_charm_place
    try:
        obj, warnings = create_charm_object(context, charm, pick_pattern(settings))
    except RuntimeError as exc:
        op.report({"ERROR"}, str(exc))
        return None
    P.place(obj, location, normal, settings, target)
    if settings.physics:
        context.view_layer.update()
        physics.add_physics(context, obj)
    select_only(context, obj)
    report_warnings(op, warnings)
    return obj


class CSCHARM_OT_spawn_on_selected(bpy.types.Operator):
    """Attach the library charm to the active mesh, at the surface point closest to the 3D cursor"""
    bl_idname = "cs_charm.spawn_on_selected"
    bl_label = "Spawn on Selected"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (context.mode == "OBJECT" and obj is not None and obj.type == "MESH"
                and not utils.is_charm(obj))

    def execute(self, context):
        target = context.active_object
        hit = P.closest_surface_point(target, context.scene.cursor.location, context)
        if hit is None:
            self.report({"ERROR"}, "Could not find a surface point on the active object")
            return {"CANCELLED"}
        obj = _spawn(self, context, hit[0], hit[1], target)
        return {"FINISHED"} if obj else {"CANCELLED"}


class CSCHARM_OT_spawn_at_cursor(bpy.types.Operator):
    """Spawn the library charm with its attachment point at the 3D cursor (manual mode).
    Attaches to the active object if one is selected and Attach is not None"""
    bl_idname = "cs_charm.spawn_at_cursor"
    bl_label = "Manual (at Cursor)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        cursor = context.scene.cursor
        # The cursor's -Y axis is the "surface normal" the charm faces along.
        normal = cursor.matrix.to_3x3() @ Vector((0.0, -1.0, 0.0))
        active = context.active_object
        target = active if active is not None and active.select_get() and not utils.is_charm(active) \
            and not utils.is_helper(active) else None
        obj = _spawn(self, context, cursor.location.copy(), normal, target)
        return {"FINISHED"} if obj else {"CANCELLED"}


class _CharmOperator:
    """Acts on the active charm only, never on other selected charms."""

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and utils.active_charm(context) is not None


class CSCHARM_OT_randomize_pattern(_CharmOperator, bpy.types.Operator):
    """Give the active charm a random pattern"""
    bl_idname = "cs_charm.randomize_pattern"
    bl_label = "Random Pattern"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        utils.active_charm(context).cs_charm.pattern = patterns.random_pattern()
        return {"FINISHED"}


class CSCHARM_OT_reset_materials(_CharmOperator, bpy.types.Operator):
    """Rebuild the materials of the active charm from the library (discards manual changes)"""
    bl_idname = "cs_charm.reset_materials"
    bl_label = "Reset Materials"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            warnings = rebuild_materials(utils.active_charm(context))
        except RuntimeError:
            self.report({"WARNING"}, "Charm not found in the library")
            return {"CANCELLED"}
        report_warnings(self, warnings)
        return {"FINISHED"}


class CSCHARM_OT_attach(bpy.types.Operator):
    """Attach the active charm to the surface it was placed on, or attach the selected charms to the active object (keeps their position)"""
    bl_idname = "cs_charm.attach"
    bl_label = "Attach"
    bl_options = {"REGISTER", "UNDO"}

    mode: bpy.props.EnumProperty(name="Mode", items=[
        ("PARENT", "Parent", "Parent to the target"),
        ("CHILD_OF", "Child Of", "Child Of constraint to the target"),
    ], default="PARENT")

    @staticmethod
    def _jobs(context):
        """[(charm, target)]: the active charm and its own surface, or the
        selected charms and a non-charm active object."""
        active = context.active_object
        charm = utils.active_charm(context)
        if charm is not None:
            target = charm.cs_charm.target or charm.cs_charm.surface
            return [(charm, target)] if target is not None else []
        if active is None or utils.is_helper(active):
            return []
        return [(obj, active) for obj in utils.selected_charms(context)]

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT" and bool(cls._jobs(context))

    def execute(self, context):
        for obj, target in self._jobs(context):
            if obj.cs_charm.physics:
                physics.remove_physics(context, obj)
            P.adopt_current_transform(obj)
            P.attach(obj, target, self.mode)
        return {"FINISHED"}


class CSCHARM_OT_detach(_CharmOperator, bpy.types.Operator):
    """Detach the active charm from its target (keeps its position)"""
    bl_idname = "cs_charm.detach"
    bl_label = "Detach"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = utils.active_charm(context)
        if obj.cs_charm.physics:
            physics.remove_physics(context, obj)
        P.attach(obj, None, "NONE")
        return {"FINISHED"}


class CSCHARM_OT_set_anchor(_CharmOperator, bpy.types.Operator):
    """Use the active charm's current position as its attachment point (after moving it with G)"""
    bl_idname = "cs_charm.set_anchor"
    bl_label = "Set Anchor from Position"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = utils.active_charm(context)
        P.adopt_current_transform(obj)
        P.update_transform(obj)
        return {"FINISHED"}


class CSCHARM_OT_add_physics(_CharmOperator, bpy.types.Operator):
    """Let the active charm swing from its attachment point (rigid body pendulum). Play the timeline to simulate"""
    bl_idname = "cs_charm.add_physics"
    bl_label = "Add Physics"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = utils.active_charm(context)
        if not obj.cs_charm.physics:
            if not obj.cs_charm.placed:
                P.store_anchor(obj, obj.matrix_world.translation, Vector((0.0, -1.0, 0.0)))
                obj.cs_charm.placed = True
            physics.add_physics(context, obj)
        self.report({"INFO"}, "Physics on: play the timeline to simulate")
        return {"FINISHED"}


class CSCHARM_OT_remove_physics(_CharmOperator, bpy.types.Operator):
    """Remove the swing physics and re-attach the active charm as before"""
    bl_idname = "cs_charm.remove_physics"
    bl_label = "Remove Physics"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = utils.active_charm(context)
        if obj.cs_charm.physics:
            physics.remove_physics(context, obj)
        return {"FINISHED"}


class CSCHARM_OT_delete(_CharmOperator, bpy.types.Operator):
    """Delete the active charm including its physics helpers"""
    bl_idname = "cs_charm.delete"
    bl_label = "Delete Charm"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        physics.delete_charm(context, utils.active_charm(context))
        return {"FINISHED"}


class CSCHARM_OT_reset_placement(bpy.types.Operator):
    """Reset the placement settings to their defaults"""
    bl_idname = "cs_charm.reset_placement"
    bl_label = "Reset to Defaults"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.cs_charm_place
        for prop in settings.bl_rna.properties:
            if prop.identifier != "rna_type" and not prop.is_readonly:
                settings.property_unset(prop.identifier)
        return {"FINISHED"}


classes = (
    CSCHARM_OT_spawn_on_selected,
    CSCHARM_OT_spawn_at_cursor,
    CSCHARM_OT_randomize_pattern,
    CSCHARM_OT_reset_materials,
    CSCHARM_OT_attach,
    CSCHARM_OT_detach,
    CSCHARM_OT_set_anchor,
    CSCHARM_OT_add_physics,
    CSCHARM_OT_remove_physics,
    CSCHARM_OT_delete,
    CSCHARM_OT_reset_placement,
)
