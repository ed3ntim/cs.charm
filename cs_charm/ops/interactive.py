# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Interactive placement: the selected charm follows the mouse over mesh
surfaces as a live preview, wheel rotates, Ctrl+wheel scales, click places."""

import math

import bpy
from bpy_extras import view3d_utils

from ..library import registry
from . import physics
from . import placement as P
from .spawn import create_charm_object, pick_pattern, report_warnings, select_only

HELP = ("LMB: place  |  Shift+LMB: place & continue  |  Wheel: rotate (Shift: fine)  |  "
        "Ctrl+Wheel: scale  |  F: hang / surface  |  RMB/Esc: finish/cancel")

# Events that should still reach the viewport (navigation).
_PASS_THROUGH = {
    "MIDDLEMOUSE", "TRACKPADPAN", "TRACKPADZOOM", "MOUSEROTATE", "MOUSESMARTZOOM",
    "NDOF_MOTION", "NUMPAD_0", "NUMPAD_1", "NUMPAD_2", "NUMPAD_3", "NUMPAD_4",
    "NUMPAD_5", "NUMPAD_6", "NUMPAD_7", "NUMPAD_8", "NUMPAD_9", "NUMPAD_PERIOD",
}


class CSCHARM_OT_place_interactive(bpy.types.Operator):
    """Move the selected charm over surfaces with a live preview and click to attach it"""
    bl_idname = "cs_charm.place_interactive"
    bl_label = "Place Interactively"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (context.mode == "OBJECT" and context.area is not None
                and context.area.type == "VIEW_3D")

    # -- lifecycle -------------------------------------------------------------

    def invoke(self, context, event):
        self.charm = registry.selected_charm(context)
        if self.charm is None:
            self.report({"ERROR"}, "No charm selected in the library")
            return {"CANCELLED"}
        settings = context.scene.cs_charm_place
        self.rotation = settings.rotation
        self.scale_factor = 1.0
        self.align = settings.align
        self.region = context.region
        self.rv3d = context.region_data
        self.candidates = P.surface_candidates(context)
        if not self.candidates:
            self.report({"ERROR"}, "No visible mesh surface to place on")
            return {"CANCELLED"}
        self.placed = []
        self.warnings = []
        self.ghost = None
        self.hit = None
        try:
            self._new_ghost(context)
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self._update(context, event)
        context.window_manager.modal_handler_add(self)
        context.area.header_text_set(HELP)
        return {"RUNNING_MODAL"}

    def _new_ghost(self, context):
        settings = context.scene.cs_charm_place
        obj, warnings = create_charm_object(context, self.charm, pick_pattern(settings))
        self.warnings += warnings
        # Keep the preview out of selection until placed.
        obj.hide_select = True
        obj.hide_set(self.hit is None)
        self.ghost = obj

    def _finish(self, context):
        context.area.header_text_set(None)

    # -- modal -------------------------------------------------------------------

    def modal(self, context, event):
        context.area.tag_redraw()
        if event.type in _PASS_THROUGH:
            return {"PASS_THROUGH"}

        if event.type == "MOUSEMOVE":
            self._update(context, event)
        elif event.type in {"WHEELUPMOUSE", "WHEELDOWNMOUSE"}:
            sign = 1 if event.type == "WHEELUPMOUSE" else -1
            if event.ctrl:
                self.scale_factor *= 1.1 ** sign
            else:
                self.rotation += math.radians(5 if event.shift else 15) * sign
            self._apply(context)
        elif event.type == "F" and event.value == "PRESS":
            self.align = "SURFACE" if self.align == "HANG" else "HANG"
            self._apply(context)
        elif event.type == "LEFTMOUSE" and event.value == "PRESS":
            if self.hit is None:
                self.report({"WARNING"}, "Not over a surface")
                return {"RUNNING_MODAL"}
            self._place(context)
            if event.shift:
                self._new_ghost(context)
                self._apply(context)
                return {"RUNNING_MODAL"}
            return self._done(context)
        elif event.type in {"RIGHTMOUSE", "ESC"} and event.value == "PRESS":
            if self.ghost is not None:
                physics.delete_charm(context, self.ghost)
                self.ghost = None
            if self.placed:
                return self._done(context)
            self._finish(context)
            return {"CANCELLED"}
        return {"RUNNING_MODAL"}

    # -- helpers -------------------------------------------------------------------

    def _update(self, context, event):
        coord = (event.mouse_region_x, event.mouse_region_y)
        origin = view3d_utils.region_2d_to_origin_3d(self.region, self.rv3d, coord)
        direction = view3d_utils.region_2d_to_vector_3d(self.region, self.rv3d, coord)
        self.hit = P.raycast_surfaces(context, origin, direction, self.candidates)
        self._apply(context)

    def _apply(self, context):
        if self.ghost is None:
            return
        self.ghost.hide_set(self.hit is None)
        if self.hit is None:
            return
        target, location, normal = self.hit
        settings = context.scene.cs_charm_place
        scale = P.charm_scale(settings, self.ghost.cs_charm.base_height, target) * self.scale_factor
        state = self.ghost.cs_charm
        state.align = self.align
        anchor = location + normal * settings.offset / 100.0 * state.base_height * scale
        self.ghost.matrix_world = P.orientation_matrix(anchor, normal, self.align, self.rotation, scale=scale)

    def _place(self, context):
        obj = self.ghost
        target, location, normal = self.hit
        settings = context.scene.cs_charm_place
        obj.hide_select = False
        scale = P.charm_scale(settings, obj.cs_charm.base_height, target) * self.scale_factor
        align = settings.align
        settings.align = self.align  # place() reads the align mode from the settings
        try:
            P.place(obj, location, normal, settings, target, scale=scale, rotation=self.rotation)
        finally:
            settings.align = align
        if settings.physics:
            context.view_layer.update()
            physics.add_physics(context, obj)
        self.placed.append(obj)
        self.ghost = None

    def _done(self, context):
        if self.ghost is not None:
            physics.delete_charm(context, self.ghost)
            self.ghost = None
        self._finish(context)
        if self.placed:
            select_only(context, self.placed[-1])
        report_warnings(self, self.warnings)
        self.report({"INFO"}, f"Placed {len(self.placed)} charm(s)")
        return {"FINISHED"}


classes = (CSCHARM_OT_place_interactive,)
