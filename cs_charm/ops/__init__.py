# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Operators and the logic behind them.

    spawn.py        glTF import, template meshes, charm materials, patterns
    placement.py    ray casts, orientation, attach / detach, stored placement
    physics.py      rigid body pendulum (anchor + point constraint)
    interactive.py  modal placement with live preview
    settle.py       resting pose on the object around the attachment point
    duplicates.py   duplicated charms get their own mesh, materials, physics
    charm_ops.py    spawn / edit operators
    library_ops.py  refresh, open folder, show in library
    slab_ops.py     Sticker Slab: load stickers, put a sticker in a slab
"""

import bpy

from . import charm_ops, duplicates, interactive, library_ops, slab_ops

_classes = (*library_ops.classes, *charm_ops.classes, *interactive.classes, *slab_ops.classes)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    duplicates.register()


def unregister():
    duplicates.unregister()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
