# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""cs.charm - spawn CS2 charms (keychains) with their patterns.

Works both as a Blender 4.5+ extension (blender_manifest.toml) and as a
legacy add-on (bl_info). Sub-packages:

    library/  charm database: catalog, patterns, DynamicParams evaluator
    nodes/    node groups and material assembly per CS2 shader
    ops/      operators: spawning, placement, attachment, physics
    ui/       sidebar panels and the charm list
"""

bl_info = {
    "name": "cs.charm",
    "author": "ed3n",
    "version": (1, 0, 0),
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
_modules = (preferences, properties, library, ops, ui)


def register():
    for mod in _modules:
        mod.register()


def unregister():
    for mod in reversed(_modules):
        mod.unregister()
