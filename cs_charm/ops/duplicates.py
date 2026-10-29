# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Duplicated charms get their own data.

Shift+D copies a charm object but keeps its materials (and Alt+D also its
mesh), so changing the pattern of one copy would change all of them. The
physics helpers are shared too. After objects were added, a short timer
looks for charms that share a mesh, a charm material or physics helpers
with another charm and gives the copies their own. The charm whose name
sorts first keeps the original data.
"""

import bpy
from bpy.app.handlers import persistent

from .. import utils
from . import physics, spawn

_state = {"objects": -1}


def _charms():
    return sorted((o for o in bpy.data.objects if utils.is_charm(o)), key=lambda o: o.name)


def make_unique(context=None):
    """Give every charm its own mesh, charm materials and physics helpers.
    Returns the charms that were changed."""
    context = context or bpy.context
    changed = []
    meshes, materials, helpers, models = set(), set(), set(), set()
    for obj in _charms():
        touched = False
        mesh = obj.data
        if mesh is not None and mesh in meshes:
            mesh = mesh.copy()
            if utils.PROP_MODEL in mesh:
                del mesh[utils.PROP_MODEL]
            obj.data = mesh
            touched = True
        if mesh is not None and utils.PROP_MODEL in mesh:
            # Only the cached import stays a template (delete_charm keeps it).
            key = mesh[utils.PROP_MODEL]
            cached = spawn._templates.get(key)
            if (cached and cached != mesh.name) or (not cached and key in models):
                del mesh[utils.PROP_MODEL]
            models.add(key)
        if mesh is not None:
            meshes.add(mesh)
            for i, mat in enumerate(mesh.materials):
                if mat is None or utils.PROP_MATERIAL_KEY not in mat:
                    continue
                if mat in materials:
                    mat = mat.copy()
                    mesh.materials[i] = mat
                    touched = True
                materials.add(mat)
        state = obj.cs_charm
        if state.physics_anchor is not None and state.physics_anchor in helpers:
            _drop_shared_physics(context, obj)
            touched = True
        for helper in (state.physics_anchor, state.physics_pivot):
            if helper is not None:
                helpers.add(helper)
        if touched:
            changed.append(obj)
    return changed


def _drop_shared_physics(context, obj):
    """The copy points at the original's anchor: remove its rigid body and
    restore the rest pose instead (Add Physics gives it its own setup)."""
    state = obj.cs_charm
    state.physics_anchor = None
    state.physics_pivot = None
    physics.remove_physics(context, obj)


def _deferred():
    try:
        make_unique()
    except Exception as exc:  # never let a timer raise
        utils.log.error("cs.charm: duplicate check failed: %s", exc)
    return None


@persistent
def _on_depsgraph(scene, depsgraph):
    count = len(bpy.data.objects)
    if count == _state["objects"]:
        return
    grew = count > _state["objects"] >= 0
    _state["objects"] = count
    # Data must not change inside the depsgraph handler: defer.
    if grew and not bpy.app.timers.is_registered(_deferred):
        bpy.app.timers.register(_deferred, first_interval=0.0)


@persistent
def _on_load(_dummy):
    _state["objects"] = len(bpy.data.objects)


def register():
    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph)
    bpy.app.handlers.load_post.append(_on_load)


def unregister():
    if _on_depsgraph in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph)
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    if bpy.app.timers.is_registered(_deferred):
        bpy.app.timers.unregister(_deferred)
