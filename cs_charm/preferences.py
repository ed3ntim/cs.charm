# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Add-on preferences: user charm library path."""

import bpy
from bpy.props import BoolProperty, StringProperty

from .utils import ADDON_ID


def _on_path_change(self, context):
    from .library import registry
    registry.refresh(context)


class CSCHARM_AP_preferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    user_path: StringProperty(
        name="Charm Library Folder",
        description="Folder made by tools/export_cs2_charms.py (catalog.json + models), "
                    "or any folder with .glb/.gltf charm models. "
                    "First-level sub-folders become collections",
        subtype="DIR_PATH",
        update=_on_path_change,
    )
    include_incomplete: BoolProperty(
        name="List Incomplete Charms", default=True,
        description="Also list charms whose model or textures are missing (shown with a warning icon)",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "user_path")
        row = layout.row(align=True)
        row.operator("cs_charm.refresh_library", icon="FILE_REFRESH")
        row.operator("cs_charm.open_user_folder", icon="FILEBROWSER")
        layout.prop(self, "include_incomplete")
        col = layout.column(align=True)
        col.label(text="Export the CS2 charms from your own game install:", icon="INFO")
        col.label(text="  python tools/export_cs2_charms.py --out <folder> --download-s2v")
        col.label(text="Loose models also work: <folder>/<Collection>/name.glb")


def register():
    bpy.utils.register_class(CSCHARM_AP_preferences)


def unregister():
    bpy.utils.unregister_class(CSCHARM_AP_preferences)
