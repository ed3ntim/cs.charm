# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""UILists for the charm library and the Sticker Slab sticker picker."""

import bpy

from ..library import catalog as C
from ..library import registry, sticker_registry
from ..library import stickers as ST

# Rarity -> built-in color-tag icon (closest match to the CS2 rarity colors).
RARITY_ICONS = {
    "common": "STRIP_COLOR_09",
    "uncommon": "STRIP_COLOR_05",
    "rare": "STRIP_COLOR_05",
    "mythical": "STRIP_COLOR_06",
    "legendary": "STRIP_COLOR_07",
    "ancient": "STRIP_COLOR_01",
    "contraband": "STRIP_COLOR_02",
}


class CSCHARM_UL_library(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        charm = registry.get_catalog().get(item.charm_id)
        icon_id = registry.preview_icon(charm) if charm else 0
        row = layout.row(align=True)
        if icon_id:
            row.label(text=item.name, icon_value=icon_id)
        else:
            row.label(text=item.name, icon="ERROR" if item.has_missing else "LINKED")
        sub = row.row(align=True)
        sub.alignment = "RIGHT"
        if item.has_pattern:
            sub.label(text="", icon="SHADING_TEXTURE")
        if item.has_missing:
            sub.label(text="", icon="ERROR")
        sub.label(text="", icon=RARITY_ICONS.get(item.rarity, "BLANK1"))

    def filter_items(self, context, data, propname):
        # Filtering happens in registry.sync_items; keep the given order.
        return [], []


class CSCHARM_UL_stickers(bpy.types.UIList):
    """Stickers for the Sticker Slab. Icons come from the sticker textures,
    loaded lazily for the visible rows only."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        sticker = sticker_registry.get_sticker(item.sticker_id)
        icon_id = sticker_registry.preview_icon(sticker) if sticker else 0
        row = layout.row(align=True)
        text = f"{item.name}  ({item.collection})" if item.collection else item.name
        if icon_id:
            row.label(text=text, icon_value=icon_id)
        else:
            row.label(text=text, icon="IMAGE_RGB_ALPHA")
        sub = row.row(align=True)
        sub.alignment = "RIGHT"
        sub.label(text=ST.FINISH_LABELS.get(item.finish, item.finish.title()))
        sub.label(text="", icon=RARITY_ICONS.get(item.rarity, "BLANK1"))

    def filter_items(self, context, data, propname):
        return [], []


def rarity_text(rarity):
    return C.rarity_label(rarity)


classes = (CSCHARM_UL_library, CSCHARM_UL_stickers)
