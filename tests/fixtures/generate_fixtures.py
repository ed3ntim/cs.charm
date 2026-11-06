# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Generate the test charms (run inside Blender):

    blender -b --factory-startup --python tests/fixtures/generate_fixtures.py

Writes tests/fixtures/library/ (not part of the add-on since 2.0):
catalog.json, the models (.glb), procedural
textures (PNG) and preview icons. Everything is made from scratch here, no
game assets. The demos use the same data layout as a real CS2 export, so
they exercise the whole pipeline:

* "Demo Gem Drop"    csgo_weapon.vfx: tint mask, hue/saturation pattern,
                     glitter flakes in the effect mask, metal chain
* "Demo Fuel Flask"  csgo_simple_liquid.vfx: liquid color and fill level
                     driven by the pattern (same formulas as Butane Buddy)
* "Demo Sticker Slab" csgo_weapon.vfx with F_STICKERS / F_OPAQUE_REFRACT:
                     own case geometry with the same UV layout as the CS2
                     slab (label and card in the color texture, sticker UV
                     as second UV map), plus two demo stickers in
                     library/stickers (a cs.sticker style catalog)

Models are in meters with the attachment point at the origin and the
charm hanging along -Z, like Source2Viewer's charm exports.
"""

import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "library")
MODELS = "demo"
ICONS = "icons"
TEX = 256
RNG = np.random.default_rng(20261028)


# ---------------------------------------------------------------------------
# Textures
# ---------------------------------------------------------------------------

def save_png(name, rgba):
    """Write an (h, w, 4) float array as PNG (row 0 = top of the image)."""
    h, w = rgba.shape[:2]
    img = bpy.data.images.new(name, w, h, alpha=True)
    img.pixels.foreach_set(np.flipud(rgba).astype(np.float32).ravel())
    path = os.path.join(OUT, MODELS, name + ".png")
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    return f"{MODELS}/{name}.png"


def uv_grid(size=TEX):
    v, u = np.mgrid[0:size, 0:size] / (size - 1)
    return u, 1.0 - v  # v = 1 at the top row


def gray(value, size=TEX):
    out = np.ones((size, size, 4))
    out[..., :3] = np.asarray(value)[..., None] if np.ndim(value) else value
    return out


def flat_normal(size=TEX):
    out = np.ones((size, size, 4))
    out[..., 0] = out[..., 1] = 0.5
    return out


def glitter_normal(size=TEX, cell=4):
    """Random flake normals (RGB) with a flake mask in alpha, like CS2's
    squares_glitter_normal."""
    n = size // cell
    angles = RNG.uniform(0, 2 * math.pi, (n, n))
    tilt = RNG.uniform(0.15, 0.6, (n, n))
    mask = (RNG.uniform(0, 1, (n, n)) > 0.35).astype(float)
    nx, ny = np.cos(angles) * tilt, np.sin(angles) * tilt
    nz = np.sqrt(np.clip(1 - nx ** 2 - ny ** 2, 0, 1))
    rgba = np.stack([nx * 0.5 + 0.5, ny * 0.5 + 0.5, nz * 0.5 + 0.5, mask], axis=-1)
    return np.kron(rgba, np.ones((cell, cell, 1)))


def gem_textures():
    u, v = uv_grid()
    # Body: candy gradient with stripes, white rim band at the equator seam.
    stripes = 0.5 + 0.5 * np.sin(v * math.pi * 10)
    color = np.ones((TEX, TEX, 4))
    color[..., 0] = 0.15 + 0.1 * stripes
    color[..., 1] = 0.55 + 0.25 * v
    color[..., 2] = 0.85 - 0.2 * stripes
    band = (np.abs(v - 0.5) < 0.06)
    color[band, :3] = 0.92
    tint = gray(np.where(band, 0.0, 1.0))
    pack = np.ones((TEX, TEX, 4))
    pack[..., 0] = np.where(band, 0.35, 0.18)   # roughness
    pack[..., 1] = np.where(band, 1.0, 0.0)     # metalness: metal band
    pack[..., 2] = np.where(band, 0.0, 1.0)     # effect mask: glitter on the body
    ao = gray(0.85 + 0.15 * np.sin(v * math.pi))
    return {
        "g_tColor": save_png("demo_gem_color", color),
        "g_tTintMask": save_png("demo_gem_tint", tint),
        "g_tMetalness": save_png("demo_gem_metal", pack),
        "g_tAmbientOcclusion": save_png("demo_gem_ao", ao),
        "g_tNormal": save_png("demo_flat_normal", flat_normal()),
        "g_tGlitterNormal": save_png("demo_glitter_normal", glitter_normal()),
    }


def chain_textures():
    pack = np.ones((TEX, TEX, 4))
    pack[..., 0], pack[..., 1], pack[..., 2] = 0.3, 1.0, 0.0
    return {
        "g_tColor": save_png("demo_chain_color", gray(0.78)),
        "g_tMetalness": save_png("demo_chain_metal", pack),
        "g_tNormal": "demo/demo_flat_normal.png",
    }


def flask_textures():
    u, v = uv_grid()
    window = (np.abs(u - 0.5) < 0.18) & (v > 0.12) & (v < 0.88)
    color = np.ones((TEX, TEX, 4))
    color[..., 0] = 0.75
    color[..., 1] = 0.12 + 0.05 * np.sin(u * math.pi * 16)
    color[..., 2] = 0.10
    color[window, :3] = 0.9
    color[..., 3] = np.where(window, 0.0, 1.0)  # alpha 0 = see-through window
    # Scale marks on the window edge (printed, opaque).
    marks = window & (np.abs(u - 0.33) < 0.012) & ((v * 20) % 1 < 0.25)
    color[marks] = (0.95, 0.95, 0.95, 1.0)
    mask = gray(window.astype(float))
    return {
        "g_tColorA": save_png("demo_flask_color", color),
        "g_tLiquidMask": save_png("demo_flask_mask", mask),
        "g_tNormalA": "demo/demo_flat_normal.png",
    }


# Sticker Slab layout, pixels of a 1024 texture (origin top left), as in
# CS2's sticker_display_case_color: label and card share one front face.
SLAB_TEX = 512
SLAB_FRONT_PX = (12, 12, 500, 610)    # label + card
SLAB_LABEL_BOTTOM_PX = 113
SLAB_CARD_TOP_PX = 124
SLAB_FRAME_PX = (560, 40, 1000, 600)  # case faces


def _px(value, size=SLAB_TEX):
    return int(round(value * size / 1024.0))


def slab_textures():
    size = SLAB_TEX
    left, top, right, bottom = (_px(c) for c in SLAB_FRONT_PX)
    label_bottom, card_top = _px(SLAB_LABEL_BOTTOM_PX), _px(SLAB_CARD_TOP_PX)
    yy, xx = np.mgrid[0:size, 0:size]
    color = np.ones((size, size, 4))
    color[..., :3] = 0.62                                       # case
    card = (xx >= left) & (xx <= right) & (yy >= card_top) & (yy <= bottom)
    dots = (np.sin(xx * 1.9) * np.sin(yy * 1.9 + (xx // 3 % 2) * 1.6)) > 0.6
    color[card, :3] = 0.80
    color[card & dots, :3] = 0.76
    label = (xx >= left) & (xx <= right) & (yy >= top) & (yy <= label_bottom)
    color[label, :3] = 0.95
    frame = label & ((xx < left + 2) | (xx > right - 2) | (yy < top + 2) | (yy > label_bottom - 2))
    badge = label & (np.abs(xx - (left + right) / 2) < 10) & (yy > label_bottom - 7)
    bars = (label & (xx > left + 6) & (xx < left + 70) & (yy > label_bottom - 9) & (yy < label_bottom - 4)
            & (RNG.uniform(0, 1, (size, size)) > 0.4))
    color[frame | badge, :3] = 0.85
    color[bars, :3] = 0.2
    tint = gray((frame | badge).astype(float), size)
    refract = gray((~(card | label)).astype(float), size)
    pack = np.ones((size, size, 4))
    pack[..., 0] = np.where(card | label, 0.6, 0.35)            # roughness
    pack[..., 1] = 0.0
    pack[..., 2] = 0.0
    return {
        "g_tColor": save_png("demo_slab_color", color),
        "g_tTintMask": save_png("demo_slab_tint", tint),
        "g_tOpaqueRefractMask": save_png("demo_slab_refract", refract),
        "g_tMetalness": save_png("demo_slab_metal", pack),
        "g_tNormal": "demo/demo_flat_normal.png",
    }


def demo_sticker_textures():
    """A star badge (paper) and its holo version: base color with alpha and
    a holo mask (R strength, G/B spectrum offset), in cs.sticker roles."""
    size = 256
    u, v = uv_grid(size)
    x, y = u - 0.5, v - 0.5
    r = np.hypot(x, y)
    a = np.arctan2(y, x)
    star = r < 0.22 + 0.12 * np.cos(5 * a)
    disc = r < 0.42
    ring = disc & (r > 0.38)
    base = np.zeros((size, size, 4))
    base[disc, :3] = (0.08, 0.10, 0.16)
    base[ring, :3] = (0.95, 0.75, 0.2)
    base[star, :3] = (0.95, 0.35, 0.15)
    base[..., 3] = disc.astype(float)
    holo = np.zeros((size, size, 4))
    holo[..., 0] = star.astype(float)
    holo[..., 1] = u
    holo[..., 2] = v
    holo[..., 3] = 1.0
    folder = os.path.join(OUT, "stickers", "textures")
    os.makedirs(folder, exist_ok=True)

    def write(name, rgba):
        img = bpy.data.images.new(name, size, size, alpha=True)
        img.pixels.foreach_set(np.flipud(rgba).astype(np.float32).ravel())
        img.filepath_raw = os.path.join(folder, name + ".png")
        img.file_format = "PNG"
        img.save()
        bpy.data.images.remove(img)
        return f"textures/{name}.png"

    return write("demo_star", base), write("demo_star_holomask", holo)


def write_sticker_catalog():
    base, holomask = demo_sticker_textures()
    catalog = {
        "version": 1,
        "generator": "cs.charm tests/fixtures/generate_fixtures.py",
        "note": "Demo stickers for the Sticker Slab, made from scratch, no game assets. "
                "Same format as cs.sticker's catalog.json.",
        "stickers": [
            {"id": "demo_star", "name": "Demo Star", "collection": "cs.charm Demo 2026", "finish": "PAPER",
             "rarity": "rare", "kit_id": 2026, "textures": {"base": base}, "tags": ["demo"]},
            {"id": "demo_star_holo", "name": "Demo Star (Holo)", "collection": "cs.charm Demo 2026",
             "finish": "HOLO", "rarity": "mythical", "kit_id": 2027,
             "textures": {"base": base, "holomask": holomask},
             "tags": ["demo"]},
        ],
    }
    with open(os.path.join(OUT, "stickers", "catalog.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(catalog, fh, indent=1)
        fh.write("\n")


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = color
    return mat


def chain(mat, links=3):
    """Small torus links from the origin downwards. Returns the lowest z."""
    objs, z = [], 0.0
    for i in range(links):
        bpy.ops.mesh.primitive_torus_add(major_radius=0.0018, minor_radius=0.00045,
                                         major_segments=16, minor_segments=6,
                                         location=(0, 0, z - 0.0018),
                                         rotation=(math.pi / 2, 0, (math.pi / 2) * (i % 2)))
        obj = bpy.context.active_object
        obj.data.materials.append(mat)
        objs.append(obj)
        z -= 0.0030
    return objs, z - 0.0008


def cylindrical_uv(obj, zmin, zmax):
    """u = angle around Z (0.5 faces +X, the charm's front), v = height."""
    mesh = obj.data
    uv = mesh.uv_layers.active or mesh.uv_layers.new(name="UVMap")
    mw = obj.matrix_world
    for poly in mesh.polygons:
        center = mw @ poly.center
        cu = math.atan2(center.y, center.x) / (2 * math.pi) + 0.5
        for li in poly.loop_indices:
            co = mw @ mesh.vertices[mesh.loops[li].vertex_index].co
            u = math.atan2(co.y, co.x) / (2 * math.pi) + 0.5
            if abs(u - cu) > 0.5:  # keep faces on the seam continuous
                u += 1.0 if cu > u else -1.0
            uv.data[li].uv = (u, (co.z - zmin) / (zmax - zmin))


def join(objs, name):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    obj = bpy.context.active_object
    obj.name = obj.data.name = name
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return obj


def build_gem():
    chain_mat = material("demo_chain", (0.78, 0.78, 0.8, 1.0))
    gem_mat = material("demo_gem", (0.2, 0.6, 0.9, 1.0))
    links, z = chain(chain_mat)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=0.009,
                                         location=(0, 0, z - 0.009))
    gem = bpy.context.active_object
    gem.scale = (0.45, 1.0, 1.25)
    bpy.ops.object.transform_apply(scale=True)
    gem.data.materials.append(gem_mat)
    cylindrical_uv(gem, z - 0.009 * 2.25, z + 0.0005)
    bpy.ops.object.shade_smooth()
    return join(links + [gem], "demo_gem_drop")


def build_flask():
    chain_mat = material("demo_chain", (0.78, 0.78, 0.8, 1.0))
    flask_mat = material("demo_flask", (0.75, 0.12, 0.1, 1.0))
    links, z = chain(chain_mat)
    height, radius = 0.026, 0.0075
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=radius, depth=height,
                                        location=(0, 0, z - 0.002 - height / 2))
    body = bpy.context.active_object
    body.scale = (0.55, 1.0, 1.0)
    bpy.ops.object.transform_apply(scale=True)
    bpy.ops.object.shade_smooth()
    body.data.materials.append(flask_mat)
    cylindrical_uv(body, z - 0.002 - height, z - 0.002)
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.0028, depth=0.003,
                                        location=(0, 0, z - 0.0005))
    cap = bpy.context.active_object
    cap.data.materials.append(chain_mat)
    return join(links + [body, cap], "demo_fuel_flask")


def build_slab():
    """Case plus a front face for label and card. UV map 1 holds the color
    texture layout, UV map 2 ("StickerUV") the sticker: card = 0..1, label
    above, everything else on one point outside (like TEXCOORD_1 of the CS2
    model)."""
    chain_mat = material("demo_chain", (0.78, 0.78, 0.8, 1.0))
    slab_mat = material("demo_slab", (0.8, 0.8, 0.8, 1.0))
    links, z = chain(chain_mat, links=2)
    left, top, right, bottom = SLAB_FRONT_PX
    width = 0.040
    px = width / (right - left)                       # meters per texture pixel
    height = (bottom - top) * px
    front_top = z - 0.004
    depth = 0.0036
    margin = 0.0018
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(depth / 2, 0, front_top - height / 2))
    case = bpy.context.active_object
    case.scale = (depth, width + 2 * margin, height + 2 * margin)
    bpy.ops.object.transform_apply(scale=True)
    case.data.materials.append(slab_mat)
    fl, ft, fr, fb = (c / 1024.0 for c in SLAB_FRAME_PX)
    uv = case.data.uv_layers.active
    for poly in case.data.polygons:
        for li in poly.loop_indices:
            co = case.data.vertices[case.data.loops[li].vertex_index].co
            s = co.y / (width + 2 * margin) + 0.5 if abs(poly.normal.x) > 0.5 else co.x / depth + 0.5
            t = (co.z - (front_top - height / 2)) / (height + 2 * margin) + 0.5
            uv.data[li].uv = (fl + (fr - fl) * s, 1.0 - fb + (fb - ft) * min(max(t, 0.0), 1.0))
    sticker_uv = case.data.uv_layers.new(name="StickerUV")
    for loop_uv in sticker_uv.data:
        loop_uv.uv = (-0.9296875, 0.0)
    # Front face (+X), slightly in front of the case.
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(depth + 0.0002, 0, front_top - height / 2),
                                     rotation=(0, math.pi / 2, 0))
    front = bpy.context.active_object
    front.scale = (height, width, 1.0)
    bpy.ops.object.transform_apply(rotation=True, scale=True)
    if front.data.polygons[0].normal.x < 0:
        front.data.flip_normals()
    front.data.materials.append(slab_mat)
    uv0 = front.data.uv_layers.active
    uv1 = front.data.uv_layers.new(name="StickerUV")
    card_h = (bottom - SLAB_CARD_TOP_PX) * px
    for li, loop in enumerate(front.data.loops):
        co = front.data.vertices[loop.vertex_index].co
        s = co.y / width + 0.5                         # 0 left .. 1 right, seen from +X
        t = (co.z - (front_top - height / 2)) / height + 0.5   # 0 bottom .. 1 top
        uv0.data[li].uv = ((left + s * (right - left)) / 1024.0, 1.0 - (bottom - t * (bottom - top)) / 1024.0)
        uv1.data[li].uv = (s, t * height / card_h)
    # Hanger between chain and case.
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.0012, depth=0.004,
                                        location=(depth / 2, 0, z - 0.002))
    hanger = bpy.context.active_object
    hanger.data.materials.append(chain_mat)
    for obj in links + [hanger]:
        obj.data.uv_layers.new(name="StickerUV")
    return join(links + [hanger, case, front], "demo_sticker_slab")


def export(obj, name):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    path = os.path.join(OUT, MODELS, name + ".glb")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True,
                              export_materials="EXPORT", export_image_format="NONE",
                              export_yup=True, export_apply=True)
    return f"{MODELS}/{name}.glb"


# ---------------------------------------------------------------------------
# Icons (Workbench render with the color textures)
# ---------------------------------------------------------------------------

def render_icon(obj, textures_by_slot, name):
    scene = bpy.context.scene
    saved = list(obj.data.materials)
    for i, mat in enumerate(saved):
        tex = textures_by_slot.get(mat.name)
        if not tex:
            continue
        preview = mat.copy()
        nodes = preview.node_tree.nodes
        img_node = nodes.new("ShaderNodeTexImage")
        img_node.image = bpy.data.images.load(os.path.join(OUT, tex))
        preview.node_tree.links.new(img_node.outputs["Color"], nodes["Principled BSDF"].inputs["Base Color"])
        obj.data.materials[i] = preview
    cam_data = bpy.data.cameras.new("icon_cam")
    cam_data.type = "ORTHO"
    dims = obj.dimensions
    cam_data.ortho_scale = max(dims.y, dims.z) * 1.15
    cam = bpy.data.objects.new("icon_cam", cam_data)
    scene.collection.objects.link(cam)
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    center = sum(corners, Vector()) / 8.0
    cam.location = (0.2, center.y, center.z)
    cam.rotation_euler = (math.pi / 2, 0, math.pi / 2)
    scene.camera = cam
    r = scene.render
    r.engine = "BLENDER_WORKBENCH"
    r.resolution_x = r.resolution_y = 256
    r.film_transparent = True
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGBA"
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "TEXTURE"
    shading.show_cavity = True
    path = os.path.join(OUT, ICONS, name + ".png")
    r.filepath = path
    try:
        bpy.ops.render.render(write_still=True)
    except RuntimeError as exc:
        print(f"icon render failed ({exc}), no icon for {name}")
        path = ""
    for i, mat in enumerate(saved):
        obj.data.materials[i] = mat
    bpy.data.objects.remove(cam)
    return f"{ICONS}/{name}.png" if path else ""


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

def main():
    os.makedirs(os.path.join(OUT, MODELS), exist_ok=True)
    os.makedirs(os.path.join(OUT, ICONS), exist_ok=True)
    reset()
    chain_tex = chain_textures()
    gem_tex = gem_textures()
    flask_tex = flask_textures()
    materials = {
        "demo/demo_chain.vmat": {
            "shader": "csgo_weapon.vfx",
            "textures": chain_tex,
            "params": {"g_vMetalnessRemapRange": [0, 1, 0, 0], "g_flModelTintAmount": 1,
                       "g_vColorTint": [1, 1, 1, 0]},
            "dynamic": {},
        },
        "demo/demo_gem_drop.vmat": {
            "shader": "csgo_weapon.vfx",
            "textures": gem_tex,
            "params": {
                "F_ENABLE_ADJUSTMENTS": 1, "F_TINT_MASK": 1, "F_GLITTER": 1, "F_ENABLE_SFX_MASK": 1,
                "g_fHueShift": 0.0, "g_fSaturation": 1.0, "g_fBrightness": 1.0, "g_fContrast": 1.0,
                "g_fGlitterIntensity": 0.35, "g_fGlitterScale": 3.0, "g_fGlitterRainbowBalance": 0.0,
                "g_fGlitterRainbowSpread": 0.6, "g_vMetalnessRemapRange": [0, 1, 0, 0],
                "g_flModelTintAmount": 1, "g_vColorTint": [1, 1, 1, 0],
            },
            # Same shape as the real charms: hue over the whole pattern range,
            # saturation boost on rare high patterns.
            "dynamic": {
                "g_fHueShift": "return lerp(-150,150,$KeychainSeed);",
                "g_fSaturation": "return lerp(1,1.6,pow($KeychainSeed,3));",
                "g_fGlitterRainbowBalance": "return $KeychainSeed;",
            },
        },
        "demo/demo_fuel_flask.vmat": {
            "shader": "csgo_simple_liquid.vfx",
            "textures": flask_tex,
            "params": {
                "g_vLiquidColor": [0.8, 0.078, 0.188, 0], "g_flLiquidLevelHeight": 0.6,
                "g_flLiquidBrightness": 2.0, "g_flLiquidRoughness": 0.1, "g_flBrightenEmptyArea": 0.2,
                "g_flWaterLineStrength": 0.8, "g_flLiquidInnerGlow": 0.0,
                "g_flMaskMinimum": 0.0, "g_flMaskMaximum": 1.0,
            },
            # Butane Buddy's formulas: color over the whole range, level every 1000 patterns.
            "dynamic": {
                "g_flLiquidColorHueShift": "return lerp(0,320,$KeychainSeed);",
                "g_flLiquidLevelHeight": "return lerp(.45,.8,frac($KeychainSeed*100));",
            },
        },
    }

    gem = build_gem()
    gem_icon = render_icon(gem, {"demo_gem": gem_tex["g_tColor"], "demo_chain": chain_tex["g_tColor"]},
                           "demo_gem_drop")
    gem_model = export(gem, "demo_gem_drop")
    reset()
    flask = build_flask()
    flask_icon = render_icon(flask, {"demo_flask": flask_tex["g_tColorA"],
                                     "demo_chain": chain_tex["g_tColor"]}, "demo_fuel_flask")
    flask_model = export(flask, "demo_fuel_flask")
    reset()
    slab_tex = slab_textures()
    slab = build_slab()
    slab_icon = render_icon(slab, {"demo_slab": slab_tex["g_tColor"], "demo_chain": chain_tex["g_tColor"]},
                            "demo_sticker_slab")
    slab_model = export(slab, "demo_sticker_slab")

    materials["demo/demo_sticker_slab.vmat"] = {
        "shader": "csgo_weapon.vfx",
        "textures": slab_tex,
        "params": {"F_STICKERS": 1, "F_OPAQUE_REFRACT": 1, "F_TINT_MASK": 1, "g_flModelTintAmount": 1,
                   "g_vColorTint": [1, 1, 1, 0], "g_vMetalnessRemapRange": [0, 1, 0, 0],
                   "g_flRefractOpacity": 0.9, "g_flRefractBrightness": 4, "g_flRefractBlur": 0.35},
        # The CS2 slab's expression: label frame in the sticker's rarity color.
        "dynamic": {"g_vColorTint": "return exists($sticker_rarity_color) ? $sticker_rarity_color : float3(1,1,1);"},
    }
    write_sticker_catalog()

    catalog = {
        "version": 1,
        "generator": "cs.charm tests/fixtures/generate_fixtures.py",
        "note": "Test charms made from scratch, no game assets.",
        "charms": [
            {
                "id": "demo_gem_drop", "name": "Demo Gem Drop", "collection": "cs.charm Demo",
                "rarity": "mythical", "model": gem_model, "icon": gem_icon,
                "slots": {"demo_chain": "demo/demo_chain.vmat", "demo_gem": "demo/demo_gem_drop.vmat"},
                "tags": ["demo", "glitter"],
            },
            {
                "id": "demo_fuel_flask", "name": "Demo Fuel Flask", "collection": "cs.charm Demo",
                "rarity": "ancient", "model": flask_model, "icon": flask_icon,
                "slots": {"demo_chain": "demo/demo_chain.vmat", "demo_flask": "demo/demo_fuel_flask.vmat"},
                "tags": ["demo", "liquid"],
            },
            {
                "id": "demo_sticker_slab", "name": "Demo Sticker Slab", "collection": "cs.charm Demo",
                "rarity": "common", "model": slab_model, "icon": slab_icon,
                "slots": {"demo_chain": "demo/demo_chain.vmat", "demo_slab": "demo/demo_sticker_slab.vmat"},
                "tags": ["demo", "slab", "sticker"],
            },
        ],
        "materials": materials,
    }
    with open(os.path.join(OUT, "catalog.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(catalog, fh, indent=1)
        fh.write("\n")
    print(f"demo charms -> {OUT}")


if __name__ == "__main__":
    main()
    sys.exit(0)
