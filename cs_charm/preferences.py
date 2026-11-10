# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Settings (charm library, sticker library, label font) and the add-on
preferences.

The settings live in a PropertyGroup (CSCHARM_PG_settings). Standalone,
the AddonPreferences point to it and add the uninstall button. Under a host
add-on (cs.blend, register(host)) the host keeps the settings and draws
them through draw_prefs(); no AddonPreferences, no uninstall button.

Older versions kept the values directly on the AddonPreferences. Those
stay declared there (hidden) and are moved into the settings once."""

import bpy
from bpy.props import BoolProperty, PointerProperty, StringProperty

from . import utils


def install_location(context):
    """Where the add-on is installed: ("EXTENSION", repo_index, pkg_id),
    ("SYSTEM", repo_index, pkg_id) for a read-only system repo, or
    ("LEGACY", None, module) for an add-on outside the extension system."""
    parts = utils.ADDON_ID.split(".")
    if len(parts) == 3 and parts[0] == "bl_ext":
        for i, repo in enumerate(context.preferences.extensions.repos):
            if repo.module == parts[1]:
                kind = "SYSTEM" if getattr(repo, "source", "") == "SYSTEM" else "EXTENSION"
                return kind, i, parts[2]
        return None
    return "LEGACY", None, utils.ADDON_ID


def _uninstall(location):
    """Run Blender's uninstall once our operator has returned: the add-on
    unregisters itself, so it must not happen inside its own operator."""
    kind, repo_index, pkg = location
    wm = bpy.context.window_manager
    window = wm.windows[0] if wm.windows else None
    with bpy.context.temp_override(window=window):
        if kind == "EXTENSION":
            bpy.ops.extensions.package_uninstall(repo_index=repo_index, pkg_id=pkg)
        else:
            bpy.ops.preferences.addon_remove(module=pkg)
    return None  # one-shot timer


class CSCHARM_OT_uninstall(bpy.types.Operator):
    """Disable cs.charm and delete it from disk. Charms already placed in
    your files stay as they are; your exported charm library is kept"""
    bl_idname = "cs_charm.uninstall"
    bl_label = "Uninstall cs.charm"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        loc = install_location(context)
        return loc is not None and loc[0] != "SYSTEM"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title="Uninstall cs.charm?",
            message="The add-on is disabled and its files are deleted.",
            confirm_text="Uninstall", icon="WARNING")

    def execute(self, context):
        location = install_location(context)
        bpy.app.timers.register(lambda: _uninstall(location), first_interval=0.1)
        return {"FINISHED"}


def _on_path_change(self, context):
    from .library import registry
    registry.refresh(context)


def _on_sticker_path_change(self, context):
    from .library import sticker_registry
    sticker_registry.invalidate()


def _on_font_change(self, context):
    from .nodes import slab
    slab.on_font_changed()


class CSCHARM_PG_settings(bpy.types.PropertyGroup):
    user_path: StringProperty(
        name="Charm Library Folder",
        description="Folder made by tools/export_cs2_charms.py (catalog.json + models), "
                    "or any folder with .glb/.gltf charm models. "
                    "First-level sub-folders become collections",
        subtype="DIR_PATH",
        update=_on_path_change,
    )
    sticker_path: StringProperty(
        name="Sticker Library",
        description="cs.sticker library for the Sticker Slab (folder with catalog.json, e.g. made by "
                    "cs.sticker's tools/export_cs2_stickers.py). Empty = use the folders of an "
                    "installed cs.sticker",
        subtype="DIR_PATH",
        update=_on_sticker_path_change,
    )
    label_font: StringProperty(
        name="Slab Label Font",
        description="Font file for the Sticker Slab label (.ttf/.otf). Empty = Blender's built-in font",
        subtype="FILE_PATH",
        update=_on_font_change,
    )
    include_incomplete: BoolProperty(
        name="List Incomplete Charms", default=True,
        description="Also list charms whose model or textures are missing (shown with a warning icon)",
    )


SETTINGS_KEYS = ("user_path", "sticker_path", "label_font", "include_incomplete")


def draw_prefs(layout, settings):
    """Settings UI, for the AddonPreferences and for a host add-on."""
    layout.prop(settings, "user_path")
    row = layout.row(align=True)
    row.operator("cs_charm.refresh_library", icon="FILE_REFRESH")
    row.operator("cs_charm.open_user_folder", icon="FILEBROWSER")
    layout.prop(settings, "include_incomplete")
    col = layout.column(align=True)
    col.label(text="Export the CS2 charms from your own game install:", icon="INFO")
    col.label(text="  python tools/export_cs2_charms.py --out <folder> --download-s2v")
    col.label(text="Loose models also work: <folder>/<Collection>/name.glb")

    box = layout.box()
    box.label(text="Sticker Slab", icon="IMAGE_RGB_ALPHA")
    box.prop(settings, "sticker_path")
    from .library import sticker_registry
    box.label(text=sticker_registry.status_text(), icon="INFO")
    box.operator("cs_charm.refresh_stickers", icon="FILE_REFRESH")
    box.prop(settings, "label_font")


class CSCHARM_AP_preferences(bpy.types.AddonPreferences):
    bl_idname = utils.ADDON_ID

    settings: PointerProperty(type=CSCHARM_PG_settings)
    migrated: BoolProperty(options={"HIDDEN"})
    # Values of older versions, read once by migrate().
    user_path: StringProperty(options={"HIDDEN"})
    sticker_path: StringProperty(options={"HIDDEN"})
    label_font: StringProperty(options={"HIDDEN"})
    include_incomplete: BoolProperty(default=True, options={"HIDDEN"})

    def draw(self, context):
        layout = self.layout
        draw_prefs(layout, self.settings)
        layout.separator()
        row = layout.row()
        row.alert = True
        row.operator("cs_charm.uninstall", icon="TRASH")
        loc = install_location(context)
        if loc is not None and loc[0] == "SYSTEM":
            layout.label(text="Installed in a system repository, remove it there.", icon="INFO")


def migrate(prefs):
    """Move the values of older versions into the settings (once). Item
    assignment skips the update callbacks: nothing is loaded here."""
    if prefs is None or prefs.migrated:
        return False
    for key in SETTINGS_KEYS:
        prefs.settings[key] = getattr(prefs, key)
    prefs.user_path = prefs.sticker_path = prefs.label_font = ""
    prefs.include_incomplete = True
    prefs.migrated = True
    return True


_standalone = False


def register(host=None):
    global _standalone
    bpy.utils.register_class(CSCHARM_PG_settings)
    _standalone = host is None
    if not _standalone:
        return
    bpy.utils.register_class(CSCHARM_OT_uninstall)
    bpy.utils.register_class(CSCHARM_AP_preferences)
    addon = bpy.context.preferences.addons.get(utils.ADDON_ID)
    if addon is not None:
        migrate(addon.preferences)


def unregister():
    global _standalone
    if _standalone:
        bpy.utils.unregister_class(CSCHARM_AP_preferences)
        bpy.utils.unregister_class(CSCHARM_OT_uninstall)
        _standalone = False
    bpy.utils.unregister_class(CSCHARM_PG_settings)
