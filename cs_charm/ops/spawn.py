# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Creating charm objects: glTF import, material setup, patterns.

The first spawn of a model imports the .glb with Blender's glTF importer,
joins its meshes (body + chain) into one mesh and keeps that mesh as a
template; later spawns copy the template mesh, so placing many charms stays
fast. Each charm gets its own materials (its own pattern).

Material per glTF slot, in this order:
1. the catalog spec for the slot (static params + DynamicParams),
2. a spec built from the Source2Viewer ``vmat`` extras in the glTF,
3. the importer's own PBR material (fallback for non-CS2 models).
"""

import json
import os

import bpy
from mathutils import Matrix

from .. import utils
from ..library import catalog as C
from ..library import gltf, patterns
from ..library import registry
from ..nodes import material as M

_templates = {}  # model path -> template mesh name


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


# ---------------------------------------------------------------------------
# glTF import
# ---------------------------------------------------------------------------

def _import_gltf(path):
    """Import a glTF file, return one joined mesh (data block) and the
    importer's materials per slot. Imported objects are removed again."""
    before_objs = set(bpy.data.objects)
    before_meshes = set(bpy.data.meshes)
    result = bpy.ops.import_scene.gltf(filepath=path)
    if "FINISHED" not in result:
        raise RuntimeError(f"glTF import failed: {path}")
    new_objs = [o for o in bpy.data.objects if o not in before_objs]
    meshes = [o for o in new_objs if o.type == "MESH" and o.data is not None]
    if not meshes:
        for o in new_objs:
            bpy.data.objects.remove(o, do_unlink=True)
        raise RuntimeError(f"no mesh in {os.path.basename(path)}")

    # Bake object transforms (glTF Y-up conversion, node hierarchy) into
    # the meshes, then join them. Joining by hand keeps this independent of
    # the active view layer / context.
    import bmesh
    bm = bmesh.new()
    slots = []          # material per slot of the joined mesh
    slot_index = {}     # material -> slot
    for obj in meshes:
        mesh = obj.data
        tmp = mesh.copy()
        tmp.transform(obj.matrix_world)
        remap = []
        for mat in mesh.materials:
            if mat not in slot_index:
                slot_index[mat] = len(slots)
                slots.append(mat)
            remap.append(slot_index[mat])
        offset = len(bm.faces)
        bm.from_mesh(tmp)
        bm.faces.ensure_lookup_table()
        for face in bm.faces[offset:]:
            if remap:
                face.material_index = remap[min(face.material_index, len(remap) - 1)]
        bpy.data.meshes.remove(tmp)
    joined = bpy.data.meshes.new(os.path.splitext(os.path.basename(path))[0])
    bm.to_mesh(joined)
    bm.free()
    for mat in slots:
        joined.materials.append(mat)

    for o in new_objs:
        bpy.data.objects.remove(o, do_unlink=True)
    for mesh in [m for m in bpy.data.meshes if m not in before_meshes and m is not joined]:
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    return joined


def _slot_info(mesh):
    """[(glTF material name, vmat extras dict or None)] per mesh slot."""
    raw = mesh.get(utils.PROP_SLOTS)
    if raw:
        try:
            return [tuple(x) for x in json.loads(raw)]
        except ValueError:
            pass
    info = []
    for mat in mesh.materials:
        vmat = None
        if mat is not None and "vmat" in mat:
            try:
                vmat = mat["vmat"].to_dict()
            except AttributeError:
                vmat = dict(mat["vmat"]) if isinstance(mat["vmat"], dict) else None
        info.append((mat.name if mat else "", vmat))
    return info


def template_mesh(charm):
    """Mesh data block for a charm model (imported once per file)."""
    key = os.path.normcase(os.path.abspath(charm.model))
    name = _templates.get(key)
    mesh = bpy.data.meshes.get(name) if name else None
    if mesh is not None and mesh.get(utils.PROP_MODEL) == key \
            and abs(mesh.get("cs_charm_mtime", 0.0) - _mtime(charm.model)) < 1e-3:
        return mesh, False
    mesh = _import_gltf(charm.model)
    info = _slot_info(mesh)
    # Material names in the glTF are unique per file; strip Blender's ".001".
    info = [(_strip_suffix(n), v) for n, v in info]
    mesh[utils.PROP_SLOTS] = json.dumps(info)
    mesh[utils.PROP_MODEL] = key
    mesh["cs_charm_mtime"] = _mtime(charm.model)
    _templates[key] = mesh.name
    return mesh, True


def _strip_suffix(name):
    head, _, tail = name.rpartition(".")
    return head if head and tail.isdigit() and len(tail) == 3 else name


def _liquid_range(mesh, slot):
    """Object-space Z range of the faces using material ``slot``."""
    zs = [mesh.vertices[v].co.z for poly in mesh.polygons if poly.material_index == slot
          for v in poly.vertices]
    if not zs:
        return None
    return min(zs), max(zs)


def _spec_for_slot(charm, slot_name, vmat):
    spec = charm.slots.get(slot_name)
    if spec is not None:
        return spec
    if vmat:
        data = gltf.spec_from_vmat_extras(vmat, os.path.dirname(charm.model))
        if data["shader"] in (C.SHADER_WEAPON, C.SHADER_LIQUID):
            return C.MaterialSpec.from_dict(data["vmat"] or f"{charm.id}:{slot_name}", data)
    return None


def _cleanup_importer_materials(materials):
    for mat in materials:
        if mat is not None and mat.users == 0 and not M.is_charm_material(mat):
            images = [n.image for n in (mat.node_tree.nodes if mat.node_tree else ())
                      if n.type == "TEX_IMAGE" and n.image]
            bpy.data.materials.remove(mat)
            for img in images:
                if img.users == 0:
                    bpy.data.images.remove(img)


# ---------------------------------------------------------------------------
# Charm objects
# ---------------------------------------------------------------------------

def setup_materials(obj, charm, pattern):
    """Give ``obj`` its own charm materials. Returns warnings."""
    warnings = []
    mesh = obj.data
    info = _slot_info(mesh)
    replaced = []
    for i, (slot_name, vmat) in enumerate(info):
        if i >= len(mesh.materials):
            break
        spec = _spec_for_slot(charm, slot_name, vmat)
        old = mesh.materials[i]
        if spec is None:
            continue  # importer PBR material stays (fallback)
        liquid_range = _liquid_range(mesh, i) if spec.is_liquid else None
        mat, warn = M.build_material(spec, f"{charm.name} {slot_name}", pattern, liquid_range)
        warnings += warn
        mesh.materials[i] = mat
        replaced.append(old)
    _cleanup_importer_materials(replaced)
    return warnings


def create_charm_object(context, charm, pattern=0):
    """New charm object at the world origin (attachment point = origin).
    Returns (object, warnings)."""
    if not charm.model or not os.path.isfile(charm.model):
        raise RuntimeError(f"model not found: {charm.model or charm.name}")
    template, fresh = template_mesh(charm)
    mesh = template if fresh else template.copy()
    if not fresh:
        mesh.materials.clear()
        for mat in template.materials:
            mesh.materials.append(mat)
    mesh.name = charm.name
    obj = bpy.data.objects.new(charm.name, mesh)
    utils.charm_collection(context).objects.link(obj)
    obj[utils.PROP_CHARM_ID] = charm.id
    state = obj.cs_charm
    state.charm_id = charm.id
    state["pattern"] = int(pattern)  # bypass update: materials are built below
    zs = [v.co.z for v in mesh.vertices]
    state.base_height = (max(zs) - min(zs)) if zs else 0.05
    obj.matrix_world = Matrix.Identity(4)
    warnings = setup_materials(obj, charm, pattern)
    return obj, warnings


def charm_of(obj):
    """Catalog entry of a charm object (None if the library lacks it)."""
    if not utils.is_charm(obj):
        return None
    return registry.get_catalog().get(obj.get(utils.PROP_CHARM_ID, ""))


def apply_pattern(obj, pattern=None):
    """Re-evaluate the pattern for all charm materials of ``obj``."""
    if pattern is None:
        pattern = obj.cs_charm.pattern
    if obj.data is None:
        return
    for mat in obj.data.materials:
        spec = M.spec_from_material(mat)
        if spec is not None:
            M.apply_pattern(mat, spec, pattern)


def on_pattern_changed(obj):
    apply_pattern(obj)


def rebuild_materials(obj):
    """Rebuild the materials from the library (resets manual tweaks).
    Returns warnings or raises if the charm is not in the library."""
    charm = charm_of(obj)
    if charm is None:
        raise RuntimeError("charm not found in the library")
    old = [m for m in obj.data.materials]
    warnings = setup_materials(obj, charm, obj.cs_charm.pattern)
    for mat in old:
        if mat is not None and mat.users == 0:
            bpy.data.materials.remove(mat)
    return warnings


def pick_pattern(settings):
    return patterns.random_pattern() if settings.random_pattern else settings.pattern


def select_only(context, obj):
    for o in context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def report_warnings(op, warnings):
    if warnings:
        op.report({"WARNING"}, f"{len(warnings)} warning(s): {warnings[0]}")
        for w in warnings:
            utils.log.warning(w)
