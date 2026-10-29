# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Blender glue for the catalog: the shared Catalog instance, preview icons
and syncing the WindowManager list mirror."""

import bpy
import bpy.utils.previews
from bpy.app.handlers import persistent

from .. import properties, utils
from . import catalog as C

_catalog = C.Catalog()
_previews = None  # bpy.utils.previews collection, keyed by charm id
_loaded = False

# The UI list mirrors only the filtered result (keeps big libraries fast).
MAX_LIST_ITEMS = 500
_match_count = 0  # charms matching the current filter (may exceed the list)


def get_catalog():
    return _catalog


def refresh(context=None):
    """Reload core + bundled + user charms and rebuild the UI list."""
    global _loaded
    context = context or bpy.context
    _catalog.load(utils.CORE_LIBRARY_DIR, utils.user_library_dir(), utils.BUNDLED_LIBRARY_DIR)
    _loaded = True
    properties.set_collection_items(_catalog.collections())
    properties.set_rarity_items(_catalog.rarities())
    if _previews is not None:
        _previews.clear()
    wm = context.window_manager
    if wm is not None:
        sync_items(wm.cs_charm)
    for msg in _catalog.report.warnings:
        utils.log.warning(msg)
    return _catalog


def _filtered(state):
    prefs = utils.get_prefs()
    include_incomplete = prefs.include_incomplete if prefs else True
    collection = "" if state.filter_collection == "ALL" else state.filter_collection
    rarity = "" if state.filter_rarity == "ALL" else state.filter_rarity
    for charm in _catalog.filter(state.search, collection, rarity):
        missing = bool(charm.missing_files())
        if missing and not include_incomplete:
            continue
        yield charm, missing


def match_count():
    return _match_count


def sync_items(state):
    """Copy the filtered catalog entries (at most MAX_LIST_ITEMS) into the
    CollectionProperty shown by the UIList."""
    global _match_count
    selected = selected_id(state)
    state.items.clear()
    _match_count = 0
    for charm, missing in _filtered(state):
        _match_count += 1
        if _match_count > MAX_LIST_ITEMS:
            continue
        item = state.items.add()
        item.name = charm.name
        item.charm_id = charm.id
        item.collection = charm.collection
        item.rarity = charm.rarity
        item.has_pattern = charm.has_pattern()
        item.has_missing = missing

    # Restore previous selection if it still exists.
    for i, item in enumerate(state.items):
        if item.charm_id == selected:
            state["index"] = i  # bypass update callback
            break
    else:
        state["index"] = 0
    # The enums may now point to removed names.
    if state.get("filter_collection", 0) >= len(properties._collection_items):
        state["filter_collection"] = 0
    if state.get("filter_rarity", 0) >= len(properties._rarity_items):
        state["filter_rarity"] = 0


def selected_id(state):
    if 0 <= state.index < len(state.items):
        return state.items[state.index].charm_id
    return ""


def selected_charm(context):
    return _catalog.get(selected_id(context.window_manager.cs_charm))


def on_filter_changed(state):
    sync_items(state)


def on_selection_changed(state, context):
    # Previews load lazily; touching the icon here starts loading early.
    preview_icon(_catalog.get(selected_id(state)))


# ---------------------------------------------------------------------------
# Previews
# ---------------------------------------------------------------------------

def preview_icon(charm):
    """icon_id for a charm's inventory image (0 if unavailable)."""
    if _previews is None or charm is None or not charm.icon:
        return 0
    if charm.id not in _previews:
        try:
            _previews.load(charm.id, charm.icon, "IMAGE")
        except (OSError, KeyError, RuntimeError):
            return 0
    return _previews[charm.id].icon_id


# ---------------------------------------------------------------------------
# Handlers / registration
# ---------------------------------------------------------------------------

@persistent
def _on_load_post(_dummy):
    # The WindowManager is replaced when a file is loaded: refill the list
    # from the catalog in memory, no need to rescan the disk.
    if _loaded:
        sync_items(bpy.context.window_manager.cs_charm)
    else:
        refresh(bpy.context)


def _deferred_refresh():
    try:
        refresh(bpy.context)
    except Exception as exc:  # never let a timer raise
        utils.log.error("cs.charm: library refresh failed: %s", exc)
    return None


def register():
    global _previews
    _previews = bpy.utils.previews.new()
    bpy.app.handlers.load_post.append(_on_load_post)
    # bpy.context is restricted during register(); refresh right after.
    bpy.app.timers.register(_deferred_refresh, first_interval=0.1)


def unregister():
    global _previews
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if bpy.app.timers.is_registered(_deferred_refresh):
        bpy.app.timers.unregister(_deferred_refresh)
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None
