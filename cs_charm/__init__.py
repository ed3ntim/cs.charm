# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""cs.charm - spawn CS2 charms (keychains) with their patterns.

Works both as a Blender 4.5+ extension (blender_manifest.toml) and as a
legacy add-on (bl_info). Sub-packages:

    library/  charm database: catalog, patterns, DynamicParams evaluator
    nodes/    node groups and material assembly per CS2 shader
    ops/      operators: spawning, placement, attachment, physics
    ui/       sidebar panels and the charm list

Host mode (cs.blend): a host add-on registers the package as a sub-module
with ``register(host)``. It then registers SETTINGS (after register), keeps
one instance per module and provides ``host.settings(MODULE_ID)`` and
``host.user_path(MODULE_ID, sub, create)``; it draws the settings with
``draw_prefs(layout, settings)``. Standalone (host None) nothing changes.
"""

bl_info = {
    "name": "cs.charm",
    "author": "ed3n",
    "version": (2, 1, 1),
    "blender": (4, 5, 0),
    "location": "3D Viewport > Sidebar > cs.charm",
    "description": "Spawn CS2 charms with their patterns applied and attach them to objects",
    "category": "Object",
    "support": "COMMUNITY",
}

# Support "Reload Scripts": re-import submodules if already loaded.
if "bpy" in locals():
    import importlib

    for _mod in (utils, preferences, properties, library, nodes, ops, ui):  # noqa: F821
        importlib.reload(_mod)

import bpy  # noqa: E402

from . import utils, preferences, properties, library, nodes, ops, ui  # noqa: E402

# Registration order matters: property groups before anything that points to them.
_modules = (properties, library, ops, ui)

MODULE_ID = utils.MODULE_ID
SETTINGS = preferences.CSCHARM_PG_settings
draw_prefs = preferences.draw_prefs


def register(host=None):
    utils.set_host(host)
    preferences.register(host)
    for mod in _modules:
        mod.register()


def unregister():
    for mod in reversed(_modules):
        mod.unregister()
    preferences.unregister()
    utils.set_host(None)
