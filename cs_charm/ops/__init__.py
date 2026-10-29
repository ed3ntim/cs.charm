# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Operators and the logic behind them.

    spawn.py        glTF import, template meshes, charm materials, patterns
    placement.py    ray casts, orientation, attach / detach, stored placement
    physics.py      rigid body pendulum (anchor + point constraint)
    interactive.py  modal placement with live preview
    charm_ops.py    spawn / edit operators
    library_ops.py  refresh, open folder, show in library
"""

import bpy

from . import charm_ops, interactive, library_ops

_classes = (*library_ops.classes, *charm_ops.classes, *interactive.classes)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
