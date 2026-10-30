# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Optional pendulum physics: the charm swings from its attachment point.

Setup (Blender rigid bodies, Bullet):

    target ── parent ── "<charm> Anchor"   tiny mesh, passive + animated
                           └─ "<charm> Pivot"  empty, Generic Spring
                                               constraint (Anchor <-> charm)
    target ── parent ── "<target> Collider"  shares the target's mesh,
                                             passive + animated, mesh shape
    charm                  active rigid body, convex hull, small margin
    "<charm> Weight"       active, Fixed constraint to the charm: convex
                           hull of the charm body (without ring and
                           chain), collides in place of the charm

The anchor follows the target (parented), so moving or animating the
weapon makes the charm swing. The collider follows it the same way, so the
charm also rests on and bumps against the weapon while it moves; it is a
separate object because the target itself must not become a rigid body
(that would ignore its parenting). One collider per target, shared by all
charms on it. Collisions between anchor and charm are disabled. Play the
timeline (or bake the rigid body cache) to simulate.
Rigid bodies ignore parenting, so the charm itself is detached while
physics is on; removing physics re-attaches it.

Blender takes the object origin as the center of mass. The charm's origin
is its attachment point, so on its own gravity would never make it swing
(it only moved when the collider kicked it). The weight on the hanging
axis, at the middle height of the charm, moves the center of mass there.
It also carries the collision shape: a hull that includes ring and chain
touches the weapon right at the pivot, where contact and constraint fight
each other (jitter).
"""

import math
from contextlib import contextmanager

import bpy
from mathutils import Matrix, Vector

from .. import utils
from . import placement as P

HELPER_SIZE = 0.0005  # anchor half size in meters (scaled with the charm)
WEIGHT_MASS = 3.0  # weight mass in charm masses: center of mass close to the weight
NO_COLLISION_LAYER = 19  # charms with a body (and bodyless weights) only
SETTLE_FRAMES = 90  # pre-simulation for the start pose (settle_start)
SPIN_STIFFNESS = 0.01  # spring on the turn around the hanging axis (ring friction)
SPIN_DAMPING = 1.0
BODY_CLEARANCE = 0.18  # ring and chain parts stay within this share of the charm's reach


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


def ensure_world(context, scale=1.0):
    """Rigid body world of the scene. A new world is set up for charms of
    ``scale`` times their real size (models are in meters): gravity pulls
    9.81 units/s², so in a scene in inches (CS:DIN2 weapons) it is 39 times
    too weak for the charm. Speeding up the simulation by sqrt(scale) gives
    the same motion as gravity scaled by ``scale``, without touching the
    scene's gravity. An existing world is left as it is."""
    scene = context.scene
    if scene.rigidbody_world is None:
        with context.temp_override(scene=scene):
            bpy.ops.rigidbody.world_add()
        scene.rigidbody_world.time_scale = min(max(math.sqrt(max(scale, 1e-6)), 0.1), 10.0)
    world = scene.rigidbody_world
    # Charms are a few centimeters: more substeps keep the pendulum stable
    # and stop the body from slipping through the weapon while it moves.
    if hasattr(world, "substeps_per_frame"):
        world.substeps_per_frame = max(world.substeps_per_frame, 60)
    world.solver_iterations = max(world.solver_iterations, 60)
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


def _local_center(obj):
    """Center of mass in the charm's local space: on the hanging axis
    (model Z through the attachment point) at the height of the bounding
    box middle. Off the axis the charm would settle in another pose than
    the rest pose (ops/settle.py) and jump at the start."""
    middle = sum((Vector(c) for c in obj.bound_box), Vector()) / 8.0
    return Vector((0.0, 0.0, middle.z))


def _weight_matrix(obj, matrix=None):
    m = obj.matrix_world if matrix is None else matrix
    return m @ Matrix.Translation(_local_center(obj))


def _islands(mesh):
    """Vertex indices of each connected part of ``mesh``."""
    parent = list(range(len(mesh.vertices)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for e in mesh.edges:
        a, b = root(e.vertices[0]), root(e.vertices[1])
        if a != b:
            parent[a] = b
    parts = {}
    for i in range(len(parent)):
        parts.setdefault(root(i), []).append(i)
    return list(parts.values())


def _body_mesh(obj):
    """Convex hull of the charm without ring and chain, around the center
    of mass. Ring and chain are separate parts that stay close to the
    attachment point (the origin); a charm in one piece loses the vertices
    there. None when too little is left."""
    import bmesh
    if obj.type != "MESH" or not obj.data.vertices:
        return None
    co = [v.co for v in obj.data.vertices]
    reach = max(p.length for p in co)
    body = [i for part in _islands(obj.data)
            if max(co[i].length for i in part) > reach * BODY_CLEARANCE for i in part]
    if len(body) == len(co):  # one piece: leave out what is close to the pivot
        body = [i for i, p in enumerate(co) if p.length > reach * BODY_CLEARANCE]
    if len(body) < 4:
        return None
    center = _local_center(obj)
    bm = bmesh.new()
    verts = [bm.verts.new(co[i] - center) for i in body]
    bmesh.ops.convex_hull(bm, input=verts, use_existing_faces=False)
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    if len(bm.faces) < 4:
        bm.free()
        return None
    mesh = bpy.data.meshes.new("CS Charm Body")
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _add_weight(context, obj, size):
    """Body at the middle of the charm, fixed to it (see module doc)."""
    mesh = _body_mesh(obj)
    weight = _new_helper(context, f"{obj.name} Weight", mesh or _anchor_mesh(size), (0.0, 0.0, 0.0), None)
    weight.matrix_world = _weight_matrix(obj)
    weight.display_type = "WIRE"
    with _override(context, weight):
        bpy.ops.rigidbody.object_add(type="ACTIVE")
    rb, charm_rb = weight.rigid_body, obj.rigid_body
    rb.mass = charm_rb.mass * WEIGHT_MASS
    if mesh is None:
        rb.collision_shape = "BOX"
        rb.collision_collections = [i == NO_COLLISION_LAYER for i in range(20)]
    else:
        # The body collides instead of the charm: no contact at the pivot.
        rb.collision_shape = "CONVEX_HULL"
        rb.use_margin = True
        rb.collision_margin = charm_rb.collision_margin
        rb.friction = charm_rb.friction
        charm_rb.collision_collections = [i == NO_COLLISION_LAYER for i in range(20)]
    rb.linear_damping = charm_rb.linear_damping
    rb.angular_damping = charm_rb.angular_damping
    with _override(context, weight):
        bpy.ops.rigidbody.constraint_add(type="FIXED")
    con = weight.rigid_body_constraint
    con.object1 = obj
    con.object2 = weight
    con.disable_collisions = True
    weight.hide_set(True)
    return weight


def _collider_users(collider):
    return [o for o in bpy.data.objects if utils.is_charm(o) and o.cs_charm.physics_collider == collider]


def ensure_collider(context, target):
    """Passive mesh collider that follows ``target`` (shared per target
    within a scene: each scene simulates its own rigid body world)."""
    for obj in context.scene.objects:
        if utils.is_helper(obj) and obj.get(utils.PROP_COLLIDER) == target.name_full                 and obj.parent == target and obj.data == target.data:
            return obj
    collider = _new_helper(context, f"{target.name} Collider", target.data, (0.0, 0.0, 0.0), None)
    collider[utils.PROP_COLLIDER] = target.name_full
    collider.parent = target
    collider.matrix_parent_inverse.identity()
    collider.matrix_basis.identity()
    collider.display_type = "WIRE"
    with _override(context, collider):
        bpy.ops.rigidbody.object_add(type="PASSIVE")
    rb = collider.rigid_body
    rb.kinematic = True
    rb.collision_shape = "MESH"
    rb.mesh_source = "BASE"
    rb.use_margin = True
    rb.collision_margin = 0.0
    rb.friction = 0.6
    collider.hide_set(True)
    collider.hide_select = True
    return collider


def _release_collider(collider):
    """Remove a collider no charm uses any more."""
    if collider is None or _collider_users(collider):
        return
    bpy.data.objects.remove(collider, do_unlink=True)


def has_physics(obj):
    return obj.cs_charm.physics and obj.rigid_body is not None


def add_physics(context, obj, settle=True):
    """Turn a placed charm into a swinging rigid body. Returns the anchor.
    With ``settle`` a charm hanging at rest starts in the simulation's own
    balance (see settle_start)."""
    state = obj.cs_charm
    if has_physics(obj):
        return state.physics_anchor
    ensure_world(context, obj.matrix_world.to_scale().x)
    target = state.target
    if state.physics_collide and target is not None and target.type == "MESH":
        # Start from the rest pose of the convex hull, not stuck in the collider.
        state.physics = True
        P.update_transform(obj)
    context.view_layer.update()
    anchor_w, _normal = P.world_anchor(obj)
    pivot_w = obj.matrix_world.translation.copy()

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
    weight = _add_weight(context, obj, HELPER_SIZE * max(state.scale, 1e-3))

    # Anchor: passive, animated, parented to the target.
    size = HELPER_SIZE * max(state.scale, 1e-3)
    anchor = _new_helper(context, f"{obj.name} Anchor", _anchor_mesh(size), pivot_w, target)
    anchor.display_type = "WIRE"
    with _override(context, anchor):
        bpy.ops.rigidbody.object_add(type="PASSIVE")
    anchor.rigid_body.kinematic = True
    anchor.rigid_body.collision_shape = "BOX"
    # Only the charm itself shares this layer, and the pivot disables that.
    anchor.rigid_body.collision_collections = [i == NO_COLLISION_LAYER for i in range(20)]
    # Passive objects never collide with each other: the anchor sits in the
    # collider's surface without trouble.
    collider = None
    if state.physics_collide and target is not None and target.type == "MESH":
        collider = ensure_collider(context, target)
        # Overlaps left at the start would make the charm jump away.
        context.scene.rigidbody_world.use_split_impulse = True

    # Pivot: ball joint between anchor and charm (no translation), with a
    # weak, damped spring on the turn around the hanging axis. A free joint
    # spins like a top after a brush against the weapon; on a real charm
    # the ring's friction stops that.
    pivot = _new_helper(context, f"{obj.name} Pivot", None, pivot_w, anchor)
    pivot.empty_display_type = "SPHERE"
    pivot.empty_display_size = size * 4.0
    with _override(context, pivot):
        bpy.ops.rigidbody.constraint_add(type="GENERIC_SPRING")
    con = pivot.rigid_body_constraint
    con.object1 = anchor
    con.object2 = obj
    con.disable_collisions = True
    con.spring_type = "SPRING2"
    for axis in "xyz":
        setattr(con, f"use_limit_lin_{axis}", True)
        setattr(con, f"limit_lin_{axis}_lower", 0.0)
        setattr(con, f"limit_lin_{axis}_upper", 0.0)
    con.use_spring_ang_z = True
    con.spring_stiffness_ang_z = SPIN_STIFFNESS
    con.spring_damping_ang_z = SPIN_DAMPING

    state.physics = True
    state.physics_anchor = anchor
    state.physics_pivot = pivot
    state.physics_weight = weight
    state.physics_collider = collider
    # Keep target and mode for re-attaching later; the anchor stays in
    # target space so editing the placement still works.
    state.target, state.attach = keep_target, keep_mode
    P.store_anchor(obj, anchor_w, _normal)
    if settle:
        settle_start(context, [obj])
    return anchor


def _frozen_animation(scene):
    """Detach every action in ``scene`` (objects keep their current pose);
    returns a function that puts them back."""
    frozen = []
    for o in scene.objects:
        ad = o.animation_data
        if ad is not None and ad.action is not None and o.rigid_body is None:
            frozen.append((o, ad.action, getattr(ad, "action_slot", None)))
            ad.action = None

    def restore():
        for o, action, slot in frozen:
            o.animation_data.action = action
            if slot is not None and o.animation_data.action_slot != slot:
                o.animation_data.action_slot = slot
    return restore


def settle_start(context, charms, frames=SETTLE_FRAMES):
    """Start charms at rest in the simulation's balance. The rest pose of
    the placement is close, but contact and the real center of mass differ
    a little, and the charm would twitch in the first frames. Simulates
    ``frames`` frames with all animation frozen at the first frame and
    takes the end pose as the start. Charms swung on purpose (tilt or
    lean) are left alone."""
    scene = context.scene
    world = scene.rigidbody_world
    charms = [o for o in charms if has_physics(o) and o.cs_charm.tilt == 0.0 and o.cs_charm.lean == 0.0]
    if world is None or not charms or world.point_cache.is_baked:
        return
    bodies = charms + [o.cs_charm.physics_weight for o in charms if o.cs_charm.physics_weight is not None]
    cache = world.point_cache
    current, start, end = scene.frame_current, cache.frame_start, cache.frame_end
    restore = _frozen_animation(scene)
    try:
        cache.frame_end = start + frames
        scene.frame_set(start)
        for f in range(start + 1, start + frames + 1):
            scene.frame_set(f)
        rest = [(o, o.matrix_world.copy()) for o in bodies]
    finally:
        cache.frame_end = end
        restore()
        scene.frame_set(start)
    for o, m in rest:
        o.matrix_world = m
    world.time_scale = world.time_scale  # resets the simulation cache
    scene.frame_set(current)


def sync_helpers(obj):
    """Move anchor / pivot to the charm's rest attachment point, the
    weight to its middle."""
    state = obj.cs_charm
    rest = P.placement_matrix(obj)
    # Anchor first: the pivot is its child.
    for helper in (state.physics_anchor, state.physics_pivot):
        if helper is not None:
            m = helper.matrix_world.copy()
            m.translation = rest.translation
            helper.matrix_world = m
    if state.physics_weight is not None:
        state.physics_weight.matrix_world = _weight_matrix(obj, rest)


def remove_physics(context, obj):
    """Remove rigid body and helpers, re-attach as before."""
    state = obj.cs_charm
    for helper in (state.physics_pivot, state.physics_weight, state.physics_anchor):
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
    state.physics_weight = None
    collider, state.physics_collider = state.physics_collider, None
    _release_collider(collider)
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
