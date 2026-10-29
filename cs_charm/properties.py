# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Property groups.

* ``WindowManager.cs_charm``   runtime library state (list mirror, filters,
  selection). Not saved in .blend files, rebuilt from the catalog.
* ``Scene.cs_charm_place``     placement settings for new charms.
* ``Object.cs_charm``          per-charm state: pattern, placement
  (anchor, normal, scale, rotation, offset), attachment and physics. The
  update callbacks re-apply the pattern / transform immediately.
"""

import math

import bpy
from bpy.props import (
    BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
    FloatVectorProperty, IntProperty, PointerProperty, StringProperty,
)

from .library import catalog as C
from .library import patterns

# Dynamic enum items must stay referenced from Python, otherwise Blender may
# read freed strings. The registry refreshes these lists.
_collection_items = [("ALL", "All Collections", "")]
_rarity_items = [("ALL", "All Rarities", "")]


def set_collection_items(names):
    _collection_items[:] = [("ALL", "All Collections", "")] + [
        (n, n, f"Only charms from {n}") for n in names
    ]


def set_rarity_items(rarities):
    _rarity_items[:] = [("ALL", "All Rarities", "")] + [
        (r, C.rarity_label(r), f"Only {C.rarity_label(r)} charms") for r in rarities
    ]


def _collection_enum(self, context):
    return _collection_items


def _rarity_enum(self, context):
    return _rarity_items


def _on_filter_change(self, context):
    from .library import registry
    registry.on_filter_changed(self)


def _on_select(self, context):
    from .library import registry
    registry.on_selection_changed(self, context)


class CSCHARM_PG_item(bpy.types.PropertyGroup):
    """Mirror of one catalog entry, displayed by the UIList."""
    # ``name`` (built in) holds the display name.
    charm_id: StringProperty()
    collection: StringProperty()
    rarity: StringProperty()
    has_pattern: BoolProperty(description="The pattern changes how this charm looks")
    has_missing: BoolProperty(description="Model or textures are missing")


class CSCHARM_PG_state(bpy.types.PropertyGroup):
    items: CollectionProperty(type=CSCHARM_PG_item)
    index: IntProperty(name="Charm", default=0, update=_on_select)

    search: StringProperty(
        name="Search", description="Filter by name, collection, rarity, effect or tag (all words must match)",
        options={"TEXTEDIT_UPDATE"}, update=_on_filter_change,
    )
    filter_collection: EnumProperty(
        name="Collection", description="Filter by charm collection",
        items=_collection_enum, update=_on_filter_change,
    )
    filter_rarity: EnumProperty(
        name="Rarity", description="Filter by rarity",
        items=_rarity_enum, update=_on_filter_change,
    )
    show_warnings: BoolProperty(name="Show Load Warnings", default=False)
    show_preview: BoolProperty(name="Preview", default=True)


ATTACH_ITEMS = [
    ("PARENT", "Parent", "Parent the charm to the target object (keeps transform)"),
    ("CHILD_OF", "Child Of", "Follow the target through a Child Of constraint"),
    ("NONE", "None", "Leave the charm unattached"),
]

SIZE_MODE_ITEMS = [
    ("ABSOLUTE", "Absolute", "Scale factor of the model. 1.0 = real CS2 size (models are in meters, "
                             "like weapons exported with Source2Viewer)"),
    ("RELATIVE", "Relative", "Charm height as a percentage of the target's longest side. "
                             "Works for any scene scale"),
]

ALIGN_ITEMS = [
    ("HANG", "Hang", "The charm hangs straight down (world -Z), facing away from the surface"),
    ("SURFACE", "Surface", "The charm points away from the surface along its normal"),
]


class CSCHARM_PG_placement(bpy.types.PropertyGroup):
    pattern: IntProperty(
        name="Pattern", description="Pattern (template) number of new charms, 0 to 100000",
        default=0, min=0, max=patterns.PATTERN_MAX,
    )
    random_pattern: BoolProperty(
        name="Random Pattern", default=False,
        description="Give every new charm a random pattern",
    )
    size_mode: EnumProperty(name="Size Mode", items=SIZE_MODE_ITEMS, default="ABSOLUTE")
    scale: FloatProperty(
        name="Scale", description="Scale factor of the charm model (1.0 = CS2 size in meters)",
        default=1.0, min=0.0001, soft_max=100.0,
    )
    size_relative: FloatProperty(
        name="Size", description="Charm height as a percentage of the target's longest side. "
                                 "About 7 % matches a charm on a CS2 rifle",
        default=7.0, min=0.01, soft_max=50.0, max=200.0, subtype="PERCENTAGE",
    )
    align: EnumProperty(name="Align", items=ALIGN_ITEMS, default="HANG")
    rotation: FloatProperty(
        name="Rotation", description="Rotation around the hanging axis",
        default=0.0, min=-2 * math.pi, max=2 * math.pi, subtype="ANGLE",
    )
    offset: FloatProperty(
        name="Offset", description="Distance of the attachment point from the surface, "
                                   "as a percentage of the charm height",
        default=0.0, soft_min=-50.0, soft_max=100.0, subtype="PERCENTAGE",
    )
    attach: EnumProperty(name="Attach", items=ATTACH_ITEMS, default="PARENT")
    physics: BoolProperty(
        name="Physics", default=False,
        description="Let the charm swing from its attachment point (rigid body pendulum). "
                    "Play the timeline to simulate",
    )


def _on_pattern(self, context):
    from .ops import spawn
    spawn.on_pattern_changed(self.id_data)


def _on_transform(self, context):
    from .ops import placement
    placement.on_transform_changed(self.id_data)


class CSCHARM_PG_charm(bpy.types.PropertyGroup):
    """State of one spawned charm (Object.cs_charm)."""
    charm_id: StringProperty(name="Charm")
    pattern: IntProperty(
        name="Pattern", description="Pattern (template) number, 0 to 100000. "
                                    "Changes color, fill level, pattern placement ... where the charm supports it",
        default=0, min=0, max=patterns.PATTERN_MAX, update=_on_pattern,
    )
    base_height: FloatProperty(name="Model Height", default=0.05, options={"HIDDEN"})

    # Placement (re-evaluated by placement.update_transform)
    placed: BoolProperty(default=False, options={"HIDDEN"})
    anchor: FloatVectorProperty(
        name="Anchor", description="Attachment point (target space when attached, else world)",
        size=3, subtype="TRANSLATION", options={"HIDDEN"},
    )
    normal: FloatVectorProperty(
        name="Normal", description="Surface normal at the attachment point (target space when attached)",
        size=3, default=(0.0, 0.0, 1.0), options={"HIDDEN"},
    )
    scale: FloatProperty(
        name="Scale", description="Scale factor of the charm model",
        default=1.0, min=0.0001, soft_max=100.0, update=_on_transform,
    )
    rotation: FloatProperty(
        name="Rotation", description="Rotation around the hanging axis",
        default=0.0, subtype="ANGLE", update=_on_transform,
    )
    tilt: FloatProperty(
        name="Tilt", description="Swing angle (sideways)",
        default=0.0, min=-math.pi, max=math.pi, subtype="ANGLE", update=_on_transform,
    )
    lean: FloatProperty(
        name="Lean", description="Swing angle (toward / away from the surface)",
        default=0.0, min=-math.pi, max=math.pi, subtype="ANGLE", update=_on_transform,
    )
    offset: FloatProperty(
        name="Offset", description="Distance of the attachment point from the surface, "
                                   "as a percentage of the charm height",
        default=0.0, soft_min=-50.0, soft_max=100.0, subtype="PERCENTAGE", update=_on_transform,
    )
    align: EnumProperty(name="Align", items=ALIGN_ITEMS, default="HANG", update=_on_transform)

    # Attachment / physics
    target: PointerProperty(name="Target", type=bpy.types.Object)
    attach: EnumProperty(name="Attach", items=ATTACH_ITEMS, default="NONE")
    physics: BoolProperty(name="Physics", default=False, options={"HIDDEN"})
    physics_anchor: PointerProperty(type=bpy.types.Object)
    physics_pivot: PointerProperty(type=bpy.types.Object)


classes = (CSCHARM_PG_item, CSCHARM_PG_state, CSCHARM_PG_placement, CSCHARM_PG_charm)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.cs_charm = PointerProperty(type=CSCHARM_PG_state)
    bpy.types.Scene.cs_charm_place = PointerProperty(type=CSCHARM_PG_placement)
    bpy.types.Object.cs_charm = PointerProperty(type=CSCHARM_PG_charm)


def unregister():
    del bpy.types.Object.cs_charm
    del bpy.types.Scene.cs_charm_place
    del bpy.types.WindowManager.cs_charm
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
