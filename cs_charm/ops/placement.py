# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Placement math shared by all spawn paths: surface ray casts, the charm's
orientation at an attachment point, attaching to a target and re-applying
the stored placement when the user edits it in the Active Charm panel.

A charm's origin is its attachment point (top of the chain); the model
hangs along -Z and is thin along X (its face looks along +/-X).

Placement is stored on ``Object.cs_charm``: anchor point and surface normal
(in target space when attached, so they follow the target), scale,
rotation, tilt, lean, offset and align mode. ``update_transform`` turns
that into the object's transform for every attach mode.
"""

import math

import bpy
from mathutils import Matrix, Vector

from .. import utils

CONSTRAINT_NAME = "CS Charm Attach"
WORLD_UP = Vector((0.0, 0.0, 1.0))

_suspend = 0  # >0 while several properties are written at once


# ---------------------------------------------------------------------------
# Surfaces
# ---------------------------------------------------------------------------

def surface_candidates(context, exclude=()):
    """Visible mesh objects a charm can be placed on."""
    out = []
    for obj in context.visible_objects:
        if obj.type != "MESH" or obj in exclude or utils.is_charm(obj) or utils.is_helper(obj):
            continue
        out.append(obj)
    return out


def raycast_surfaces(context, origin, direction, candidates):
    """Nearest hit -> (object, world location, world normal) or None."""
    depsgraph = context.evaluated_depsgraph_get()
    best, best_dist = None, math.inf
    for obj in candidates:
        mw = obj.matrix_world
        try:
            inv = mw.inverted()
        except ValueError:
            continue  # zero scale
        o = inv @ origin
        d = (inv.to_3x3() @ direction).normalized()
        hit, loc, nor, _idx = obj.ray_cast(o, d, depsgraph=depsgraph)
        if not hit:
            continue
        world = mw @ loc
        dist = (world - origin).length
        if dist < best_dist:
            normal = (inv.transposed().to_3x3() @ nor).normalized()
            best, best_dist = (obj, world, normal), dist
    return best


def closest_surface_point(obj, point, context=None):
    """Closest point on ``obj`` to a world point -> (location, normal) or None."""
    depsgraph = (context or bpy.context).evaluated_depsgraph_get()
    mw = obj.matrix_world
    inv = mw.inverted()
    ok, loc, nor, _idx = obj.closest_point_on_mesh(inv @ point, depsgraph=depsgraph)
    if not ok:
        return None
    return mw @ loc, (inv.transposed().to_3x3() @ nor).normalized()


def target_size(target):
    """Longest side of the target's world bounding box."""
    if target is None:
        return 0.0
    corners = [target.matrix_world @ Vector(c) for c in target.bound_box]
    return max(max(c[i] for c in corners) - min(c[i] for c in corners) for i in range(3))


def charm_scale(settings, base_height, target=None):
    """Scale factor for a new charm from the placement settings."""
    if settings.size_mode == "RELATIVE" and target is not None and base_height > 0:
        size = target_size(target)
        if size > 0:
            return size * settings.size_relative / 100.0 / base_height
    return settings.scale


# ---------------------------------------------------------------------------
# Orientation
# ---------------------------------------------------------------------------

def _perpendicular(v):
    other = Vector((1.0, 0.0, 0.0)) if abs(v.x) < 0.9 else Vector((0.0, 1.0, 0.0))
    return v.cross(other).normalized()


def orientation_matrix(location, normal, align="HANG", rotation=0.0, tilt=0.0, lean=0.0, scale=1.0):
    """World matrix of a charm whose attachment point sits at ``location``.

    HANG:    local -Z points down, the face (+X) looks away from the surface
    SURFACE: local -Z points along the surface normal (away from it)
    ``rotation`` turns around the hanging axis, ``tilt`` swings sideways
    (around the face axis), ``lean`` toward / away from the surface.
    """
    n = Vector(normal)
    n = n.normalized() if n.length > 1e-9 else WORLD_UP.copy()
    if align == "SURFACE":
        z = -n
        x = (WORLD_UP - WORLD_UP.dot(z) * z)
        x = x.normalized() if x.length > 1e-6 else _perpendicular(z)
    else:
        z = WORLD_UP.copy()
        x = Vector((n.x, n.y, 0.0))
        x = x.normalized() if x.length > 1e-6 else Vector((1.0, 0.0, 0.0))
    y = z.cross(x).normalized()
    basis = Matrix((x, y, z)).transposed().to_4x4()
    local = (Matrix.Rotation(rotation, 4, "Z")
             @ Matrix.Rotation(tilt, 4, "X")
             @ Matrix.Rotation(-lean, 4, "Y"))
    return Matrix.Translation(location) @ basis @ local @ Matrix.Scale(scale, 4)


def offset_distance(state_or_settings, base_height, scale):
    return state_or_settings.offset / 100.0 * base_height * scale


# ---------------------------------------------------------------------------
# Attachment
# ---------------------------------------------------------------------------

def _child_of(obj):
    for con in obj.constraints:
        if con.type == "CHILD_OF" and con.name.startswith(CONSTRAINT_NAME):
            return con
    return None


def detach(obj):
    """Remove parent / Child Of, keep the world transform."""
    world = obj.matrix_world.copy()
    con = _child_of(obj)
    if con is not None:
        obj.constraints.remove(con)
    obj.parent = None
    obj.matrix_world = world


def attach(obj, target, mode):
    """Attach ``obj`` to ``target`` keeping its world transform. Converts the
    stored anchor / normal into target space."""
    state = obj.cs_charm
    anchor_w, normal_w = world_anchor(obj)
    detach(obj)
    if target is None or mode == "NONE" or target == obj:
        state.target = None
        state.attach = "NONE"
    else:
        state.target = target
        state.attach = mode
        world = obj.matrix_world.copy()
        if mode == "PARENT":
            obj.parent = target
            obj.matrix_parent_inverse = target.matrix_world.inverted()
            obj.matrix_world = world
        else:
            con = obj.constraints.new("CHILD_OF")
            con.name = CONSTRAINT_NAME
            con.target = target
            con.inverse_matrix = target.matrix_world.inverted()
            obj.matrix_basis = world
    store_anchor(obj, anchor_w, normal_w)


def world_anchor(obj):
    """Stored anchor point and normal in world space."""
    state = obj.cs_charm
    anchor, normal = Vector(state.anchor), Vector(state.normal)
    if state.target is not None and state.attach != "NONE":
        mw = state.target.matrix_world
        anchor = mw @ anchor
        normal = (mw.inverted().transposed().to_3x3() @ normal).normalized()
    return anchor, normal


def store_anchor(obj, anchor_w, normal_w):
    """Store a world anchor / normal (converted into target space)."""
    state = obj.cs_charm
    anchor, normal = Vector(anchor_w), Vector(normal_w)
    if state.target is not None and state.attach != "NONE":
        mw = state.target.matrix_world
        inv = mw.inverted()
        anchor = inv @ anchor
        normal = (mw.transposed().to_3x3() @ normal).normalized()
    state.anchor = anchor
    state.normal = normal


def place(obj, location, normal, settings, target=None, scale=None, rotation=None):
    """Initial placement of a new charm from the placement settings."""
    global _suspend
    state = obj.cs_charm
    _suspend += 1
    try:
        state.scale = charm_scale(settings, state.base_height, target) if scale is None else scale
        state.rotation = settings.rotation if rotation is None else rotation
        state.offset = settings.offset
        state.align = settings.align
        state.tilt = state.lean = 0.0
        state.placed = True
        state.target = None
        state.attach = "NONE"
        store_anchor(obj, location, normal)
    finally:
        _suspend -= 1
    update_transform(obj)
    if target is not None and settings.attach != "NONE":
        attach(obj, target, settings.attach)


def placement_matrix(obj):
    """World matrix from the stored placement."""
    state = obj.cs_charm
    anchor, normal = world_anchor(obj)
    anchor = anchor + normal * offset_distance(state, state.base_height, state.scale)
    return orientation_matrix(anchor, normal, state.align, state.rotation, state.tilt, state.lean, state.scale)


def update_transform(obj):
    """Apply the stored placement for the current attach mode."""
    state = obj.cs_charm
    if not state.placed:
        return
    world = placement_matrix(obj)
    con = _child_of(obj)
    if con is not None and con.target is not None:
        # world = target @ inverse @ basis (Child Of with set inverse)
        obj.matrix_basis = (con.target.matrix_world @ con.inverse_matrix).inverted() @ world
    else:
        obj.matrix_world = world
    if state.physics:
        from . import physics
        physics.sync_helpers(obj)


def on_transform_changed(obj):
    if _suspend:
        return
    # Make sure the target's matrix is current before reading it.
    if obj.cs_charm.target is not None:
        bpy.context.view_layer.update()
    update_transform(obj)


def adopt_current_transform(obj):
    """Take the object's current location as new anchor (e.g. after the user
    moved the charm with G). Keeps the stored normal."""
    _anchor, normal = world_anchor(obj)
    state = obj.cs_charm
    loc = obj.matrix_world.translation - normal * offset_distance(state, state.base_height, state.scale)
    store_anchor(obj, loc, normal)
