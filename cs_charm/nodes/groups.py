# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Reusable shader node groups for CS2 charm materials.

* ``CS2 Charm Weapon``  csgo_weapon.vfx, used by almost every charm
* ``CS2 Charm Liquid``  csgo_simple_liquid.vfx (Butane Buddy)
* ``CS2 Charm UV``      UV transform (scale / offset / rotation) for the
                        detail texture and the glitter normal map

Groups take *texture samples* as inputs instead of containing Image Texture
nodes, so one group serves every charm. material.py creates the image
nodes and wires them in. Input names match library/shading.py.

csgo_weapon.vfx as implemented here (approximation, Valve does not
document the shader):

* color adjustments (hue in degrees, saturation, brightness, contrast)
  apply where the tint mask is white (no tint mask = everywhere)
* detail texture is multiplied in (default detail = 1x1 white), optionally
  only inside the tint mask
* ``g_tMetalness`` is packed: R roughness, G metalness, B effect mask;
  roughness gets brightness/contrast, metalness is remapped
* glitter: flake normal map (alpha = flake mask) tilts the normal and adds
  rainbow sparkle inside the effect mask
* iridescence: thin film, pearlescent: hue shift toward glancing angles,
  both inside the effect mask
"""

import bpy

from .builder import GroupBuilder, principled, set_bsdf

# Bump when group contents change; outdated groups are renamed (existing
# materials keep working) and rebuilt.
GROUP_VERSION = 1
VERSION_KEY = "cs_charm_version"

WEAPON_GROUP = "CS2 Charm Weapon"
LIQUID_GROUP = "CS2 Charm Liquid"
UV_GROUP = "CS2 Charm UV"

FLAT_NORMAL = (0.5, 0.5, 1.0, 1.0)
WHITE = (1.0, 1.0, 1.0, 1.0)


def _hue_shift(b, color, degrees, fac=1.0, saturation=1.0, x=None, y=0):
    """Hue/Saturation node with the hue given in degrees (wraps around)."""
    hue = b.math("FRACT", b.math("ADD", b.math("DIVIDE", degrees, 360.0, x=x, y=y), 0.5, x=x, y=y), x=x, y=y)
    n = b.node("ShaderNodeHueSaturation", x, y)
    b.set_or_link(n, "Hue", hue)
    b.set_or_link(n, "Saturation", saturation)
    b.set_or_link(n, "Value", 1.0)
    b.set_or_link(n, "Fac", fac)
    b.set_or_link(n, "Color", color)
    return n.outputs["Color"]


def _contrast(b, value, contrast, kind="FLOAT", x=None, y=0):
    """(value - 0.5) * contrast + 0.5 for floats or colors."""
    if kind == "FLOAT":
        return b.math("ADD", b.math("MULTIPLY", b.math("SUBTRACT", value, 0.5, x=x, y=y), contrast, x=x, y=y),
                      0.5, x=x, y=y)
    centered = b.vmath("SUBTRACT", value, (0.5, 0.5, 0.5), x=x, y=y)
    return b.vmath("ADD", b.vmath("SCALE", centered, scale=contrast, x=x, y=y), (0.5, 0.5, 0.5), x=x, y=y)


# ---------------------------------------------------------------------------
# UV helper
# ---------------------------------------------------------------------------

def _build_uv(tree):
    b = GroupBuilder(tree)
    uv = b.input("UV", "VECTOR", hide_value=True,
                 description="Texture coordinates (UV map of the charm)")
    sx = b.input("Scale X", default=1.0)
    sy = b.input("Scale Y", default=1.0)
    ox = b.input("Offset X", default=0.0)
    oy = b.input("Offset Y", default=0.0)
    rot = b.input("Rotation", default=0.0, description="Rotation around the UV center in degrees")
    out = b.output("Vector", "VECTOR")

    b.column(-900)
    centered = b.vmath("SUBTRACT", uv, (0.5, 0.5, 0.0))
    b.column(-650)
    rotate = b.node("ShaderNodeVectorRotate", rotation_type="Z_AXIS")
    b.set_or_link(rotate, "Vector", centered)
    b.set_or_link(rotate, "Angle", b.math("RADIANS", rot))
    b.column(-400)
    scaled = b.vmath("MULTIPLY", rotate.outputs[0], b.combine(sx, sy, 1.0))
    b.column(-150)
    shifted = b.vmath("ADD", scaled, b.combine(b.math("ADD", ox, 0.5), b.math("ADD", oy, 0.5), 0.0))
    b.link(shifted, out)


# ---------------------------------------------------------------------------
# csgo_weapon.vfx
# ---------------------------------------------------------------------------

def _build_weapon(tree):
    b = GroupBuilder(tree)
    # Texture samples
    color = b.input("Color", "COLOR", default=(0.8, 0.8, 0.8, 1.0), description="g_tColor")
    normal = b.input("Normal Map", "COLOR", default=FLAT_NORMAL, description="g_tNormal (tangent space)")
    pack = b.input("Metal Pack", "COLOR", default=(0.5, 0.0, 0.0, 1.0),
                   description="g_tMetalness: R roughness, G metalness, B effect mask")
    ao = b.input("Ambient Occlusion", default=1.0, lo=0.0, hi=1.0, factor=True)
    tint = b.input("Tint Mask", default=1.0, lo=0.0, hi=1.0, factor=True,
                   description="Where color adjustments apply (1 without tint mask)")
    detail = b.input("Detail", "COLOR", default=WHITE, description="g_tDetail, multiplied into the color")
    glitter_n = b.input("Glitter Normal", "COLOR", default=FLAT_NORMAL, description="g_tGlitterNormal RGB")
    glitter_m = b.input("Glitter Mask", default=0.0, lo=0.0, hi=1.0, factor=True,
                        description="g_tGlitterNormal alpha")
    # Parameters
    hue = b.input("Hue Shift", default=0.0, lo=-3600.0, hi=3600.0, description="g_fHueShift in degrees")
    sat = b.input("Saturation", default=1.0, lo=0.0, hi=10.0, description="g_fSaturation")
    bright = b.input("Brightness", default=1.0, lo=0.0, hi=10.0, description="g_fBrightness")
    contrast = b.input("Contrast", default=1.0, lo=0.0, hi=10.0, description="g_fContrast")
    color_tint = b.input("Color Tint", "COLOR", default=WHITE, description="g_vColorTint")
    tint_amount = b.input("Tint Amount", default=1.0, lo=0.0, hi=1.0, factor=True, description="g_flModelTintAmount")
    detail_blend = b.input("Detail Blend", default=0.0, lo=0.0, hi=1.0, factor=True,
                           description="g_fDetailBlendFactor")
    detail_by_tint = b.input("Detail By Tint Mask", default=0.0, lo=0.0, hi=1.0, factor=True,
                             description="g_bMaskDetailTextureByTintMask")
    r_bright = b.input("Roughness Brightness", default=1.0, lo=0.0, hi=10.0,
                       description="g_fTextureRoughnessBrightness")
    r_contrast = b.input("Roughness Contrast", default=1.0, lo=0.0, hi=10.0,
                         description="g_fTextureRoughnessContrast")
    r_by_tint = b.input("Roughness By Tint Mask", default=0.0, lo=0.0, hi=1.0, factor=True,
                        description="g_bMaskRoughnessAdjustmentsByTintMask")
    m_min = b.input("Metal Min", default=0.0, lo=0.0, hi=1.0, description="g_vMetalnessRemapRange.x")
    m_max = b.input("Metal Max", default=1.0, lo=0.0, hi=1.0, description="g_vMetalnessRemapRange.y")
    g_int = b.input("Glitter Intensity", default=0.0, lo=0.0, hi=4.0, description="g_fGlitterIntensity")
    g_rainbow = b.input("Glitter Rainbow", default=0.0, lo=-4.0, hi=4.0,
                        description="g_fGlitterRainbowBalance: shifts the sparkle hues")
    g_spread = b.input("Glitter Rainbow Spread", default=0.0, lo=0.0, hi=4.0,
                       description="g_fGlitterRainbowSpread: how colorful the sparkle is")
    irid = b.input("Iridescence", default=0.0, lo=0.0, hi=4.0, description="g_flIridescentStrength")
    irid_scale = b.input("Iridescence Scale", default=1.0, lo=0.0, hi=10.0, description="g_flIridescentScale")
    irid_hue = b.input("Iridescence Hue", default=0.5, lo=-4.0, hi=4.0, description="g_flIridescentHueShift")
    pearl = b.input("Pearlescent", default=0.0, lo=0.0, hi=360.0,
                    description="g_flPearlescentScale: hue shift in degrees toward glancing angles")
    ao_strength = b.input("AO Strength", default=1.0, lo=0.0, hi=1.0, factor=True)
    n_strength = b.input("Normal Strength", default=1.0, lo=0.0, hi=10.0)
    out = b.output("BSDF")

    rough, metal, sfx = b.separate_color(pack, x=-950, y=-600)

    # -- color ---------------------------------------------------------------
    b.column(-900)
    shifted = _hue_shift(b, color, hue, saturation=sat, y=300)
    b.column(-700)
    brightened = b.vmath("SCALE", shifted, scale=bright, y=300)
    adjusted = _contrast(b, brightened, contrast, kind="COLOR", y=300)
    b.column(-500)
    col = b.mix("RGBA", tint, color, adjusted, y=300)
    detail_mask = b.math("MULTIPLY", detail_blend,
                         b.mix("FLOAT", detail_by_tint, 1.0, tint, y=100), y=100)
    col = b.mix("RGBA", detail_mask, col, detail, blend="MULTIPLY", y=300)
    col = b.mix("RGBA", tint_amount, col, color_tint, blend="MULTIPLY", y=300)
    # Pearlescent: hue drifts toward glancing angles inside the effect mask.
    b.column(-300)
    facing = b.node("ShaderNodeLayerWeight", y=500)
    b.set_or_link(facing, "Blend", 0.5)
    pearl_deg = b.math("MULTIPLY", facing.outputs["Facing"], pearl, y=500)
    col = _hue_shift(b, col, pearl_deg, fac=sfx, y=300)
    col = b.mix("RGBA", ao_strength, col, ao, blend="MULTIPLY", y=300)

    # -- roughness / metalness -----------------------------------------------
    b.column(-700)
    r_adj = _contrast(b, b.math("MULTIPLY", rough, r_bright, y=-500), r_contrast, y=-500)
    r_mask = b.mix("FLOAT", r_by_tint, 1.0, tint, y=-700)
    b.column(-450)
    rough = b.math("MINIMUM", b.math("MAXIMUM", b.mix("FLOAT", r_mask, rough, r_adj, y=-500), 0.0, y=-500),
                   1.0, y=-500)
    metal = b.map_range(metal, 0.0, 1.0, m_min, m_max, y=-800)

    # -- glitter ---------------------------------------------------------------
    b.column(-700)
    g_fac = b.math("MULTIPLY", b.math("MULTIPLY", glitter_m, sfx, y=-1100), g_int, y=-1100, clamp=True)
    gx, gy, _gz = b.separate_color(glitter_n, y=-1300)
    b.column(-450)
    sparkle_hue = b.math("MULTIPLY", b.math("ADD", b.math("ADD", gx, gy, y=-1300), g_rainbow, y=-1300),
                         360.0, y=-1300)
    sparkle = _hue_shift(b, (1.0, 0.25, 0.25, 1.0), sparkle_hue, y=-1300)
    b.column(-250)
    sparkle = b.mix("RGBA", b.math("MINIMUM", g_spread, 1.0, y=-1300), WHITE, sparkle, y=-1300)
    col = b.mix("RGBA", b.math("MULTIPLY", g_fac, 0.6, y=-1100), col, sparkle, y=300)
    metal = b.mix("FLOAT", g_fac, metal, 1.0, y=-800)
    rough = b.mix("FLOAT", g_fac, rough, 0.12, y=-500)

    # -- normals -----------------------------------------------------------------
    b.column(-300)
    base_n = b.node("ShaderNodeNormalMap", y=-200)
    b.set_or_link(base_n, "Strength", n_strength)
    b.set_or_link(base_n, "Color", normal)
    flake_n = b.node("ShaderNodeNormalMap", y=-400)
    b.set_or_link(flake_n, "Strength", 1.0)
    b.set_or_link(flake_n, "Color", glitter_n)
    b.column(0)
    nrm = b.mix("VECTOR", g_fac, base_n.outputs[0], flake_n.outputs[0], y=-300)
    nrm = b.vmath("NORMALIZE", nrm, y=-300)

    # -- iridescence (thin film) ---------------------------------------------
    b.column(-250)
    irid_amount = b.math("MULTIPLY", b.math("MINIMUM", irid, 1.0, y=-1600), sfx, y=-1600)
    film = b.math("MULTIPLY", b.math("ADD", b.math("MULTIPLY", irid_hue, 600.0, y=-1700), 150.0, y=-1700),
                  b.math("MAXIMUM", irid_scale, 0.1, y=-1700), y=-1700)
    film = b.math("MULTIPLY", film, irid_amount, y=-1600)

    bsdf = principled(b, x=400, y=0)
    set_bsdf(b, bsdf, Base_Color=col, Metallic=metal, Roughness=rough, Normal=nrm,
             Thin_Film_Thickness=film)
    b.link(bsdf.outputs[0], out)


# ---------------------------------------------------------------------------
# csgo_simple_liquid.vfx
# ---------------------------------------------------------------------------

def _build_liquid(tree):
    b = GroupBuilder(tree)
    color = b.input("Color", "COLOR", default=(0.6, 0.6, 0.6, 1.0), description="g_tColorA RGB")
    print_alpha = b.input("Color Alpha", default=1.0, lo=0.0, hi=1.0, factor=True,
                          description="g_tColorA alpha: opaque print / body (1) or window (0)")
    normal = b.input("Normal Map", "COLOR", default=FLAT_NORMAL, description="g_tNormalA")
    mask = b.input("Liquid Mask", default=1.0, lo=0.0, hi=1.0, factor=True,
                   description="g_tLiquidMask: where the liquid is visible")
    bottom = b.input("Bottom", default=-1.0, description="Object-space Z of an empty container")
    top = b.input("Top", default=0.0, description="Object-space Z of a full container")
    liquid = b.input("Liquid Color", "COLOR", default=(0.8, 0.08, 0.19, 1.0), description="g_vLiquidColor")
    hue = b.input("Liquid Hue Shift", default=0.0, lo=-3600.0, hi=3600.0,
                  description="g_flLiquidColorHueShift in degrees (pattern driven on Butane Buddy)")
    level = b.input("Fill Level", default=0.5, lo=0.0, hi=1.0, factor=True,
                    description="g_flLiquidLevelHeight (pattern driven on Butane Buddy)")
    l_bright = b.input("Liquid Brightness", default=1.0, lo=0.0, hi=10.0, description="g_flLiquidBrightness")
    l_rough = b.input("Liquid Roughness", default=0.1, lo=0.0, hi=1.0, factor=True,
                      description="g_flLiquidRoughness")
    l_emit = b.input("Liquid Emission", default=0.0, lo=0.0, hi=100.0, description="g_flLiquidEmissiveStrength")
    glow = b.input("Inner Glow", default=0.0, lo=0.0, hi=10.0, description="g_flLiquidInnerGlow")
    empty = b.input("Brighten Empty", default=0.2, lo=0.0, hi=10.0, description="g_flBrightenEmptyArea")
    waterline = b.input("Waterline", default=0.8, lo=0.0, hi=10.0, description="g_flWaterLineStrength")
    m_min = b.input("Mask Min", default=0.0, lo=0.0, hi=1.0, description="g_flMaskMinimum")
    m_max = b.input("Mask Max", default=1.0, lo=0.0, hi=1.0, description="g_flMaskMaximum")
    color_tint = b.input("Color Tint", "COLOR", default=WHITE, description="g_vColorTint")
    glass_rough = b.input("Glass Roughness", default=0.05, lo=0.0, hi=1.0, factor=True)
    body_rough = b.input("Body Roughness", default=0.35, lo=0.0, hi=1.0, factor=True)
    body_metal = b.input("Body Metallic", default=0.0, lo=0.0, hi=1.0, factor=True)
    n_strength = b.input("Normal Strength", default=1.0, lo=0.0, hi=10.0)
    out = b.output("BSDF")

    # Normalized height inside the container (0 bottom, 1 top).
    b.column(-1000)
    coords = b.node("ShaderNodeTexCoord", y=-200)
    _x, _y, z = b.separate(coords.outputs["Object"], y=-200)
    b.column(-800)
    height = b.map_range(z, bottom, top, y=-200)
    window = b.map_range(mask, m_min, m_max, y=-400)
    b.column(-600)
    edge = 0.004
    filled = b.map_range(height, b.math("ADD", level, edge, y=-200), b.math("SUBTRACT", level, edge, y=-300),
                         y=-200, interpolation="SMOOTHSTEP")
    line = b.map_range(b.math("ABSOLUTE", b.math("SUBTRACT", height, level, y=-500), y=-500), 0.02, 0.0,
                       y=-500, interpolation="SMOOTHSTEP")
    line = b.math("MULTIPLY", line, waterline, y=-500)

    # Liquid color: hue shifted, brightness applied.
    b.column(-700)
    liq = _hue_shift(b, liquid, hue, y=200)
    b.column(-450)
    liq = b.vmath("SCALE", liq, scale=b.math("MULTIPLY", l_bright, 0.5, y=200), y=200)
    liq_lit = b.vmath("ADD", liq, b.vmath("SCALE", (1.0, 1.0, 1.0), scale=line, y=100), y=200)
    emit_strength = b.math("ADD", l_emit, b.math("MULTIPLY", glow, 2.0, y=50), y=50)

    nmap = b.node("ShaderNodeNormalMap", x=-450, y=-700)
    b.set_or_link(nmap, "Strength", n_strength)
    b.set_or_link(nmap, "Color", normal)
    tinted = b.mix("RGBA", 1.0, color, color_tint, blend="MULTIPLY", x=-450, y=500)

    # Three surfaces: printed body, filled window, empty window.
    body = principled(b, x=0, y=700)
    set_bsdf(b, body, Base_Color=tinted, Metallic=body_metal, Roughness=body_rough, Normal=nmap.outputs[0])
    fluid = principled(b, x=0, y=200)
    set_bsdf(b, fluid, Base_Color=liq_lit, Roughness=l_rough, Normal=nmap.outputs[0],
             Coat_Weight=1.0, Coat_Roughness=glass_rough, Emission_Color=liq, Emission_Strength=emit_strength)
    glass_col = b.mix("RGBA", b.math("MINIMUM", b.math("MULTIPLY", empty, 0.3, x=-200, y=-300), 1.0,
                                     x=-200, y=-300), tinted, WHITE, x=-200, y=-300)
    glass = principled(b, x=0, y=-300)
    set_bsdf(b, glass, Base_Color=glass_col, Roughness=glass_rough, Transmission_Weight=1.0,
             IOR=1.45, Normal=nmap.outputs[0])

    b.column(300)
    interior = b.node("ShaderNodeMixShader", y=0)
    b.set_or_link(interior, 0, filled)
    b.link(glass.outputs[0], interior.inputs[1])
    b.link(fluid.outputs[0], interior.inputs[2])
    b.column(500)
    show_window = b.math("MULTIPLY", window, b.math("SUBTRACT", 1.0, print_alpha, y=300), y=300)
    final = b.node("ShaderNodeMixShader", y=200)
    b.set_or_link(final, 0, show_window)
    b.link(body.outputs[0], final.inputs[1])
    b.link(interior.outputs[0], final.inputs[2])
    b.link(final.outputs[0], out)


_BUILDERS = {
    "UV": (UV_GROUP, _build_uv),
    "WEAPON": (WEAPON_GROUP, _build_weapon),
    "LIQUID": (LIQUID_GROUP, _build_liquid),
}


def ensure_group(key):
    """Return the node group for ``key``, building or upgrading it if needed."""
    name, build = _BUILDERS[key]
    tree = bpy.data.node_groups.get(name)
    if tree is not None and tree.get(VERSION_KEY) == GROUP_VERSION:
        return tree
    if tree is not None:
        tree.name = f"{name} (v{tree.get(VERSION_KEY, 0)})"
    tree = bpy.data.node_groups.new(name, "ShaderNodeTree")
    tree[VERSION_KEY] = GROUP_VERSION
    build(tree)
    return tree


def ensure_all():
    return [ensure_group(k) for k in _BUILDERS]
