# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Charm database.

    expr.py      evaluator for the DynamicParams expressions of CS2 materials
    patterns.py  pattern number -> $KeychainSeed -> parameter values
    gltf.py      reads glTF JSON / Source2Viewer material extras
    catalog.py   Charm / MaterialSpec, loading libraries, search + filter
    shading.py   CS2 shader parameters -> node inputs
    registry.py  Blender glue: shared catalog, UI list mirror, previews
    stickers.py  stickers of a cs.sticker library (Sticker Slab)
    sticker_registry.py  Blender glue for the sticker library and picker

Everything except the two registries is pure Python and unit tested without
Blender (tests/test_library.py).
"""


def register():
    from . import registry, sticker_registry
    registry.register()
    sticker_registry.register()


def unregister():
    from . import registry, sticker_registry
    sticker_registry.unregister()
    registry.unregister()
