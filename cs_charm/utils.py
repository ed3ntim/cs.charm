# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Small shared helpers: add-on id, paths, preference access, logging."""

import logging
import os

import bpy

# Package name as Blender sees it ("cs_charm" for legacy installs,
# "bl_ext.<repo>.cs_charm" for extensions). Used as AddonPreferences id.
ADDON_ID = __package__

ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
# Only present in personal builds (tools/build_zip.py --with-charms).
BUNDLED_LIBRARY_DIR = os.path.join(ADDON_DIR, "charms", "bundled")
# Extra charm and sticker folders loaded before all others. Nothing ships
# there since 2.0 (no demo set); the tests point them at tests/fixtures.
CORE_LIBRARY_DIR = ""
CORE_STICKER_DIR = ""

# Custom property keys.
PROP_CHARM_ID = "cs_charm_id"            # on charm objects
PROP_HELPER = "cs_charm_helper"          # on physics anchor / pivot / collider objects
PROP_COLLIDER = "cs_charm_collider"      # on colliders: name of the target they follow
PROP_MATERIAL_KEY = "cs_charm_material"  # on charm materials
PROP_MATERIAL_SPEC = "cs_charm_spec"     # JSON copy of the spec, survives library moves
PROP_MODEL = "cs_charm_model"            # on template meshes: source model path
PROP_SLOTS = "cs_charm_slots"            # on meshes: glTF material names per slot
PROP_COLLECTION = "cs_charm_collection"  # on the per-scene charm collections
PROP_STICKER = "cs_charm_sticker"        # on slab objects: JSON copy of the sticker
PROP_LABEL = "cs_charm_label"            # on slab meshes: label plane (JSON)

CHARM_COLLECTION_NAME = "CS Charms"

log = logging.getLogger("cs_charm")


def get_prefs():
    """Return the add-on preferences or None (e.g. when run from tests)."""
    addon = bpy.context.preferences.addons.get(ADDON_ID)
    return addon.preferences if addon else None


def user_library_dir():
    """Absolute user library path from the preferences, or '' if unset/invalid."""
    prefs = get_prefs()
    if prefs is None or not prefs.user_path:
        return ""
    path = bpy.path.abspath(prefs.user_path)
    return path if os.path.isdir(path) else ""


def _sticker_addon_dirs():
    """Library folders of an installed cs.sticker: its user folder from the
    preferences, then its core and bundled sets."""
    import sys
    out = []
    for key, addon in bpy.context.preferences.addons.items():
        if key != "cs_sticker" and not key.endswith(".cs_sticker"):
            continue
        prefs = getattr(addon, "preferences", None)
        user = getattr(prefs, "user_path", "") if prefs else ""
        if user:
            out.append(bpy.path.abspath(user))
        module = sys.modules.get(key)
        root = os.path.dirname(os.path.abspath(module.__file__)) if module and module.__file__ else ""
        if root:
            out += [os.path.join(root, "stickers", "bundled"), os.path.join(root, "stickers", "core")]
    return out


def sticker_library_dirs():
    """Sticker library folders, most specific first: the folder from the
    preferences, or (empty) the folders of an installed cs.sticker, then
    CORE_STICKER_DIR (tests only)."""
    prefs = get_prefs()
    path = bpy.path.abspath(prefs.sticker_path) if prefs is not None and prefs.sticker_path else ""
    dirs = [path] if path else _sticker_addon_dirs()
    if CORE_STICKER_DIR:
        dirs.append(CORE_STICKER_DIR)
    seen, out = set(), []
    for d in dirs:
        key = os.path.normcase(os.path.abspath(d))
        if key not in seen and os.path.isdir(d):
            seen.add(key)
            out.append(d)
    return out


def is_charm(obj):
    return obj is not None and PROP_CHARM_ID in obj


def is_helper(obj):
    return obj is not None and PROP_HELPER in obj


def charm_collection(context):
    """Get (or create) the collection that holds the charms of this scene.

    Every scene gets its own: a collection linked into two scenes shows
    the same objects in both. Older files match by name."""
    scene = context.scene
    for coll in scene.collection.children_recursive:
        if PROP_COLLECTION in coll or coll.name == CHARM_COLLECTION_NAME:
            return coll
    coll = bpy.data.collections.new(CHARM_COLLECTION_NAME)
    coll[PROP_COLLECTION] = True
    scene.collection.children.link(coll)
    return coll


def active_charm(context):
    """The active object if it is a charm (panel buttons act on it only)."""
    obj = context.active_object
    return obj if is_charm(obj) else None


def selected_charms(context):
    objs = list(context.selected_objects)
    active = context.active_object
    if active is not None and active not in objs:
        objs.append(active)
    return [o for o in objs if is_charm(o)]
