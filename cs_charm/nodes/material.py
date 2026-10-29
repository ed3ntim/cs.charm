# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Material assembly: one Blender material per charm material slot.

Layout of a charm material::

    UV Map ─┬─────────────── TEX_COLOR / TEX_NORMAL / TEX_METAL / ...
            ├─ CHARM_DETAIL_UV ── TEX_DETAIL      ─┐
            └─ CHARM_GLITTER_UV ─ TEX_GLITTER     ─┼─ CHARM_MAIN ── Output
                                                   ┘

CHARM_MAIN is the "CS2 Charm Weapon" or "CS2 Charm Liquid" group. Static
parameters and the pattern's DynamicParams are written to the group inputs
through library/shading.py. A JSON copy of the spec is stored on the
material so patterns can be changed in saved files without the library.
"""

import json
import os

import bpy

from .. import utils
from ..library import catalog as C
from ..library import shading as S
from . import groups

_TEX_PREFIX = "TEX_"


def _load_image(path, colorspace):
    """Load (or reuse) a texture. CS2 textures carry data in alpha or have
    alpha 0 (normal and detail maps), so alpha is never premultiplied into
    the color: with "Straight" alpha Blender would turn those pixels black."""
    img = bpy.data.images.load(path, check_existing=True)
    try:
        img.colorspace_settings.name = colorspace
    except TypeError:  # colorspace missing in a custom OCIO config
        pass
    img.alpha_mode = "CHANNEL_PACKED"
    return img


def _spec_to_json(spec):
    return json.dumps({"key": spec.key, "shader": spec.shader, "params": spec.params,
                       "dynamic": spec.dynamic})


def spec_from_material(mat):
    """MaterialSpec stored on a charm material (textures are not needed
    to change the pattern), or None."""
    raw = mat.get(utils.PROP_MATERIAL_SPEC) if mat else None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return C.MaterialSpec.from_dict(data.get("key", mat.name), data)


def is_charm_material(mat):
    return mat is not None and utils.PROP_MATERIAL_KEY in mat


def build_material(spec, name, pattern=0, liquid_range=None):
    """Create a material for ``spec`` at ``pattern``. ``liquid_range``
    (bottom, top) is the object-space Z range of the container for liquids.
    Returns (material, warnings)."""
    warnings = []
    liquid = S.is_liquid(spec.shader)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    tree = mat.node_tree
    nodes, links = tree.nodes, tree.links
    nodes.clear()

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (700, 0)
    main = nodes.new("ShaderNodeGroup")
    main.name = main.label = S.NODE_MAIN
    main.node_tree = groups.ensure_group("LIQUID" if liquid else "WEAPON")
    main.location = (350, 0)
    main.width = 240
    links.new(main.outputs[0], out.inputs["Surface"])

    uv = nodes.new("ShaderNodeUVMap")
    uv.location = (-900, 0)

    def uv_helper(node_name, y):
        n = nodes.new("ShaderNodeGroup")
        n.name = n.label = node_name
        n.node_tree = groups.ensure_group("UV")
        n.location = (-650, y)
        links.new(uv.outputs[0], n.inputs["UV"])
        return n

    roles = S.texture_roles(spec.shader)
    y = 500
    used_roles = set()
    for slot, path in spec.textures.items():
        role_info = roles.get(slot)
        if role_info is None:
            continue
        role, colorspace = role_info
        if role in used_roles:
            continue  # e.g. g_tColorA and g_tColor both given
        if not os.path.isfile(path):
            warnings.append(f"{name}: missing texture {os.path.basename(path)}")
            continue
        used_roles.add(role)
        tex = nodes.new("ShaderNodeTexImage")
        tex.name = tex.label = _TEX_PREFIX + role
        tex.location = (-350, y)
        y -= 280
        tex.image = _load_image(path, colorspace)
        if role == "DETAIL":
            links.new(uv_helper(S.NODE_DETAIL_UV, tex.location.y).outputs[0], tex.inputs["Vector"])
        elif role == "GLITTER":
            links.new(uv_helper(S.NODE_GLITTER_UV, tex.location.y).outputs[0], tex.inputs["Vector"])
            tex.interpolation = "Closest"  # crisp flakes
        else:
            links.new(uv.outputs[0], tex.inputs["Vector"])
        _wire_texture(links, tex, role, main, liquid)

    mat[utils.PROP_MATERIAL_KEY] = spec.key
    mat[utils.PROP_MATERIAL_SPEC] = _spec_to_json(spec)
    if liquid:
        if liquid_range:
            main.inputs["Bottom"].default_value = liquid_range[0]
            main.inputs["Top"].default_value = liquid_range[1]
        # EEVEE: let the empty part of the container refract.
        if hasattr(mat, "use_raytrace_refraction"):
            mat.use_raytrace_refraction = True
    apply_pattern(mat, spec, pattern)
    return mat, warnings


def _wire_texture(links, tex, role, main, liquid):
    inputs = main.inputs
    if role == "COLOR":
        links.new(tex.outputs["Color"], inputs["Color"])
        if liquid:
            links.new(tex.outputs["Alpha"], inputs["Color Alpha"])
    elif role == "NORMAL":
        links.new(tex.outputs["Color"], inputs["Normal Map"])
    elif role == "METAL" and not liquid:
        links.new(tex.outputs["Color"], inputs["Metal Pack"])
    elif role == "AO" and not liquid:
        links.new(tex.outputs["Color"], inputs["Ambient Occlusion"])
    elif role == "TINT" and not liquid:
        links.new(tex.outputs["Color"], inputs["Tint Mask"])
    elif role == "DETAIL" and not liquid:
        links.new(tex.outputs["Color"], inputs["Detail"])
    elif role == "GLITTER" and not liquid:
        links.new(tex.outputs["Color"], inputs["Glitter Normal"])
        links.new(tex.outputs["Alpha"], inputs["Glitter Mask"])
    elif role == "LIQUID" and liquid:
        links.new(tex.outputs["Color"], inputs["Liquid Mask"])


def apply_pattern(mat, spec, pattern):
    """Write static params + the pattern's dynamic params to the nodes."""
    nodes = mat.node_tree.nodes if mat and mat.node_tree else None
    if nodes is None:
        return
    for (node_name, input_name), value in S.node_values(spec, pattern).items():
        node = nodes.get(node_name)
        if node is None:
            continue
        sock = node.inputs.get(input_name)
        if sock is None or not hasattr(sock, "default_value"):
            continue
        try:
            if isinstance(value, tuple):
                sock.default_value = value[:len(sock.default_value)]
            else:
                sock.default_value = value
        except (TypeError, ValueError) as exc:
            utils.log.warning("cs.charm: %s.%s = %r failed: %s", node_name, input_name, value, exc)


def main_node(mat):
    if mat is None or mat.node_tree is None:
        return None
    return mat.node_tree.nodes.get(S.NODE_MAIN)


def parameter_nodes(mat):
    """Nodes whose inputs the Active Charm panel shows, in display order."""
    if mat is None or mat.node_tree is None:
        return []
    names = (S.NODE_MAIN, S.NODE_DETAIL_UV, S.NODE_GLITTER_UV)
    return [mat.node_tree.nodes[n] for n in names if n in mat.node_tree.nodes]
