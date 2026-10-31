# cs.charm

Blender add-on that spawns CS2 charms (weapon keychains) as full 3D models
with their pattern applied: colors, detail, glitter and special effects
such as the fill level of the Butane Buddy follow the pattern number like
in the game. Charms can be placed interactively on a weapon, attached via
Parent or Child Of and optionally swing with rigid body physics.
Target: Blender 5.2, compatible back to 4.5.

**For plugin excluding the charm assets (CS2 export required) [⬇ Download cs_charm.zip (latest release)](https://github.com/ed3ntim/cs.charm/releases/latest/download/cs_charm.zip)**

**For the version including all charm assets visit my page [⬇ Download cs_charm-1.3.1 - all charms.zip](https://ed3n.gallery/apps/cs-charm/)**

## Installation

1. Download [`cs_charm.zip`](https://github.com/ed3ntim/cs.charm/releases/latest/download/cs_charm.zip)
   (all versions: [Releases](https://github.com/ed3ntim/cs.charm/releases)).
2. Blender: *Edit > Preferences > Get Extensions > ⌄ > Install from Disk...*
   and pick the zip (drag & drop onto the Blender window works too).
3. 3D Viewport sidebar (`N`), tab **cs.charm**.

The add-on ships with two demo charms (one with the standard charm shader,
one liquid charm). To use the real CS2 charms, export them from your own
game installation (see [CS2 charms](#cs2-charms)).

## Usage

1. **Library**: search by name, collection or tag, filter by collection
   and rarity. The info box shows rarity, effects (pattern, glitter,
   liquid, ...) and the inventory icon as preview.
2. **Placement**:
   - **Pattern** (0 to 100000) or the random button: every spawn gets a
     new random pattern when *Random* is on.
   - **Size**: *Absolute* (default) uses the CS2 model size in meters times
     *Scale*. *Relative* sets the charm height to a percentage of the
     target's longest side; about 7 % matches a charm on a rifle in any
     scene scale.
   - **Align**: *Hang* lets the charm hang down with its face pointing
     away from the surface. With *Rest on Surface* (default) it settles
     on the whole object around the attachment point, not just the face
     it is attached to: it hangs straight down from a wall, lies flat on
     a top (toward the target's center, along a rifle), follows a curved
     surface such as a sphere, tips over an edge and rolls a little to
     lie on slanted or uneven parts of a complex model. *Rotation* turns
     it around the vertical. Without *Rest on Surface* it only looks at
     the surface normal. *Surface* points the charm along the surface
     normal. The charm is lifted by the depth of its back, so it never
     cuts into the target; the offset (percentage of the charm height)
     adds to that.
   - **Attach**: Parent, Child Of or none. **Physics** adds the pendulum
     setup after placing.
   - **Place Interactively**: the charm follows the mouse over surfaces as
     a live preview. Wheel = rotate (Shift = fine), Ctrl+Wheel = scale,
     F = toggle Hang/Surface, LMB = place, Shift+LMB = place and continue,
     RMB/Esc = finish/cancel.
   - **Spawn on Selected**: onto the selected mesh, at the point closest to
     the 3D cursor (Shift+right-click on the surface sets the cursor).
   - **Manual (at Cursor)**: at the 3D cursor, facing along the cursor's
     -Y axis, attached to the active object if one is selected.
3. **Active Charm** (always just the active object, even with several
   charms selected): change the pattern (the material updates live, the
   panel lists what the pattern changes), scale, rotation, tilt, lean and
   offset, attach to another object, add or remove physics. *Set Anchor
   from Position* takes over a charm you moved by hand. *Material
   Parameters* exposes every input of the charm node groups.
   Duplicated charms (Shift+D, Alt+D) get their own mesh, materials and
   physics right away, so editing one copy never changes the others.

### Physics

*Add Physics* turns the charm into an active rigid body that hangs from
a small passive anchor through a ball joint (Generic Spring constraint; a
weak spring damps the turn around the hanging axis, like the friction of
the ring). A hidden "<charm> Weight" fixed to it puts the center of mass
into the charm, so gravity really makes it swing, and carries the
collision hull of the body without ring and chain. The anchor is parented
to the target, so moving or animating the weapon makes the charm swing.
A new rigid body world runs faster in scenes whose charms are scaled up
(e.g. weapons in inches), which equals real gravity for the charm. Play the timeline or bake the rigid body cache to see it.
Rigid bodies ignore parenting, so the charm itself is detached while
physics is on; *Remove Physics* restores the rest pose and the previous
attachment.

With *Collide with Target* (default) the charm also collides with the
weapon, including while the weapon is animated: a hidden passive
"<target> Collider" object shares the target's mesh and follows it, one
per target for all its charms. The weapon itself stays untouched. At the
start the charm rests in the simulation's own balance: *Add Physics*
simulates a moment with all animation frozen and takes that pose as the
start, so nothing twitches when the timeline starts (skipped for a charm
swung on purpose with tilt or lean). On dense weapon meshes this takes a
few seconds. Dense meshes also make the simulation slower; turn the
option off before *Add Physics* if the charm hangs freely anyway.

## CS2 charms

Valve's charm models and textures are copyrighted game assets and are not
part of this repository or the release. `tools/export_cs2_charms.py`
exports them from **your own** CS2 installation with
[Source2Viewer](https://github.com/ValveResourceFormat/ValveResourceFormat)
into a library the add-on reads: about 80 charms in 8 collections, roughly
250 MB. The tool needs Python 3.10+ and nothing else (Blender's bundled
Python works too).

```
python tools/export_cs2_charms.py --out D:/cs2_charms --download-s2v
```

What it does:

1. Reads `items_game.txt` and the localization: names, collections
   (capsules) and rarity of every keychain definition.
2. Exports each charm model as glb with materials and textures
   (Source2Viewer-CLI, `--gltf_export_format glb --gltf_export_materials`).
3. Decompiles the materials (`.vmat`) for the pattern formulas
   (`DynamicParams`), which the glb does not contain.
4. Exports the textures of community charms, which use a shared blank
   model with their own material.
5. Copies the inventory icons and writes `catalog.json`.

Options:

- CS2 is found through Steam; otherwise pass `--cs2 <path>`.
- `--download-s2v` fetches Source2Viewer-CLI; alternatively `--s2v <path>`.
- `--language german` for localized names.
- `--keep-raw` keeps the raw export in `<out>/_raw`, `--skip-export`
  rebuilds the library from it without exporting again.

Then either set *Preferences > Add-ons > cs.charm > Charm Library Folder*
to the `--out` folder, or bake everything into a personal add-on zip:

```
python tools/build_zip.py --with-charms D:/cs2_charms
-> dist/cs_charm-<version>-full.zip   (for your own use only, do not share)
```

Highlight reel charms (tournament highlights) reuse the model of their
base charm with an animated sticker slab and are skipped.

### Own charms

The library folder also reads loose models: every `.glb`/`.gltf` in the
folder or in a first-level sub-folder (folder name = collection) shows up
as a charm. A Source2Viewer glb keeps its CS2 materials (the material
data travels in the glTF extras); any other glb keeps the materials of the
glTF importer. Icons: `icons/<name>.png` or `<name>_icon.png`.

For names, rarity and pattern formulas, write a `catalog.json`:

```json
{
  "charms": [
    {
      "id": "my_charm",
      "name": "My Charm",
      "collection": "Custom",
      "rarity": "ancient",
      "model": "models/my_charm.glb",
      "icon": "icons/my_charm.png",
      "slots": { "body": "body_mat" }
    }
  ],
  "materials": {
    "body_mat": {
      "shader": "csgo_weapon.vfx",
      "textures": { "g_tColor": "textures/body_color.png" },
      "params": { "F_ENABLE_ADJUSTMENTS": 1, "g_fSaturation": 1.0 },
      "dynamic": { "g_fHueShift": "return lerp(0, 360, $KeychainSeed);" }
    }
  }
}
```

`slots` maps material slot names of the model to material keys (or inline
material objects). Paths are relative to the catalog file.

## Material setup

Each charm material is a small node tree around a reusable node group:

| Group | CS2 shader | Implementation |
|---|---|---|
| CS2 Charm Weapon | `csgo_weapon.vfx` | color with hue shift, saturation, brightness and contrast masked by the tint mask, detail texture with its own UV transform, color tint, pearlescence, ambient occlusion, metalness remap, glitter flakes, iridescence via thin film |
| CS2 Charm Liquid | `csgo_simple_liquid.vfx` | see-through tinted glass, opaque print, liquid with hue-shifted color and waterline whose surface stays level in world space (see below) |
| CS2 Charm UV | - | scale, offset and rotation for detail and glitter textures |

Texture mapping:

- `g_tColor` is the base color (sRGB), `g_tNormal` the normal map,
  `g_tAmbientOcclusion` and `g_tTintMask` are masks.
- `g_tMetalness` is channel packed: R = roughness, G = metalness,
  B = effect mask (pearlescence, glitter).
- `g_tGlitterNormal` holds the flake normals, its alpha the flake mask.
- Liquid: `g_tColorA` RGB is the glass tint, its alpha marks opaque
  parts (metal, print); `g_tLiquidMask` marks glass that holds liquid.
- Color parameters (`g_vColorTint`, `g_vLiquidColor`) are sRGB in the
  material and are converted to linear.

### Liquid level

CS2 computes the liquid surface from the direction of gravity in model
space. `g_flLiquidCenterOffset` is a reference point,
`g_vLiquidLevelUpwardsMinMidMax`, `...SidewardsMinMidMax` and
`...DownwardsMinMidMax` give the surface height above it for fill level
0, 0.5 and 1 with the charm hanging upright, lying on its side and
upside down. cs.charm converts these values (Source inches, Source Y =
Blender X) and evaluates them in the shader with world up transformed
into object space, blending between the three cases. The surface stays
level when the charm tilts, swings with physics or lies on a weapon.
Liquids without these values get a level that runs from the bottom to
the top of their bounding box.

With the charm hanging upright, the waterlines match the in-game
renders of the Butane Buddy for patterns 1 to 1990. The see-through glass
is an approximation: the game renders the container with a fake
interior, Blender shows what is really behind it.

All textures are loaded with *Channel Packed* alpha: CS2 stores data in
alpha or leaves it at 0 (normal and detail maps), and straight alpha would
turn those colors black.

### Patterns

The pattern number (0 to 100000) becomes `$KeychainSeed` = pattern /
100000. Each material's `DynamicParams` are small HLSL-like expressions on
that seed; cs.charm evaluates them with a safe parser (no `eval`) and
writes the results to the node group inputs. Examples:

- **Butane Buddy**: liquid hue `lerp(0, 320, seed)`, fill level
  `lerp(0.45, 0.8, frac(seed * 100))`.
- Other charms change hue, saturation, brightness, the detail pattern
  position, glitter or metalness with the seed.

The material keeps a copy of its parameters and formulas, so the pattern
can be changed in saved files even without the library.

The seed mapping matches in-game renders: the Butane Buddy's liquid hue
and fill level at patterns 1, 250, 500, 700, 1990, 25000, 50000, 75000
and 99999 follow these formulas exactly. Valve does not document the
shaders, so the node setups are approximations based on the shader
parameters; colors can differ from the game.

## Development

Tests run headless in Blender:

```
blender -b --factory-startup --python tests/run_tests.py
```

- Demo charms: `blender -b --factory-startup --python tools/generate_demo_charms.py`
- Release zip: `python tools/build_zip.py`, check with
  `blender --command extension validate dist/cs_charm-<version>.zip`

## License

[PolyForm Noncommercial 1.0.0](LICENSE.md), Copyright 2026 ed3n.
Free for noncommercial use. Any commercial use (selling the add-on, paid
bundles, paid services) needs a written agreement, see
[COMMERCIAL.md](COMMERCIAL.md). Contact: contact@ed3n.gallery
