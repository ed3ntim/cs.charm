# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Blender glue for the sticker library of the Sticker Slab: the shared
StickerLibrary, the sticker picker's list mirror and preview icons.

The library loads lazily (a full CS2 export lists ~11 000 stickers): only
when the picker is shown or a sticker is needed."""

import os
import time

import bpy

from .. import properties, utils
from . import sticker_thumbs as thumbs
from . import stickers as ST

_library = ST.StickerLibrary()
_loaded = False
_previews = None  # bpy.utils.previews collection, keyed by sticker id
_thumb_queue = []  # stickers whose composed thumbnail is not cached yet
_THUMB_PREFIX = "thumb:"

MAX_LIST_ITEMS = 300
_match_count = 0


def invalidate():
    """Forget the loaded library (path changed); reloads on next use."""
    global _loaded
    _loaded = False
    _library.load()
    _thumb_queue.clear()
    if _previews is not None:
        _previews.clear()


def get_library():
    global _loaded
    if not _loaded:
        _library.load(*utils.sticker_library_dirs())
        _loaded = True
        properties.set_sticker_filter_items(_library.collections(), _library.finishes(), _library.rarities())
        for msg in _library.report.warnings[:20]:
            utils.log.warning(msg)
    return _library


def is_loaded():
    return _loaded


def refresh(context=None):
    invalidate()
    lib = get_library()
    context = context or bpy.context
    if context.window_manager is not None:
        sync_items(context.window_manager.cs_charm)
    return lib


def status_text():
    if not _loaded:
        dirs = utils.sticker_library_dirs()
        return f"{len(dirs)} sticker folder(s), loads on first use"
    roots = [r for r in _library.roots if r != utils.CORE_STICKER_DIR]
    where = roots[0] if roots else "no sticker folder"
    return f"{len(_library)} stickers ({where})"


def get_sticker(sticker_id):
    return get_library().get(sticker_id) if sticker_id else None


# ---------------------------------------------------------------------------
# Picker list
# ---------------------------------------------------------------------------

def match_count():
    return _match_count


def _filter_value(state, name):
    value = getattr(state, name)
    return "" if value == "ALL" else value


def sync_items(state):
    """Mirror the filtered stickers (at most MAX_LIST_ITEMS) into the
    picker's CollectionProperty and keep the selected sticker selected."""
    global _match_count
    lib = get_library()
    state.sticker_items.clear()
    _match_count = 0
    for sticker in lib.filter(state.sticker_search, _filter_value(state, "sticker_collection"),
                              _filter_value(state, "sticker_finish"), _filter_value(state, "sticker_rarity")):
        _match_count += 1
        if _match_count > MAX_LIST_ITEMS:
            continue
        item = state.sticker_items.add()
        item.name = sticker.name
        item.sticker_id = sticker.id
        item.collection = sticker.collection
        item.finish = sticker.finish
        item.rarity = sticker.rarity
    for i, item in enumerate(state.sticker_items):
        if item.sticker_id == state.sticker_id:
            state["sticker_index"] = i
            break
    else:
        state["sticker_index"] = -1
    for name, items in (("sticker_collection", properties._sticker_collection_items),
                        ("sticker_finish", properties._sticker_finish_items),
                        ("sticker_rarity", properties._sticker_rarity_items)):
        if state.get(name, 0) >= len(items):
            state[name] = 0


def ensure_items(state):
    """Fill the picker if it was never filled (not from a draw callback)."""
    if not _loaded or (not state.sticker_items and _match_count == 0):
        sync_items(state)


def on_filter_changed(state):
    sync_items(state)


def on_selection_changed(state):
    if 0 <= state.sticker_index < len(state.sticker_items):
        state.sticker_id = state.sticker_items[state.sticker_index].sticker_id
        preview_icon(get_sticker(state.sticker_id))


def selected_sticker(context):
    state = context.window_manager.cs_charm
    return get_sticker(state.sticker_id) if state.sticker_id else None


# ---------------------------------------------------------------------------
# Previews
# ---------------------------------------------------------------------------

def _load_preview(key, path):
    if key not in _previews:
        try:
            _previews.load(key, path, "IMAGE")
        except (OSError, KeyError, RuntimeError):
            return 0
    return _previews[key].icon_id


def preview_icon(sticker):
    """icon_id for a sticker (0 if unavailable).

    Prefers the composed thumbnail (cut out, finish hint, as in
    cs.sticker). While that is not cached yet, the plain base texture is
    shown and the thumbnail is queued: building it creates images, which
    draw callbacks may not do."""
    if _previews is None or sticker is None or not sticker.base_path:
        return 0
    key = _THUMB_PREFIX + sticker.id
    if key in _previews:
        return _previews[key].icon_id
    path = thumbs.cache_path(sticker)
    if os.path.isfile(path):
        return _load_preview(key, path)
    if sticker not in _thumb_queue:
        _thumb_queue.append(sticker)
        if not bpy.app.timers.is_registered(_build_thumbs):
            bpy.app.timers.register(_build_thumbs, first_interval=0.05)
    return _load_preview("sticker:" + sticker.id, sticker.base_path)


def _build_thumbs():
    """Timer: build queued thumbnails for ~50 ms per tick."""
    start = time.perf_counter()
    while _thumb_queue and time.perf_counter() - start < 0.05:
        sticker = _thumb_queue.pop(0)
        try:
            thumbs.build(sticker)
        except Exception as exc:  # a broken texture must not stop the queue
            utils.log.warning("cs.charm: sticker thumbnail for %s failed: %s", sticker.id, exc)
    wm = bpy.context.window_manager
    for window in getattr(wm, "windows", []):
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()
    return 0.02 if _thumb_queue else None


def register():
    global _previews
    import bpy.utils.previews
    _previews = bpy.utils.previews.new()


def unregister():
    global _previews, _loaded
    if bpy.app.timers.is_registered(_build_thumbs):
        bpy.app.timers.unregister(_build_thumbs)
    _thumb_queue.clear()
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None
    _loaded = False
