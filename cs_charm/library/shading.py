# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Mapping CS2 shader parameters to the inputs of the cs.charm node setup.

Pure Python (no bpy): the material builder asks ``node_values`` which
node inputs to set for a material spec and a pattern, so the same table
drives material creation, pattern changes and the tests.

Node names inside each charm material:

    CHARM_MAIN        "CS2 Charm Weapon" or "CS2 Charm Liquid" group
    CHARM_DETAIL_UV   "CS2 Charm UV" group feeding the detail texture
    CHARM_GLITTER_UV  "CS2 Charm UV" group feeding the glitter normal map

Valve does not document csgo_weapon.vfx / csgo_simple_liquid.vfx; the
meaning of each parameter is inferred from names, defaults and the
DynamicParams that drive them, so the node setups are approximations.
"""

from dataclasses import dataclass

from . import patterns
from .catalog import SHADER_LIQUID

NODE_MAIN = "CHARM_MAIN"
NODE_DETAIL_UV = "CHARM_DETAIL_UV"
NODE_GLITTER_UV = "CHARM_GLITTER_UV"

KIND_FLOAT = "FLOAT"
KIND_COLOR = "COLOR"  # vector param -> RGBA input
KIND_X = "X"          # first component of a vector param
KIND_Y = "Y"          # second component


@dataclass(frozen=True)
class Binding:
    param: str
    node: str
    input: str
    kind: str = KIND_FLOAT


WEAPON_BINDINGS = (
    Binding("g_fHueShift", NODE_MAIN, "Hue Shift"),
    Binding("g_fSaturation", NODE_MAIN, "Saturation"),
    Binding("g_fBrightness", NODE_MAIN, "Brightness"),
    Binding("g_fContrast", NODE_MAIN, "Contrast"),
    Binding("g_vColorTint", NODE_MAIN, "Color Tint", KIND_COLOR),
    Binding("g_flModelTintAmount", NODE_MAIN, "Tint Amount"),
    Binding("g_fDetailBlendFactor", NODE_MAIN, "Detail Blend"),
    Binding("g_bMaskDetailTextureByTintMask", NODE_MAIN, "Detail By Tint Mask"),
    Binding("g_fTextureRoughnessBrightness", NODE_MAIN, "Roughness Brightness"),
    Binding("g_fTextureRoughnessContrast", NODE_MAIN, "Roughness Contrast"),
    Binding("g_bMaskRoughnessAdjustmentsByTintMask", NODE_MAIN, "Roughness By Tint Mask"),
    Binding("g_vMetalnessRemapRange", NODE_MAIN, "Metal Min", KIND_X),
    Binding("g_vMetalnessRemapRange", NODE_MAIN, "Metal Max", KIND_Y),
    Binding("g_fGlitterIntensity", NODE_MAIN, "Glitter Intensity"),
    Binding("g_fGlitterRainbowBalance", NODE_MAIN, "Glitter Rainbow"),
    Binding("g_fGlitterRainbowSpread", NODE_MAIN, "Glitter Rainbow Spread"),
    Binding("g_flIridescentStrength", NODE_MAIN, "Iridescence"),
    Binding("g_flIridescentScale", NODE_MAIN, "Iridescence Scale"),
    Binding("g_flIridescentHueShift", NODE_MAIN, "Iridescence Hue"),
    Binding("g_flPearlescentScale", NODE_MAIN, "Pearlescent"),
    Binding("g_vDetailTexCoordScale", NODE_DETAIL_UV, "Scale X", KIND_X),
    Binding("g_vDetailTexCoordScale", NODE_DETAIL_UV, "Scale Y", KIND_Y),
    Binding("g_vDetailTexCoordOffset", NODE_DETAIL_UV, "Offset X", KIND_X),
    Binding("g_vDetailTexCoordOffset", NODE_DETAIL_UV, "Offset Y", KIND_Y),
    Binding("g_flDetailTexCoordRotation", NODE_DETAIL_UV, "Rotation"),
    Binding("g_fGlitterScale", NODE_GLITTER_UV, "Scale X"),
    Binding("g_fGlitterScale", NODE_GLITTER_UV, "Scale Y"),
)

LIQUID_BINDINGS = (
    Binding("g_vLiquidColor", NODE_MAIN, "Liquid Color", KIND_COLOR),
    Binding("g_flLiquidColorHueShift", NODE_MAIN, "Liquid Hue Shift"),
    Binding("g_flLiquidLevelHeight", NODE_MAIN, "Fill Level"),
    Binding("g_flLiquidBrightness", NODE_MAIN, "Liquid Brightness"),
    Binding("g_flLiquidRoughness", NODE_MAIN, "Liquid Roughness"),
    Binding("g_flLiquidEmissiveStrength", NODE_MAIN, "Liquid Emission"),
    Binding("g_flLiquidInnerGlow", NODE_MAIN, "Inner Glow"),
    Binding("g_flBrightenEmptyArea", NODE_MAIN, "Brighten Empty"),
    Binding("g_flWaterLineStrength", NODE_MAIN, "Waterline"),
    Binding("g_flMaskMinimum", NODE_MAIN, "Mask Min"),
    Binding("g_flMaskMaximum", NODE_MAIN, "Mask Max"),
    Binding("g_vColorTint", NODE_MAIN, "Color Tint", KIND_COLOR),
)

# Texture slots per shader: compiled texture parameter -> (role, colorspace).
# Roles are the image nodes' names inside the material ("TEX_<role>").
WEAPON_TEXTURES = {
    "g_tColor": ("COLOR", "sRGB"),
    "g_tNormal": ("NORMAL", "Non-Color"),
    "g_tMetalness": ("METAL", "Non-Color"),  # R roughness, G metalness, B sfx mask
    "g_tAmbientOcclusion": ("AO", "Non-Color"),
    "g_tTintMask": ("TINT", "Non-Color"),
    "g_tDetail": ("DETAIL", "sRGB"),
    "g_tGlitterNormal": ("GLITTER", "Non-Color"),  # A = glitter mask
}
LIQUID_TEXTURES = {
    "g_tColorA": ("COLOR", "sRGB"),          # A = opacity of the print
    "g_tColor": ("COLOR", "sRGB"),
    "g_tNormalA": ("NORMAL", "Non-Color"),
    "g_tNormal": ("NORMAL", "Non-Color"),
    "g_tLiquidMask": ("LIQUID", "Non-Color"),
    "g_tMetalnessA": ("METAL", "Non-Color"),
}

# Display names for the pattern-driven parameters (Active Charm panel).
PARAM_LABELS = {
    "g_fHueShift": "Hue Shift",
    "g_fSaturation": "Saturation",
    "g_fBrightness": "Brightness",
    "g_fContrast": "Contrast",
    "g_flLiquidColorHueShift": "Liquid Hue",
    "g_flLiquidLevelHeight": "Fill Level",
    "g_vDetailTexCoordOffset": "Pattern Offset",
    "g_vDetailTexCoordScale": "Pattern Scale",
    "g_flDetailTexCoordRotation": "Pattern Rotation",
    "g_fGlitterRainbowBalance": "Glitter Rainbow",
    "g_fGlitterScale": "Glitter Scale",
    "g_fGlitterIntensity": "Glitter Intensity",
    "g_vMetalnessRemapRange": "Metalness Range",
    "g_flPearlescentScale": "Pearlescent",
    "g_fTextureRoughnessContrast": "Roughness Contrast",
    "g_fTextureRoughnessBrightness": "Roughness Brightness",
    "g_flIridescentStrength": "Iridescence",
}


def is_liquid(shader):
    return shader == SHADER_LIQUID


def bindings(shader):
    return LIQUID_BINDINGS if is_liquid(shader) else WEAPON_BINDINGS


def texture_roles(shader):
    return LIQUID_TEXTURES if is_liquid(shader) else WEAPON_TEXTURES


def _component(value, index):
    if isinstance(value, (list, tuple)):
        return float(value[index]) if len(value) > index else 0.0
    return float(value)


def _convert(value, kind):
    if kind == KIND_COLOR:
        vec = list(value) if isinstance(value, (list, tuple)) else [value] * 3
        vec = [float(v) for v in vec[:3]] + [0.0] * (3 - len(vec[:3]))
        return (vec[0], vec[1], vec[2], 1.0)
    if kind == KIND_X:
        return _component(value, 0)
    if kind == KIND_Y:
        return _component(value, 1)
    return _component(value, 0)


def _flag(params, name):
    try:
        return bool(int(params.get(name, 0)))
    except (TypeError, ValueError):
        return False


def pattern_values(spec, pattern):
    """Static params overlaid with the pattern's DynamicParams.
    Returns (params, errors)."""
    values = dict(spec.params)
    dynamic, errors = patterns.evaluate_dynamic(spec.dynamic, pattern)
    values.update(dynamic)
    return values, errors


def node_values(spec, pattern=0):
    """{(node name, input name): value} for a material spec at a pattern.
    Parameters the spec does not set keep the node group defaults."""
    params, _errors = pattern_values(spec, pattern)
    out = {}
    for b in bindings(spec.shader):
        if b.param in params:
            out[(b.node, b.input)] = _convert(params[b.param], b.kind)
    if not is_liquid(spec.shader):
        # Feature switches of csgo_weapon.vfx: disabled effects contribute nothing.
        if not _flag(params, "F_GLITTER"):
            out[(NODE_MAIN, "Glitter Intensity")] = 0.0
        if not _flag(params, "F_IRIDESCENCE"):
            out[(NODE_MAIN, "Iridescence")] = 0.0
        if not _flag(params, "F_ENABLE_ADJUSTMENTS"):
            for name in ("Hue Shift",):
                out[(NODE_MAIN, name)] = 0.0
            for name in ("Saturation", "Brightness", "Contrast", "Roughness Brightness", "Roughness Contrast"):
                out[(NODE_MAIN, name)] = 1.0
    return out


def pattern_summary(spec, pattern):
    """[(label, value)] of the pattern-driven parameters, for display."""
    dynamic, _errors = patterns.evaluate_dynamic(spec.dynamic, pattern)
    out = []
    for name in sorted(dynamic):
        out.append((PARAM_LABELS.get(name, name), dynamic[name]))
    return out


def format_value(name_or_label, value):
    if isinstance(value, tuple):
        return "(" + ", ".join(f"{v:.2f}" for v in value) + ")"
    if "Hue" in name_or_label or "Rotation" in name_or_label:
        return f"{value:.0f}°"
    if "Level" in name_or_label:
        return f"{value * 100:.0f} %"
    return f"{value:.3f}"
