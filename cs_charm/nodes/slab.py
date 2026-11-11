# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Sticker Slab: the sticker inside the case and the printed label.

In CS2 the slab is a charm (def_index 37) whose material
(csgo_weapon.vfx with F_STICKERS) draws one sticker through the model's
second UV map. Here:

* **Sticker layer** in the slab material, between CHARM_MAIN and the
  glass (CHARM_GLASS)::

      CHARM_MAIN ───────────────┐
      SLAB_STICKER (finish) ────┴─ SLAB_MIX ── CHARM_GLASS ── Output
      SLAB_WEAR (alpha + wear) ── factor

  The finish groups are copies of cs.sticker's (sticker_groups.py). The
  sticker's own alpha and wear go through the "Wear & Clip" group; the
  finish group itself stays opaque and the mix lays it over the card.
* **Label color**: the material's DynamicParams read
  ``$sticker_rarity_color`` (g_vColorTint inside the tint mask, i.e. the
  label frame). The value is stored on the material (material.PROP_ENV).
* **Label text** by a Geometry Nodes modifier on the slab ("CS Slab
  Label"), so the text follows physics, parenting and duplicates. The
  label rectangle comes from the label area of the color texture (UV),
  mapped onto the mesh once per mesh (utils.PROP_LABEL).

The sticker is stored on the object as JSON (utils.PROP_STICKER), so wear,
text and rebuilds work without the sticker library.
"""

import json
import os
import zlib

import bpy

from .. import utils
from ..library import stickers as ST
from . import material as M
from . import sticker_groups as SG

STICKER_UV = "StickerUV"          # second UV map of the slab model (TEXCOORD_1)
NODE_PREFIX = "SLAB_"             # all sticker layer nodes; removed on rebuild
NODE_STICKER = "SLAB_STICKER"
NODE_WEAR = "SLAB_WEAR"
NODE_MIX = "SLAB_MIX"
ENV_RARITY = "$sticker_rarity_color"

LABEL_MODIFIER = "CS Slab Label"
LABEL_GROUP = "CS2 Slab Label"
LABEL_VERSION = 2
LABEL_VERSION_KEY = "cs_charm_label_version"
TEXT_MATERIAL = "CS2 Slab Label Text"
SERIAL_MATERIAL = "CS2 Slab Label Serial"

# Label area in the slab's 1024 px color texture (left, top, right, bottom;
# origin top left), frame included. Measured on the CS2 texture; the demo
# slab uses the same layout.
LABEL_RECT_PX = (12, 12, 500, 113)
TEXTURE_PX = 1024.0
# Distance of the text above the label surface (meters, model scale).
LABEL_LIFT = 0.00002

# Text lines of the label as fractions of the label width / height, from
# the in-game views (cs.charm-dev#13): (input, size, x, baseline, align, box
# width, material).
LABEL_LINES = (
    ("Header Left", 0.150, 0.035, 0.650, "LEFT", 0.46, TEXT_MATERIAL),
    ("Header Right", 0.150, 0.965, 0.650, "RIGHT", 0.46, TEXT_MATERIAL),
    ("Text", 0.270, 0.035, 0.370, "LEFT", 0.93, TEXT_MATERIAL),
    ("Serial", 0.150, 0.965, 0.120, "RIGHT", 0.30, SERIAL_MATERIAL),
)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def is_slab_material(mat):
    spec = M.spec_from_material(mat)
    return spec is not None and spec.flag("F_STICKERS")


def slab_materials(obj):
    if obj is None or obj.type != "MESH" or obj.data is None:
        return []
    return [m for m in obj.data.materials if m is not None and is_slab_material(m)]


def is_slab(obj):
    return utils.is_charm(obj) and bool(slab_materials(obj))


def is_slab_charm(charm):
    """Catalog entry of a slab (its material draws a sticker)."""
    return charm is not None and any(spec.flag("F_STICKERS") for spec in charm.materials())


def sticker_of(obj):
    """The sticker stored on a slab object, or None."""
    raw = obj.get(utils.PROP_STICKER) if obj is not None else None
    if not raw:
        return None
    try:
        return ST.Sticker.from_dict(json.loads(raw))
    except (ValueError, TypeError):
        return None


def label_text(obj):
    custom = obj.cs_charm.label_text.strip()
    if custom:
        return custom
    sticker = sticker_of(obj)
    return sticker.label_text() if sticker else ""


def label_color(obj):
    state = obj.cs_charm
    if state.use_label_color:
        return tuple(state.label_color)
    sticker = sticker_of(obj)
    return sticker.color if sticker else (1.0, 1.0, 1.0)


def wear_seed(sticker_id):
    """Stable per-sticker wear seed, like cs.sticker's."""
    return (zlib.crc32(sticker_id.encode("utf-8")) % 1000) / 10.0


# ---------------------------------------------------------------------------
# Sticker layer
# ---------------------------------------------------------------------------

def _image(path, data=False):
    if not path or not os.path.isfile(path):
        return None
    try:
        img = bpy.data.images.load(path, check_existing=True)
    except RuntimeError:
        return None
    if data:
        try:
            img.colorspace_settings.name = "Non-Color"
        except TypeError:
            img.colorspace_settings.is_data = True
        img.alpha_mode = "CHANNEL_PACKED"
    return img


MASK_FLOOR_KEY = "cs_charm_mask_floor"


def image_mask_floor(img):
    """ST.mask_floor of a loaded wear mask, cached on the image."""
    if img is None or not img.size[0] or not img.size[1]:
        return 0.0
    if MASK_FLOOR_KEY in img:
        return float(img[MASK_FLOOR_KEY])
    import numpy as np
    w, h = img.size
    px = np.empty(w * h * img.channels, dtype=np.float32)
    img.pixels.foreach_get(px)
    floor = ST.mask_floor(px.reshape(h, w, img.channels)[..., 0])
    img[MASK_FLOOR_KEY] = floor
    return floor


def _clear_layer(tree):
    for node in [n for n in tree.nodes if n.name.startswith(NODE_PREFIX)]:
        tree.nodes.remove(node)


def _layer_endpoints(tree):
    """(socket the card shader comes from, socket the result goes to)."""
    nodes = tree.nodes
    main = nodes.get("CHARM_MAIN")
    glass = nodes.get("CHARM_GLASS")
    if main is None:
        return None, None
    if glass is not None:
        return main.outputs[0], glass.inputs["Shader"]
    out = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
    return main.outputs[0], (out.inputs["Surface"] if out else None)


def build_sticker_layer(mat, sticker, wear=0.0):
    """(Re)build the sticker layer of a slab material. ``sticker`` None
    removes it (empty slab). Returns warnings."""
    warnings = []
    tree = mat.node_tree
    _clear_layer(tree)
    card, dest = _layer_endpoints(tree)
    if card is None or dest is None:
        return [f"{mat.name}: not a slab material"]
    nodes, links = tree.nodes, tree.links
    if sticker is None:
        links.new(card, dest)
        return warnings

    def node(kind, name, x, y, **props):
        n = nodes.new(kind)
        n.name = n.label = NODE_PREFIX + name
        n.location = (x, y)
        for key, value in props.items():
            setattr(n, key, value)
        return n

    finish = sticker.finish if sticker.finish in SG.FINISH_GROUP_KEYS else ST.DEFAULT_FINISH
    group = node("ShaderNodeGroup", "STICKER", 100, -900)
    group.name = NODE_STICKER
    group.label = f"Sticker ({ST.FINISH_LABELS.get(finish, finish)})"
    group.node_tree = SG.ensure_group(finish)
    group.width = 240
    wear_node = node("ShaderNodeGroup", "WEAR", 100, -1500)
    wear_node.name = NODE_WEAR
    wear_node.label = "Sticker Alpha & Wear"
    wear_node.node_tree = SG.ensure_group("WEAR")
    mix = node("ShaderNodeMixShader", "MIX", 420, -300)
    mix.name = NODE_MIX
    links.new(card, mix.inputs[1])
    links.new(group.outputs[0], mix.inputs[2])
    links.new(wear_node.outputs["Alpha"], mix.inputs[0])
    links.new(mix.outputs[0], dest)

    uv = node("ShaderNodeUVMap", "UV", -1300, -1000, uv_map=STICKER_UV)
    present = {r: p for r, p in sticker.textures.items() if p and os.path.isfile(p)}
    for role, path in sticker.textures.items():
        if role not in present:
            warnings.append(f"{sticker.name}: {role} texture not found ({path})")

    y = [-700]

    def tex(role, vector=None, extension="EXTEND"):
        img = _image(present.get(role, ""), data=role in ST.DATA_ROLES)
        if img is None:
            return None
        n = node("ShaderNodeTexImage", "TEX_" + role.upper(), -650, y[0], image=img, extension=extension)
        y[0] -= 280
        links.new(vector if vector is not None else uv.outputs[0], n.inputs["Vector"])
        return n

    def wire(src, name, target=group):
        sock = target.inputs.get(name)
        if sock is not None:
            links.new(src, sock)

    def setv(target, name, value):
        sock = target.inputs.get(name)
        if sock is not None and not sock.is_linked and hasattr(sock, "default_value"):
            try:
                sock.default_value = value
            except (TypeError, ValueError):
                pass

    base = tex(ST.ROLE_BASE, extension="CLIP")
    if base is None:
        warnings.append(f"{sticker.name}: no base texture, the slab stays empty")
        links.new(card, dest)
        _clear_layer(tree)
        return warnings
    wire(base.outputs["Color"], "Base Color")
    setv(group, "Alpha", 1.0)      # opaque: the mix factor carries the alpha
    setv(group, "Alpha Clip", 0.0)
    setv(group, "Wear", 0.0)

    wearmask = tex(ST.ROLE_WEARMASK, extension="CLIP")
    if wearmask is not None:
        # CS2: the sticker shape is wear mask above its background (0, some
        # masks 4/255) by ~0.4 % (as in cs.sticker).
        shape = node("ShaderNodeMath", "SHAPE", -300, -1500, operation="MULTIPLY_ADD", use_clamp=True)
        floor = image_mask_floor(wearmask.image)
        shape.inputs[1].default_value = ST.MASK_SHAPE_GAIN
        shape.inputs[2].default_value = -floor * ST.MASK_SHAPE_GAIN
        links.new(wearmask.outputs["Color"], shape.inputs[0])
        wire(shape.outputs[0], "Alpha", wear_node)
        wire(wearmask.outputs["Color"], "Wear Mask", wear_node)
        setv(wear_node, "Use Wear Mask", 1.0)
        scratches = tex(ST.ROLE_SCRATCHES, extension="REPEAT")
        if scratches is not None:
            wire(scratches.outputs["Color"], "Scratches", wear_node)
    else:
        wire(base.outputs["Alpha"], "Alpha", wear_node)
    setv(wear_node, "Alpha Clip", 0.0)
    setv(wear_node, "Wear", float(wear))
    seed = wear_seed(sticker.id)
    setv(wear_node, "Wear Seed", seed)

    normal = tex(ST.ROLE_NORMAL)
    if normal is not None:
        wire(normal.outputs["Color"], "Normal Color")
    rough = tex(ST.ROLE_ROUGHNESS)
    if rough is not None:
        wire(rough.outputs["Color"], "Roughness")
    if finish in ("FOIL", "GOLD"):
        metal = tex(ST.ROLE_METALNESS)
        if metal is not None:
            wire(metal.outputs["Color"], "Metal Mask")
    glow = tex(ST.ROLE_EMISSION)
    if glow is not None:
        wire(glow.outputs["Color"], "Emission Mask")
    if finish == "GLITTER":
        glit = tex(ST.ROLE_GLITTER)
        if glit is not None:
            wire(glit.outputs["Color"], "Glitter Mask")
        if ST.ROLE_FLAKES in present:
            tiling = node("ShaderNodeMapping", "FLAKE_TILING", -950, y[0])
            tiling.inputs["Scale"].default_value = (8.0, 8.0, 8.0)
            links.new(uv.outputs[0], tiling.inputs["Vector"])
            flakes = tex(ST.ROLE_FLAKES, tiling.outputs["Vector"], extension="REPEAT")
            if flakes is not None:
                wire(flakes.outputs["Color"], "Flake Normal")
                setv(group, "Use Flake Texture", 1.0)
    if finish in ("HOLO", "LENTICULAR") and ST.ROLE_HOLOMASK in present:
        coords = node("ShaderNodeGroup", "HOLO_COORDS", -950, y[0])
        coords.node_tree = SG.ensure_group("HOLO_COORDS")
        mask = tex(ST.ROLE_HOLOMASK)
        if mask is not None:
            links.new(mask.outputs["Color"], coords.inputs["Holo Mask"])
            wire(mask.outputs["Color"], "Holo Mask")
            wire(mask.outputs["Alpha"], "Holo Mask Alpha")
        spectrum = tex(ST.ROLE_HOLOSPECTRUM, coords.outputs["Vector"], extension="REPEAT")
        if spectrum is None:
            proc = node("ShaderNodeGroup", "HOLO_SPECTRUM", -650, y[0])
            proc.node_tree = SG.ensure_group("HOLO_SPECTRUM")
            links.new(coords.outputs["Vector"], proc.inputs["Vector"])
            spectrum_out = proc.outputs["Color"]
        else:
            spectrum_out = spectrum.outputs["Color"]
        wire(spectrum_out, "Spectrum Color")

    # Catalog params (e.g. Wear Bias) set matching inputs of both groups.
    for key, value in sticker.params.items():
        if key in ("Wear", "Alpha", "Alpha Clip"):
            continue
        setv(group, key, value)
        setv(wear_node, key, value)
    return warnings


def set_wear(mat, wear):
    node = mat.node_tree.nodes.get(NODE_WEAR) if mat.node_tree else None
    if node is not None and "Wear" in node.inputs:
        node.inputs["Wear"].default_value = float(wear)


# ---------------------------------------------------------------------------
# Label plane
# ---------------------------------------------------------------------------

def _uv_rect():
    left, top, right, bottom = LABEL_RECT_PX
    return (left / TEXTURE_PX, 1.0 - bottom / TEXTURE_PX, right / TEXTURE_PX, 1.0 - top / TEXTURE_PX)


def compute_label_plane(mesh):
    """Label rectangle on the mesh from the label area of the first UV map:
    {"origin": bottom-left corner, "x": vector along the width, "y": vector
    along the height} in object space, or None. Takes the largest triangle
    whose UVs contain the center of the area and maps UV to positions
    linearly from it (label and card are one flat, evenly mapped face)."""
    if not mesh.uv_layers:
        return None
    u0, v0, u1, v1 = _uv_rect()
    cu, cv = (u0 + u1) / 2.0, (v0 + v1) / 2.0
    uv = mesh.uv_layers[0].data
    mesh.calc_loop_triangles()
    best, best_area = None, 0.0
    eps = 1e-6
    for tri in mesh.loop_triangles:
        (ax, ay), (bx, by), (cx, cy) = ((uv[li].uv.x, uv[li].uv.y) for li in tri.loops)
        det = (bx - ax) * (cy - ay) - (cx - ax) * (by - ay)
        if abs(det) < 1e-12:
            continue
        s = ((cu - ax) * (cy - ay) - (cx - ax) * (cv - ay)) / det
        t = ((bx - ax) * (cv - ay) - (cu - ax) * (by - ay)) / det
        if s < -eps or t < -eps or s + t > 1.0 + eps:
            continue
        if tri.area > best_area:
            best, best_area = tri, tri.area
    if best is None:
        return None
    uvs = [uv[li].uv.copy() for li in best.loops]
    cos = [mesh.vertices[vi].co.copy() for vi in best.vertices]
    a, b, c = uvs
    det = (b.x - a.x) * (c.y - a.y) - (c.x - a.x) * (b.y - a.y)

    def at(u, v):
        s = ((u - a.x) * (c.y - a.y) - (c.x - a.x) * (v - a.y)) / det
        t = ((b.x - a.x) * (v - a.y) - (u - a.x) * (b.y - a.y)) / det
        return cos[0] + (cos[1] - cos[0]) * s + (cos[2] - cos[0]) * t

    origin = at(u0, v0)
    x = at(u1, v0) - origin
    y = at(u0, v1) - origin
    return {"origin": tuple(origin), "x": tuple(x), "y": tuple(y)}


def label_plane(mesh):
    raw = mesh.get(utils.PROP_LABEL)
    if raw:
        try:
            return json.loads(raw) or None
        except ValueError:
            pass
    plane = compute_label_plane(mesh)
    mesh[utils.PROP_LABEL] = json.dumps(plane)
    return plane


# ---------------------------------------------------------------------------
# Label text (Geometry Nodes)
# ---------------------------------------------------------------------------

def _text_material(name, gray):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.diffuse_color = (gray, gray, gray, 1.0)
        tree = mat.node_tree if mat.node_tree else None
        if tree is None:
            mat.use_nodes = True
            tree = mat.node_tree
        bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (gray, gray, gray, 1.0)
            bsdf.inputs["Roughness"].default_value = 0.8
            spec = bsdf.inputs.get("Specular IOR Level")
            if spec is not None:
                spec.default_value = 0.1  # printed ink, no gloss
    return mat


def _set_menu(node, socket, ui_value, prop, enum_value):
    """Menu socket (Blender 5.x) or enum property (4.5)."""
    sock = node.inputs.get(socket)
    if sock is not None and sock.bl_idname == "NodeSocketMenu":
        sock.default_value = ui_value
    elif hasattr(node, prop):
        setattr(node, prop, enum_value)


def _label_font():
    prefs = utils.prefs()
    path = bpy.path.abspath(prefs.label_font) if prefs is not None and prefs.label_font else ""
    if path and os.path.isfile(path):
        try:
            return bpy.data.fonts.load(path, check_existing=True)
        except RuntimeError:
            utils.log.warning("cs.charm: cannot load label font %s", path)
    # Blender 5.x needs a font data block; "<builtin>" is Blender's own font.
    for font in bpy.data.fonts:
        if font.filepath == "<builtin>":
            return font
    try:
        return bpy.data.fonts.load("<builtin>")
    except RuntimeError:
        return None


def _set_font(node, font):
    sock = node.inputs.get("Font")
    if sock is not None and hasattr(sock, "default_value"):
        sock.default_value = font
    elif hasattr(node, "font"):
        node.font = font


def _build_label_group(tree):
    from .builder import find_socket
    nodes, links = tree.nodes, tree.links
    iface = tree.interface

    def sock(name, kind, in_out="INPUT", default=None, description=""):
        s = iface.new_socket(name=name, in_out=in_out, socket_type=kind)
        if description:
            s.description = description
        if default is not None and hasattr(s, "default_value"):
            s.default_value = default
        return s

    sock("Geometry", "NodeSocketGeometry")
    sock("Text", "NodeSocketString", description="Main line: sticker name and event")
    sock("Serial", "NodeSocketString", default="0000000000")
    sock("Header Left", "NodeSocketString", default=ST.LABEL_HEADER_LEFT)
    sock("Header Right", "NodeSocketString", default=ST.LABEL_HEADER_RIGHT)
    sock("Origin", "NodeSocketVector", description="Bottom-left corner of the label (object space)")
    sock("Axis X", "NodeSocketVector", default=(0.0, 0.04, 0.0), description="Label width vector")
    sock("Axis Y", "NodeSocketVector", default=(0.0, 0.0, 0.008), description="Label height vector")
    sock("Lift", "NodeSocketFloat", default=LABEL_LIFT, description="Text distance above the label")
    sock("Geometry", "NodeSocketGeometry", in_out="OUTPUT")

    def new(kind, x, y, **props):
        n = nodes.new(kind)
        n.location = (x, y)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def vm(op, a, b=None, x=0, y=0):
        n = new("ShaderNodeVectorMath", x, y, operation=op)
        links.new(a, n.inputs[0]) if not isinstance(a, tuple) else setattr(n.inputs[0], "default_value", a)
        if b is not None:
            if isinstance(b, tuple):
                n.inputs[1].default_value = b
            else:
                links.new(b, n.inputs[1])
        return find_socket(n.outputs, "Value" if op == "LENGTH" else "Vector")

    def fm(op, a, b, x=0, y=0):
        n = new("ShaderNodeMath", x, y, operation=op)
        for i, v in enumerate((a, b)):
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                links.new(v, n.inputs[i])
        return n.outputs[0]

    gin = new("NodeGroupInput", -1400, 0)
    gout = new("NodeGroupOutput", 1400, 0)
    width = vm("LENGTH", gin.outputs["Axis X"], x=-1200, y=-300)
    height = vm("LENGTH", gin.outputs["Axis Y"], x=-1200, y=-450)

    join_text = new("GeometryNodeJoinGeometry", 600, 0)
    font = _label_font()
    for i, (name, size, x_frac, base_frac, align, box_frac, mat_name) in enumerate(LABEL_LINES):
        y = 400 - i * 350
        s2c = new("GeometryNodeStringToCurves", -700, y)
        s2c.name = s2c.label = "LABEL_" + name.upper().replace(" ", "_")
        links.new(gin.outputs[name], s2c.inputs["String"])
        size_s = fm("MULTIPLY", height, size, x=-950, y=y)
        links.new(size_s, s2c.inputs["Size"])
        box_w = fm("MULTIPLY", width, box_frac, x=-950, y=y - 60)
        links.new(box_w, find_socket(s2c.inputs, "Text Box Width"))
        box_h = fm("MULTIPLY", size_s, 1.6, x=-950, y=y - 120)
        links.new(box_h, find_socket(s2c.inputs, "Text Box Height"))
        _set_menu(s2c, "Overflow", "Scale To Fit", "overflow", "SCALE_TO_FIT")
        _set_menu(s2c, "Align X", "Right" if align == "RIGHT" else "Left", "align_x", align)
        # "Top Baseline": the (first) baseline sits at y = 0, also when
        # Scale To Fit shrinks a long line (measured, both overflow modes).
        _set_menu(s2c, "Align Y", "Top Baseline", "align_y", "TOP_BASELINE")
        _set_font(s2c, font)
        realize = new("GeometryNodeRealizeInstances", -450, y)
        links.new(s2c.outputs["Curve Instances"], realize.inputs[0])
        fill = new("GeometryNodeFillCurve", -250, y)
        links.new(realize.outputs[0], fill.inputs["Curve"])
        # The text box starts at x = 0: right-aligned lines end at box width.
        left = fm("SUBTRACT", fm("MULTIPLY", width, x_frac, x=-450, y=y - 200), box_w if align == "RIGHT" else 0.0,
                  x=-250, y=y - 200)
        up = fm("MULTIPLY", height, base_frac, x=-450, y=y - 260)
        offset = new("ShaderNodeCombineXYZ", -50, y - 200)
        links.new(left, offset.inputs[0])
        links.new(up, offset.inputs[1])
        move = new("GeometryNodeTransform", 0, y)
        links.new(fill.outputs[0], move.inputs["Geometry"])
        links.new(offset.outputs[0], move.inputs["Translation"])
        setmat = new("GeometryNodeSetMaterial", 250, y)
        links.new(move.outputs[0], setmat.inputs["Geometry"])
        setmat.inputs["Material"].default_value = _text_material(
            mat_name, 0.006 if mat_name == TEXT_MATERIAL else 0.08)
        links.new(setmat.outputs[0], join_text.inputs[0])

    # Label space (x along the width, y along the height) -> object space.
    pos = new("GeometryNodeInputPosition", 600, -500)
    sep = new("ShaderNodeSeparateXYZ", 800, -500)
    links.new(pos.outputs[0], sep.inputs[0])
    ux = vm("NORMALIZE", gin.outputs["Axis X"], x=600, y=-700)
    uy = vm("NORMALIZE", gin.outputs["Axis Y"], x=600, y=-850)
    un = vm("NORMALIZE", vm("CROSS_PRODUCT", ux, uy, x=800, y=-1000), x=1000, y=-1000)
    px = vm("SCALE", ux, x=1000, y=-600)
    links.new(sep.outputs[0], px.node.inputs["Scale"])
    py = vm("SCALE", uy, x=1000, y=-750)
    links.new(sep.outputs[1], py.node.inputs["Scale"])
    lift = vm("SCALE", un, x=1150, y=-1000)
    links.new(gin.outputs["Lift"], lift.node.inputs["Scale"])
    p = vm("ADD", vm("ADD", gin.outputs["Origin"], px, x=1150, y=-600), py, x=1250, y=-650)
    p = vm("ADD", p, lift, x=1300, y=-750)
    setpos = new("GeometryNodeSetPosition", 900, 0)
    links.new(join_text.outputs[0], setpos.inputs["Geometry"])
    links.new(p, setpos.inputs["Position"])
    join = new("GeometryNodeJoinGeometry", 1150, 0)
    links.new(setpos.outputs[0], join.inputs[0])
    links.new(gin.outputs["Geometry"], join.inputs[0])
    links.new(join.outputs[0], gout.inputs[0])


def ensure_label_group():
    tree = bpy.data.node_groups.get(LABEL_GROUP)
    if tree is not None and tree.get(LABEL_VERSION_KEY) == LABEL_VERSION:
        return tree
    if tree is not None:
        tree.name = f"{LABEL_GROUP} (v{tree.get(LABEL_VERSION_KEY, 0)})"
    tree = bpy.data.node_groups.new(LABEL_GROUP, "GeometryNodeTree")
    tree[LABEL_VERSION_KEY] = LABEL_VERSION
    _build_label_group(tree)
    return tree


def on_font_changed():
    tree = bpy.data.node_groups.get(LABEL_GROUP)
    if tree is None:
        return
    font = _label_font()
    for node in tree.nodes:
        if node.bl_idname == "GeometryNodeStringToCurves":
            _set_font(node, font)


def _input_ids(tree):
    return {item.name: item.identifier for item in tree.interface.items_tree
            if getattr(item, "item_type", "SOCKET") == "SOCKET" and item.in_out == "INPUT"}


def _set_modifier_input(mod, ids, name, value):
    key = ids.get(name)
    if key is None:
        return
    try:
        props = getattr(mod, "properties", None)  # Blender 5.x
        if props is not None and hasattr(props, "inputs"):
            getattr(props.inputs, key).value = value
        else:                                     # 4.5: ID properties
            mod[key] = value
    except (TypeError, ValueError) as exc:
        utils.log.warning("cs.charm: label input %s = %r failed: %s", name, value, exc)


def label_modifier(obj):
    mod = obj.modifiers.get(LABEL_MODIFIER)
    return mod if mod is not None and mod.type == "NODES" else None


def update_label(obj):
    """Create or update the label modifier of a slab object."""
    plane = label_plane(obj.data)
    if plane is None:
        return False
    mod = label_modifier(obj)
    if mod is None:
        mod = obj.modifiers.new(LABEL_MODIFIER, "NODES")
    tree = ensure_label_group()
    if mod.node_group is not tree:
        mod.node_group = tree
    ids = _input_ids(tree)
    _set_modifier_input(mod, ids, "Text", label_text(obj))
    sticker = sticker_of(obj)
    _set_modifier_input(mod, ids, "Serial", sticker.serial() if sticker else ST.format_serial(0))
    _set_modifier_input(mod, ids, "Origin", plane["origin"])
    _set_modifier_input(mod, ids, "Axis X", plane["x"])
    _set_modifier_input(mod, ids, "Axis Y", plane["y"])
    # Custom property writes do not tag the modifier for re-evaluation.
    mod.show_viewport = mod.show_viewport
    obj.update_tag()
    return True


# ---------------------------------------------------------------------------
# Object level
# ---------------------------------------------------------------------------

def update(obj):
    """Apply the slab settings (color, wear, label) of ``obj``."""
    if not is_slab(obj):
        return
    color = label_color(obj)
    for mat in slab_materials(obj):
        M.set_material_env(mat, {ENV_RARITY: list(color)})
        spec = M.spec_from_material(mat)
        if spec is not None:
            M.apply_pattern(mat, spec, obj.cs_charm.pattern)
        set_wear(mat, obj.cs_charm.sticker_wear)
    update_label(obj)


def on_settings_changed(obj):
    update(obj)


def apply_sticker(obj, sticker):
    """Put ``sticker`` (stickers.Sticker or None) into the slab ``obj``.
    Returns warnings."""
    warnings = []
    mats = slab_materials(obj)
    if not mats:
        return ["not a Sticker Slab"]
    if sticker is None:
        if utils.PROP_STICKER in obj:
            del obj[utils.PROP_STICKER]
    else:
        obj[utils.PROP_STICKER] = json.dumps(sticker.to_dict())
    for mat in mats:
        warnings += build_sticker_layer(mat, sticker, obj.cs_charm.sticker_wear)
    update(obj)
    return warnings


def rebuild(obj):
    """Rebuild the sticker layer from the stored sticker (after the
    materials were rebuilt)."""
    if is_slab(obj):
        return apply_sticker(obj, sticker_of(obj))
    return []
