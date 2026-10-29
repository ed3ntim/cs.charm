# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Optional pendulum physics: the charm swings from its attachment point.

Setup (Blender rigid bodies, Bullet):

    target ── parent ── "<charm> Anchor"   tiny mesh, passive + animated
                           └─ "<charm> Pivot"  empty, Point constraint
                                               (Anchor <-> charm)
    charm                  active rigid body, convex hull, small margin

The anchor follows the target (parented), so moving or animating the
weapon makes the charm swing. Collisions between anchor and charm are
disabled. Play the timeline (or bake the rigid body cache) to simulate.
Rigid bodies ignore parenting, so the charm itself is detached while
physics is on; removing physics re-attaches it.
"""

from contextlib import contextmanager

import bpy
from mathutils import Vector

from .. import utils
from . import placement as P

HELPER_SIZE = 0.0005  # anchor half size in meters (scaled with the charm)


@contextmanager
def _override(context, obj):
    """Run rigid body operators on ``obj``. Blender 4.5's constraint_add
    reads the view layer's active object and ignores the context override
    (crashes when there is none), so that is set too and restored after."""
    layer_objects = context.view_layer.objects
    previous = layer_objects.active
    layer_objects.active = obj
    try:
        with context.temp_override(object=obj, active_object=obj, selected_objects=[obj],
                                   selected_editable_objects=[obj]):
            yield
    finally:
        try:
            if previous is None or previous.name in layer_objects:
                layer_objects.active = previous
        except ReferenceError:  # removed meanwhile
            pass


def ensure_world(context):
    scene = context.scene
    if scene.rigidbody_world is None:
        with context.temp_override(scene=scene):
            bpy.ops.rigidbody.world_add()
    world = scene.rigidbody_world
    # Charms are a few centimeters: more substeps keep the pendulum stable.
    if hasattr(world, "substeps_per_frame"):
        world.substeps_per_frame = max(world.substeps_per_frame, 20)
    world.solver_iterations = max(world.solver_iterations, 20)
    cache = world.point_cache
    cache.frame_start = min(cache.frame_start, scene.frame_start)
    cache.frame_end = max(cache.frame_end, scene.frame_end)
    return world


def _anchor_mesh(size):
    import bmesh
    mesh = bpy.data.meshes.new("CS Charm Anchor")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=size * 2.0)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _new_helper(context, name, data, location, parent):
    obj = bpy.data.objects.new(name, data)
    obj[utils.PROP_HELPER] = True
    utils.charm_collection(context).objects.link(obj)
    obj.location = location
    if parent is not None:
        obj.parent = parent
        obj.matrix_parent_inverse = parent.matrix_world.inverted()
    obj.hide_render = True
    return obj


def has_physics(obj):
    return obj.cs_charm.physics and obj.rigid_body is not None


def add_physics(context, obj):
    """Turn a placed charm into a swinging rigid body. Returns the anchor."""
    state = obj.cs_charm
    if has_physics(obj):
        return state.physics_anchor
    ensure_world(context)
    context.view_layer.update()
    anchor_w, _normal = P.world_anchor(obj)
    pivot_w = obj.matrix_world.translation.copy()
    target = state.target

    # The charm: unattached active rigid body.
    keep_target, keep_mode = state.target, state.attach
    P.detach(obj)
    with _override(context, obj):
        bpy.ops.rigidbody.object_add(type="ACTIVE")
    rb = obj.rigid_body
    rb.mass = 0.01
    rb.collision_shape = "CONVEX_HULL"
    rb.use_margin = True
    rb.collision_margin = 0.0002 * max(state.scale, 1e-3)
    rb.linear_damping = 0.35
    rb.angular_damping = 0.55
    rb.friction = 0.2

    # Anchor: passive, animated, parented to the target.
    size = HELPER_SIZE * max(state.scale, 1e-3)
    anchor = _new_helper(context, f"{obj.name} Anchor", _anchor_mesh(size), pivot_w, target)
    anchor.display_type = "WIRE"
    with _override(context, anchor):
        bpy.ops.rigidbody.object_add(type="PASSIVE")
    anchor.rigid_body.kinematic = True
    anchor.rigid_body.collision_shape = "BOX"

    # Pivot: Point constraint between anchor and charm.
    pivot = _new_helper(context, f"{obj.name} Pivot", None, pivot_w, anchor)
    pivot.empty_display_type = "SPHERE"
    pivot.empty_display_size = size * 4.0
    with _override(context, pivot):
        bpy.ops.rigidbody.constraint_add(type="POINT")
    con = pivot.rigid_body_constraint
    con.object1 = anchor
    con.object2 = obj
    con.disable_collisions = True

    state.physics = True
    state.physics_anchor = anchor
    state.physics_pivot = pivot
    # Keep target and mode for re-attaching later; the anchor stays in
    # target space so editing the placement still works.
    state.target, state.attach = keep_target, keep_mode
    P.store_anchor(obj, anchor_w, _normal)
    return anchor


def sync_helpers(obj):
    """Move anchor / pivot to the charm's rest attachment point."""
    state = obj.cs_charm
    point = P.placement_matrix(obj).translation
    # Anchor first: the pivot is its child.
    for helper in (state.physics_anchor, state.physics_pivot):
        if helper is not None:
            m = helper.matrix_world.copy()
            m.translation = point
            helper.matrix_world = m


def remove_physics(context, obj):
    """Remove rigid body and helpers, re-attach as before."""
    state = obj.cs_charm
    for helper in (state.physics_pivot, state.physics_anchor):
        if helper is None:
            continue
        data = helper.data
        bpy.data.objects.remove(helper, do_unlink=True)
        if data is not None and data.users == 0:
            bpy.data.meshes.remove(data)
    if obj.rigid_body is not None:
        with _override(context, obj):
            bpy.ops.rigidbody.object_remove()
    state.physics_anchor = None
    state.physics_pivot = None
    state.physics = False
    target, mode = state.target, state.attach
    # Back to the rest pose, then attach again.
    state.target, state.attach = None, "NONE"
    anchor, normal = Vector(state.anchor), Vector(state.normal)
    if target is not None and mode != "NONE":
        anchor = target.matrix_world @ anchor
        normal = (target.matrix_world.inverted().transposed().to_3x3() @ normal).normalized()
    P.store_anchor(obj, anchor, normal)
    P.update_transform(obj)
    if target is not None and mode != "NONE":
        P.attach(obj, target, mode)


def delete_charm(context, obj):
    """Delete a charm with its physics helpers."""
    if obj.cs_charm.physics:
        remove_physics(context, obj)
    mesh = obj.data
    mats = [m for m in mesh.materials if m] if mesh else []
    bpy.data.objects.remove(obj, do_unlink=True)
    if mesh is not None and mesh.users == 0 and utils.PROP_MODEL not in mesh:
        bpy.data.meshes.remove(mesh)
    for m in mats:
        if m.users == 0:
            bpy.data.materials.remove(m)
