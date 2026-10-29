# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Generate the two demo charms shipped with the add-on (run inside Blender):

    blender -b --factory-startup --python tools/generate_demo_charms.py

Writes cs_charm/charms/core/: catalog.json, the models (.glb), procedural
textures (PNG) and preview icons. Everything is made from scratch here, no
game assets. The demos use the same data layout as a real CS2 export, so
they exercise the whole pipeline:

* "Demo Gem Drop"    csgo_weapon.vfx: tint mask, hue/saturation pattern,
                     glitter flakes in the effect mask, metal chain
* "Demo Fuel Flask"  csgo_simple_liquid.vfx: liquid color and fill level
                     driven by the pattern (same formulas as Butane Buddy)

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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "cs_charm", "charms", "core")
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

    catalog = {
        "version": 1,
        "generator": "cs.charm tools/generate_demo_charms.py",
        "note": "Demo charms made from scratch, no game assets.",
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
