# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Placement math shared by all spawn paths: surface ray casts, the charm's
orientation at an attachment point, attaching to a target and re-applying
the stored placement when the user edits it in the Active Charm panel.

A charm's origin is its attachment point (top of the chain); the model
hangs along -Z and its face looks along +X (CS2 models sit almost entirely
in front of the origin). On upward-facing surfaces a hanging charm rests
on the surface instead of passing through it.

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


REST_THRESHOLD = 0.05  # normal.z above which a hanging charm rests on the surface
REST_FALLBACK_WEIGHT = 0.1  # pull toward the rest direction on (nearly) flat tops


def _in_plane(v, n):
    """``v`` projected into the plane with normal ``n`` (may be zero)."""
    return v - v.dot(n) * n


def orientation_matrix(location, normal, align="HANG", rotation=0.0, tilt=0.0, lean=0.0, scale=1.0,
                       rest_dir=None):
    """World matrix of a charm whose attachment point sits at ``location``.

    HANG:    on walls and overhangs local -Z points down and the face (+X)
             looks away from the surface. On upward-facing surfaces the
             charm cannot hang through the object, so it rests on it: back
             on the surface, face up, lying downhill. On (nearly) flat tops
             it lies toward ``rest_dir`` (world vector, e.g. toward the
             target's center), or -Y without one. Both cases meet at
             vertical walls.
    SURFACE: local -Z points along the surface normal (away from it)
    ``rotation`` turns around the hanging axis (around the normal when
    resting), ``tilt`` swings sideways (around the face axis), ``lean``
    toward / away from the surface.
    """
    n = Vector(normal)
    n = n.normalized() if n.length > 1e-9 else WORLD_UP.copy()
    spin = rotation
    if align == "SURFACE":
        z = -n
        x = (WORLD_UP - WORLD_UP.dot(z) * z)
        x = x.normalized() if x.length > 1e-6 else _perpendicular(z)
    elif n.z > REST_THRESHOLD:
        down = _in_plane(-WORLD_UP, n)  # downhill, zero on a flat top
        fallback = _in_plane(Vector(rest_dir) if rest_dir is not None else Vector((0.0, -1.0, 0.0)), n)
        if fallback.length > 1e-9:
            down += fallback.normalized() * REST_FALLBACK_WEIGHT
        down = down.normalized() if down.length > 1e-9 else _perpendicular(n)
        down = Matrix.Rotation(rotation, 3, n) @ down
        x, z = n, -down
        spin = 0.0
    else:
        z = WORLD_UP.copy()
        x = Vector((n.x, n.y, 0.0))
        x = x.normalized() if x.length > 1e-6 else Vector((1.0, 0.0, 0.0))
    y = z.cross(x).normalized()
    basis = Matrix((x, y, z)).transposed().to_4x4()
    local = (Matrix.Rotation(spin, 4, "Z")
             @ Matrix.Rotation(tilt, 4, "X")
             @ Matrix.Rotation(-lean, 4, "Y"))
    return Matrix.Translation(location) @ basis @ local @ Matrix.Scale(scale, 4)


def back_depth(obj):
    """How far the model reaches behind its attachment point (local -X),
    in model units. Lifting by this keeps the back out of the surface."""
    try:
        return max(0.0, -min(corner[0] for corner in obj.bound_box))
    except (AttributeError, TypeError, ValueError):
        return 0.0


def rest_direction(target, anchor):
    """World direction from ``anchor`` toward the target's center (a charm
    resting on a flat top lies that way, e.g. along a rifle), or None."""
    if target is None:
        return None
    center = sum((Vector(c) for c in target.bound_box), Vector()) / 8.0
    return target.matrix_world @ center - Vector(anchor)


def lift_distance(obj, offset_percent, base_height, scale, align):
    """Distance along the normal from the surface point to the charm origin."""
    lift = offset_percent / 100.0 * base_height * scale
    if align != "SURFACE":
        lift += back_depth(obj) * scale
    return lift


def charm_matrix(obj, anchor, normal, align, rotation=0.0, tilt=0.0, lean=0.0, scale=1.0,
                 offset_percent=0.0, target=None, rest=None):
    """World matrix for ``obj`` attached at a surface point (used by the
    stored placement and the interactive preview alike). ``rest`` is a
    resting rotation from ops/settle.py; without it the orientation comes
    from the surface normal alone."""
    location = attach_point(obj, anchor, normal, align, scale, offset_percent)
    if rest is None:
        n = Vector(normal)
        n = n.normalized() if n.length > 1e-9 else WORLD_UP.copy()
        return orientation_matrix(location, n, align, rotation, tilt, lean, scale,
                                  rest_dir=rest_direction(target, anchor))
    local = Matrix.Rotation(tilt, 4, "X") @ Matrix.Rotation(-lean, 4, "Y")
    return Matrix.Translation(location) @ rest.to_4x4() @ local @ Matrix.Scale(scale, 4)


def attach_point(obj, anchor, normal, align, scale, offset_percent):
    """Charm origin for a surface point: lifted along the normal."""
    n = Vector(normal)
    n = n.normalized() if n.length > 1e-9 else WORLD_UP.copy()
    return Vector(anchor) + n * lift_distance(obj, offset_percent, obj.cs_charm.base_height, scale, align)


def rest_rotation(obj, surface, anchor, normal, rotation, scale, offset_percent, rest_target=None, hull=False):
    """Resting rotation (world 3x3) of ``obj`` on ``surface`` (a
    settle.Surface), or None when it cannot rest there. ``hull``: rest as
    the convex hull physics uses (start pose of the simulation)."""
    from . import settle
    if obj.data is None:
        return None
    pivot = attach_point(obj, anchor, normal, "HANG", scale, offset_percent)
    return settle.solve(surface, obj.data, pivot, normal, scale, rotation,
                        rest_direction(rest_target, anchor), hull)


def resting_surface(obj):
    """Object a hanging charm rests on (its target, else where it was placed)."""
    state = obj.cs_charm
    if state.align != "HANG" or not state.rest_on_surface:
        return None
    surface = state.target if state.attach != "NONE" and state.target is not None else state.surface
    return surface if surface is not None and surface.type == "MESH" else None


def rests_as_hull(obj):
    """With colliding physics the charm rests as its convex hull."""
    state = obj.cs_charm
    return state.physics and state.physics_collide


def _rest_key(obj, surface):
    state = obj.cs_charm
    values = (*state.anchor, *state.normal, state.scale, state.rotation, state.offset)
    return (f"{surface.name_full}|{state.attach}|{len(obj.data.vertices)}|{int(rests_as_hull(obj))}|"
            + ",".join(f"{v:.6g}" for v in values))


def _stored_rest(obj, surface):
    """Resting rotation for the stored placement: cached in surface space
    (follows the surface when it moves), solved again when inputs change."""
    from . import settle
    state = obj.cs_charm
    to_world = surface.matrix_world.to_quaternion().to_matrix()
    key = _rest_key(obj, surface)
    if state.rest_key == key:
        x, z = Vector(state.rest_x), Vector(state.rest_z)
        return to_world @ Matrix((x, z.cross(x), z)).transposed()
    anchor, normal = world_anchor(obj)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    rest = rest_rotation(obj, settle.Surface(surface, depsgraph), anchor, normal, state.rotation, state.scale,
                         state.offset, surface, rests_as_hull(obj))
    if rest is None:
        state.rest_key = ""
        return None
    local = to_world.transposed() @ rest
    state.rest_x = local.col[0]
    state.rest_z = local.col[2]
    state.rest_key = key
    return rest


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
        state.rest_on_surface = settings.rest_on_surface
        state.surface = target
        state.rest_key = ""
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
        update_transform(obj)  # the target sets the rest direction on flat tops


def placement_matrix(obj):
    """World matrix from the stored placement."""
    state = obj.cs_charm
    anchor, normal = world_anchor(obj)
    target = state.target if state.attach != "NONE" else None
    surface = resting_surface(obj)
    rest = _stored_rest(obj, surface) if surface is not None else None
    return charm_matrix(obj, anchor, normal, state.align, state.rotation, state.tilt, state.lean, state.scale,
                        state.offset, target, rest)


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
    loc = obj.matrix_world.translation - normal * lift_distance(obj, state.offset, state.base_height, state.scale,
                                                                 state.align)
    store_anchor(obj, loc, normal)
