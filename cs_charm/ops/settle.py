# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Resting pose of a hanging charm on the object around its attachment point.

A charm hangs from its attachment point (the origin) and swings freely
around it. Gravity pulls it as low as it can go; the object it is attached
to stops it. ``solve`` searches the lowest hanging direction in which the
charm does not cut into the object:

* Candidate directions for the charm's hanging axis (model -Z) cover the
  sphere around the attachment point and are tried lowest first. The
  charm's face (+X) turns toward a reference direction (the surface normal,
  turned by the charm's rotation), so it stays readable.
* A candidate is free when no ray from the attachment point to a point on
  the charm's hull hits the object first. Rays work on open and
  non-manifold meshes (game models) where inside/outside tests do not.
* The best free direction is refined in two smaller cones.

* With physics, the rest pose is the start of the simulation, where the
  charm is its convex hull: points of the object (vertices and points
  along its edges) must also stay outside that hull, or the solver would
  start with the charm stuck in the collider and it would jump away.

On a wall the charm simply hangs down, on a flat top it lies flat, on a
sphere it lies along the curvature, near an edge it hangs over the edge.
"""

import math

import bmesh
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

WORLD_UP = Vector((0.0, 0.0, 1.0))
HULL_DIRECTIONS = 96     # support directions for the hull sample points
COARSE = 260             # candidate hanging directions on the sphere
FINE = 40                # candidates per refinement cone
REFINE_ANGLES = (math.radians(12.0), math.radians(3.0))
LEVEL_BAND = math.radians(1.5)  # directions this close in elevation count as level
MAX_UP = 0.9             # never point the charm (almost) straight up
CHECK_POINTS = 1500      # vertices for the final, finer collision check
LIFT_STEP = math.radians(0.5)
MAX_LIFT = math.radians(20.0)
RING_RADIUS = 0.15       # hull mode ignores the object this close to the pivot
# Rolls around the hanging axis, preferred order (face toward the reference).
ROLLS = tuple(math.radians(a) for a in (12, -12, 25, -25, 40, -40))
ROLL_STEP = math.radians(6.0)
ROLL_RANGE = math.radians(35.0)  # how much lower a rolled pose may go

_points_cache = {}


def _fibonacci(count):
    golden = math.pi * (3.0 - math.sqrt(5.0))
    for i in range(count):
        z = 1.0 - 2.0 * (i + 0.5) / count
        r = math.sqrt(max(0.0, 1.0 - z * z))
        yield Vector((r * math.cos(golden * i), r * math.sin(golden * i), z))


def _cone(axis, angle, count):
    """``axis`` plus ``count`` directions within ``angle`` of it."""
    basis = axis.to_track_quat("Z", "Y").to_matrix()
    golden = math.pi * (3.0 - math.sqrt(5.0))
    cos_max = math.cos(angle)
    out = [axis.copy()]
    for i in range(count):
        z = 1.0 - (1.0 - cos_max) * (i + 0.5) / count
        r = math.sqrt(max(0.0, 1.0 - z * z))
        out.append((basis @ Vector((r * math.cos(golden * i), r * math.sin(golden * i), z))).normalized())
    return out


def hull_points(mesh):
    """Points on the charm's convex hull (model space, unscaled), lowest
    first: the far end is where a charm usually touches first."""
    key = (mesh.name_full, len(mesh.vertices))
    cached = _points_cache.get(key)
    if cached is not None:
        return cached
    count = len(mesh.vertices)
    if count == 0:
        return []
    co = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(count, 3)
    dirs = np.array([tuple(d) for d in _fibonacci(HULL_DIRECTIONS)])
    idx = np.unique(np.argmax(co @ dirs.T, axis=0))
    pts = co[idx]
    pts = pts[np.argsort(pts[:, 2])]
    out = [Vector(p) for p in pts]
    _points_cache[key] = out
    return out


def check_points(mesh):
    """Up to CHECK_POINTS vertices (model space) for the final check: the
    hull samples can miss a corner that touches first."""
    key = ("check", mesh.name_full, len(mesh.vertices))
    cached = _points_cache.get(key)
    if cached is not None:
        return cached
    count = len(mesh.vertices)
    co = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(count, 3)
    if count > CHECK_POINTS:
        co = co[np.linspace(0, count - 1, CHECK_POINTS).astype(int)]
    out = [Vector(p) for p in co]
    _points_cache[key] = out
    return out


def hull_planes(mesh):
    """Planes (normals F x 3, offsets F) of the convex hull of ``mesh``
    (model space): inside means ``normals @ p < offsets`` for all."""
    key = ("planes", mesh.name_full, len(mesh.vertices))
    cached = _points_cache.get(key)
    if cached is not None:
        return cached
    bm = bmesh.new()
    for v in mesh.vertices:
        bm.verts.new(v.co)
    out = (np.zeros((0, 3)), np.zeros(0))
    if len(bm.verts) >= 4:
        result = bmesh.ops.convex_hull(bm, input=list(bm.verts))
        faces = [f for f in result["geom"] if isinstance(f, bmesh.types.BMFace)]
        normals, offsets = [], []
        for f in faces:
            f.normal_update()
            if f.normal.length < 0.5:
                continue
            normals.append(tuple(f.normal))
            offsets.append(f.normal.dot(f.verts[0].co))
        if normals:
            out = (np.array(normals), np.array(offsets))
    bm.free()
    _points_cache[key] = out
    return out


def frame(down, face_ref):
    """Rotation whose -Z is ``down`` and whose +X is as close as possible
    to ``face_ref``."""
    z = -down
    x = face_ref - face_ref.dot(z) * z
    if x.length < 1e-6:
        other = Vector((1.0, 0.0, 0.0)) if abs(z.x) < 0.9 else Vector((0.0, 1.0, 0.0))
        x = z.cross(other)
    x.normalize()
    y = z.cross(x)
    return Matrix((x, y, z)).transposed()


class Surface:
    """Ray caster for one object (local space BVH of the evaluated mesh)."""

    def __init__(self, obj, depsgraph):
        self.obj = obj
        self.bvh = BVHTree.FromObject(obj, depsgraph)
        self.matrix = obj.matrix_world.copy()
        self.inverse = self.matrix.inverted_safe()
        self.depsgraph = depsgraph
        self._samples = {}

    def points_near(self, center_w, radius_w, spacing_w):
        """World points of the object within ``radius_w`` of ``center_w``:
        vertices plus points along the edges, at most ``spacing_w`` apart."""
        scale = max(self.matrix.to_scale()) or 1.0
        spacing = spacing_w / scale
        key = round(math.log(max(spacing, 1e-9), 1.25))
        tree = self._samples.get(key)
        if tree is None:
            tree = self._build_samples(1.25 ** key)
            self._samples[key] = tree
        found = tree.find_range(self.inverse @ Vector(center_w), radius_w / scale * 1.01)
        if not found:
            return np.zeros((0, 3))
        local = np.array([tuple(co) for co, _i, _d in found])
        m = np.array(self.matrix)
        return local @ m[:3, :3].T + m[:3, 3]

    def _build_samples(self, spacing):
        evaluated = self.obj.evaluated_get(self.depsgraph)
        mesh = evaluated.to_mesh()
        try:
            count = len(mesh.vertices)
            co = np.empty(count * 3)
            mesh.vertices.foreach_get("co", co)
            co = co.reshape(count, 3)
            edges = np.empty(len(mesh.edges) * 2, dtype=np.int64)
            mesh.edges.foreach_get("vertices", edges)
            edges = edges.reshape(-1, 2)
        finally:
            evaluated.to_mesh_clear()
        a, b = co[edges[:, 0]], co[edges[:, 1]]
        steps = np.maximum(1, np.ceil(np.linalg.norm(b - a, axis=1) / spacing).astype(np.int64))
        long = steps > 1
        pieces = [co]
        if long.any():
            # Interior points k / n (k = 1 .. n-1) of every long edge.
            a, b, n = a[long], b[long], steps[long]
            edge = np.repeat(np.arange(len(n)), n - 1)
            first = np.repeat(np.cumsum(n - 1) - (n - 1), n - 1)
            k = np.arange(len(edge)) - first + 1
            t = (k / n[edge])[:, None]
            pieces.append(a[edge] + (b[edge] - a[edge]) * t)
        pts = np.concatenate(pieces)
        tree = KDTree(len(pts))
        for i, p in enumerate(pts):
            tree.insert(p, i)
        tree.balance()
        return tree

    def blocked(self, origin_w, points_w, tol):
        """True if a segment from ``origin_w`` to any point hits the object
        more than ``tol`` (world units) before reaching the point."""
        inv = self.inverse
        o = inv @ origin_w
        for p in points_w:
            q = inv @ p
            seg = q - o
            length = seg.length
            if length < 1e-12:
                continue
            # Shorten by tol, measured in local units along this segment.
            world_len = (p - origin_w).length
            reach = length * max(0.0, 1.0 - tol / world_len) if world_len > 0 else 0.0
            if reach <= 0.0:
                continue
            hit = self.bvh.ray_cast(o, seg / length, reach)
            if hit[0] is not None:
                return True
        return False


def solve(surface, mesh, pivot_w, normal_w, scale, rotation=0.0, rest_dir=None, hull=False):
    """Rotation (3x3, world) of the resting charm, or None if every
    direction is blocked (attachment point inside the object). ``hull``:
    also keep the object out of the charm's convex hull (physics start)."""
    pts = hull_points(mesh)
    if not pts:
        return None
    n = Vector(normal_w).normalized()
    turn = Matrix.Rotation(rotation, 3, WORLD_UP)
    face_ref = turn @ n
    pref = Vector(rest_dir) if rest_dir is not None else Vector((0.0, -1.0, 0.0))
    pref = turn @ Vector((pref.x, pref.y, 0.0))
    pref = pref.normalized() if pref.length > 1e-9 else Vector((0.0, -1.0, 0.0))

    size = max((p.length for p in pts), default=0.0) * scale
    tol = 0.002 * size
    origin = Vector(pivot_w) + n * (0.004 * size)
    local = [p * scale for p in pts]

    def pose(d, roll):
        rot = frame(d, face_ref)
        return rot @ Matrix.Rotation(roll, 3, "Z") if roll else rot

    near = np.zeros((0, 3))
    if hull:
        normals, offsets = hull_planes(mesh)
        if len(offsets):
            near = surface.points_near(pivot_w, size, size / 25.0) - np.array(tuple(pivot_w))
            # The ring around the attachment point is held there anyway.
            near = near[np.linalg.norm(near, axis=1) > RING_RADIUS * size]
            offsets = offsets * scale - tol

    def in_hull(rot):
        if not len(near):
            return False
        local = near @ np.array(rot)  # rot^T @ p for every row
        return bool(np.any(np.all(local @ normals.T < offsets, axis=1)))

    def fits(rot, points):
        if surface.blocked(origin, [pivot_w + rot @ p for p in points], tol):
            return False
        return not in_hull(rot)

    def free(d, rolls):
        """First roll around the hanging axis that fits, or None. Rolling
        lets a wide charm lie on a curved or slanted surface."""
        for roll in rolls:
            if fits(pose(d, roll), local):
                return roll
        return None

    def search(candidates, rolls=(0.0,), floor=-math.pi):
        """Lowest free direction; among the free ones about as low, the one
        closest to the rest direction (a charm on a flat top lies toward
        the center, not wherever the sampling happens to be lowest)."""
        lowest = None
        best = None
        for d in sorted(candidates, key=lambda c: c.z):
            if d.z > MAX_UP:
                break
            elevation = math.asin(max(-1.0, min(1.0, d.z)))
            if elevation < floor:
                continue
            if lowest is not None and elevation > lowest + LEVEL_BAND:
                break
            roll = free(d, rolls)
            if roll is None:
                continue
            if lowest is None:
                lowest = elevation
            if best is None or d.dot(pref) > best[0].dot(pref) + 1e-9:
                best = (d, roll)
        return best

    def elevation_of(d):
        return math.asin(max(-1.0, min(1.0, d.z)))

    def toward_rest(angles):
        return [pref * math.cos(a) + Vector((0.0, 0.0, math.sin(a))) for a in angles]

    steps = [math.radians(a) for a in range(-90, 91, 5)]
    coarse = [Vector((0.0, 0.0, -1.0))] + toward_rest(steps) + list(_fibonacci(COARSE))
    # Without rolling first; then rolled poses only where they can go lower.
    best = search(coarse)
    if best is None or elevation_of(best[0]) > -math.pi / 2 + LEVEL_BAND:
        floor = -math.pi if best is None else elevation_of(best[0]) - ROLL_RANGE
        rolled = search([d for d in coarse if best is None or d.z < best[0].z], ROLLS, floor)
        if rolled is not None and (best is None or rolled[0].z < best[0].z):
            best = rolled
    if best is None:
        # No pose keeps the object out of the hull: rest like without physics.
        return solve(surface, mesh, pivot_w, normal_w, scale, rotation, rest_dir) if hull else None
    for angle in REFINE_ANGLES:
        found = search(_cone(best[0], angle, FINE) + [best[0]], (best[1],))
        if found is not None:
            best = found

    # Final check with the vertices: roll a little, else turn the charm away
    # from the surface (up to MAX_LIFT), until nothing cuts in.
    d, roll = best
    fine = [p * scale for p in check_points(mesh)]
    axis = d.cross(n)
    rolls = (roll, roll + ROLL_STEP, roll - ROLL_STEP)
    for _ in range(int(MAX_LIFT / LIFT_STEP)):
        for r in rolls:
            if fits(pose(d, r), fine):
                return pose(d, r)
        if axis.length < 1e-9 or d.z > MAX_UP:
            break
        d = (Matrix.Rotation(LIFT_STEP, 3, axis.normalized()) @ d).normalized()
    return pose(best[0], best[1])
