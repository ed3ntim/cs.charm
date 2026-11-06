# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Sticker Slab operators: load the sticker library, put the picked sticker
into slabs, show a slab's sticker in the picker."""

import bpy

from .. import utils
from ..library import sticker_registry
from ..nodes import slab
from .spawn import report_warnings


class CSCHARM_OT_refresh_stickers(bpy.types.Operator):
    """Load (or reload) the sticker library for the Sticker Slab"""
    bl_idname = "cs_charm.refresh_stickers"
    bl_label = "Refresh Stickers"

    def execute(self, context):
        lib = sticker_registry.refresh(context)
        if not len(lib):
            self.report({"WARNING"}, "No stickers found: set the Sticker Library in the add-on preferences "
                                     "or install cs.sticker")
        else:
            self.report({"INFO"}, f"{len(lib)} stickers")
        return {"FINISHED"}


class CSCHARM_OT_set_sticker(bpy.types.Operator):
    """Put the sticker picked in the Library panel into the selected Sticker Slabs"""
    bl_idname = "cs_charm.set_sticker"
    bl_label = "Put Picked Sticker in Slab"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(slab.is_slab(o) for o in utils.selected_charms(context))

    def execute(self, context):
        sticker = sticker_registry.selected_sticker(context) if sticker_registry.is_loaded() else None
        if sticker is None:
            self.report({"ERROR"}, "Pick a sticker in the Library panel first (select the Sticker Slab there)")
            return {"CANCELLED"}
        warnings, count = [], 0
        for obj in utils.selected_charms(context):
            if slab.is_slab(obj):
                warnings += slab.apply_sticker(obj, sticker)
                count += 1
        report_warnings(self, warnings)
        if not warnings:
            self.report({"INFO"}, f"{sticker.name} in {count} slab(s)")
        return {"FINISHED"}


class CSCHARM_OT_show_sticker(bpy.types.Operator):
    """Select the active slab's sticker in the sticker picker"""
    bl_idname = "cs_charm.show_sticker"
    bl_label = "Show Sticker in Picker"

    @classmethod
    def poll(cls, context):
        return slab.sticker_of(context.active_object) is not None

    def execute(self, context):
        sticker = slab.sticker_of(context.active_object)
        state = context.window_manager.cs_charm
        state.sticker_search = ""
        state.sticker_collection = "ALL"
        state.sticker_finish = "ALL"
        state.sticker_rarity = "ALL"
        state.sticker_id = sticker.id
        sticker_registry.sync_items(state)
        if sticker_registry.get_sticker(sticker.id) is None:
            self.report({"WARNING"}, f"{sticker.name} is not in the current sticker library")
            return {"CANCELLED"}
        # Bring the slab itself up in the charm list so the picker is shown.
        bpy.ops.cs_charm.select_in_library()
        return {"FINISHED"}


classes = (CSCHARM_OT_refresh_stickers, CSCHARM_OT_set_sticker, CSCHARM_OT_show_sticker)
