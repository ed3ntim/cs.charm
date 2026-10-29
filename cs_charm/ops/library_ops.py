# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Library operators: refresh, open the user folder, select a charm."""

import os
import subprocess
import sys

import bpy

from .. import utils
from ..library import registry


class CSCHARM_OT_refresh_library(bpy.types.Operator):
    """Rescan the core set and the user charm folder"""
    bl_idname = "cs_charm.refresh_library"
    bl_label = "Refresh Library"

    def execute(self, context):
        catalog = registry.refresh(context)
        warnings = len(catalog.report.warnings)
        msg = f"{len(catalog.charms)} charms in {len(catalog.collections())} collections"
        if warnings:
            msg += f" ({warnings} warnings, see the Library panel)"
        self.report({"WARNING"} if warnings else {"INFO"}, msg)
        return {"FINISHED"}


class CSCHARM_OT_open_user_folder(bpy.types.Operator):
    """Open the user charm folder in the file browser"""
    bl_idname = "cs_charm.open_user_folder"
    bl_label = "Open Folder"

    @classmethod
    def poll(cls, context):
        return bool(utils.user_library_dir())

    def execute(self, context):
        path = utils.user_library_dir()
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - opening a folder the user chose
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return {"FINISHED"}


class CSCHARM_OT_select_charm_in_library(bpy.types.Operator):
    """Select the active charm's entry in the library"""
    bl_idname = "cs_charm.select_in_library"
    bl_label = "Show in Library"

    @classmethod
    def poll(cls, context):
        return utils.is_charm(context.active_object)

    def execute(self, context):
        state = context.window_manager.cs_charm
        charm_id = context.active_object.get(utils.PROP_CHARM_ID, "")
        for attempt in range(2):
            for i, item in enumerate(state.items):
                if item.charm_id == charm_id:
                    state.index = i
                    return {"FINISHED"}
            # Not in the filtered list: clear filters once and retry.
            state.search = ""
            state.filter_collection = "ALL"
            state.filter_rarity = "ALL"
        self.report({"WARNING"}, "Charm not found in the library")
        return {"CANCELLED"}


classes = (CSCHARM_OT_refresh_library, CSCHARM_OT_open_user_folder, CSCHARM_OT_select_charm_in_library)
