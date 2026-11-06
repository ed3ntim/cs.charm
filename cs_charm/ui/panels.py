# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""3D Viewport sidebar panels (tab "cs.charm"): Library, Placement, Active Charm."""

import bpy

from .. import utils
from ..library import registry, sticker_registry
from ..library import shading as S
from ..nodes import material as M
from ..nodes import slab
from ..ops.spawn import charm_of
from .lists import RARITY_ICONS

TAB = "cs.charm"

# Inputs of the main groups shown in the Active Charm panel, by shader.
# Texture inputs are left out; every other input is drawn.
_TEXTURE_INPUTS = {
    "Color", "Normal Map", "Metal Pack", "Ambient Occlusion", "Tint Mask", "Detail",
    "Glitter Normal", "Glitter Mask", "Color Alpha", "Liquid Mask", "UV", "Shader", "Refract Mask",
}

_NODE_TITLES = {S.NODE_DETAIL_UV: "Detail Pattern", S.NODE_GLITTER_UV: "Glitter Flakes", S.NODE_GLASS: "Glass"}


def _sticker_info(layout, sticker):
    col = layout.column(align=True)
    col.label(text=sticker.label_text(), icon="IMAGE_RGB_ALPHA")
    from .lists import RARITY_ICONS
    col.label(text=f"{sticker.finish_label}, {sticker.rarity_label}",
              icon=RARITY_ICONS.get(sticker.rarity, "BLANK1"))


def draw_sticker_picker(layout, context):
    """Sticker picker under the library when the Sticker Slab is selected."""
    state = context.window_manager.cs_charm
    box = layout.box()
    box.label(text="Sticker for the Slab", icon="IMAGE_RGB_ALPHA")
    if not sticker_registry.is_loaded():
        # Panels may not write to the WindowManager: loading is an operator.
        box.operator("cs_charm.refresh_stickers", text="Load Stickers", icon="IMPORT")
        return
    lib = sticker_registry.get_library()
    box.prop(state, "sticker_search", text="", icon="VIEWZOOM")
    row = box.row(align=True)
    row.prop(state, "sticker_collection", text="")
    row = box.row(align=True)
    row.prop(state, "sticker_finish", text="")
    row.prop(state, "sticker_rarity", text="")
    box.template_list("CSCHARM_UL_stickers", "", state, "sticker_items", state, "sticker_index", rows=5)
    row = box.row()
    total, shown = sticker_registry.match_count(), len(state.sticker_items)
    text = f"{total} of {len(lib)} stickers"
    if shown < total:
        text += f" (first {shown})"
    row.label(text=text)
    row.operator("cs_charm.refresh_stickers", text="", icon="FILE_REFRESH")
    sticker = sticker_registry.selected_sticker(context)
    if sticker is None:
        box.label(text="Pick a sticker for new slabs", icon="INFO")
        return
    _sticker_info(box, sticker)
    if state.show_preview:
        icon_id = sticker_registry.preview_icon(sticker)
        if icon_id:
            box.template_icon(icon_value=icon_id, scale=6.0)
    if slab.is_slab(context.active_object):
        box.operator("cs_charm.set_sticker", icon="FILE_REFRESH")


class _Panel:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = TAB


class CSCHARM_PT_library(_Panel, bpy.types.Panel):
    bl_label = "Library"
    bl_idname = "CSCHARM_PT_library"

    def draw(self, context):
        layout = self.layout
        state = context.window_manager.cs_charm
        catalog = registry.get_catalog()

        layout.prop(state, "search", text="", icon="VIEWZOOM")
        row = layout.row(align=True)
        row.prop(state, "filter_collection", text="")
        row.prop(state, "filter_rarity", text="")

        layout.template_list("CSCHARM_UL_library", "", state, "items", state, "index", rows=6)
        row = layout.row()
        total = registry.match_count()
        shown = len(state.items)
        text = f"{total} of {len(catalog.charms)} charms"
        if shown < total:
            text += f" (first {shown} shown, refine the search)"
        row.label(text=text)
        row.operator("cs_charm.refresh_library", text="", icon="FILE_REFRESH")

        charm = registry.selected_charm(context)
        if charm is not None:
            box = layout.box()
            col = box.column(align=True)
            col.label(text=charm.name, icon="LINKED")
            col.label(text=charm.collection, icon="OUTLINER_COLLECTION")
            col.label(text=charm.rarity_label, icon=RARITY_ICONS.get(charm.rarity, "BLANK1"))
            effects = charm.effects()
            if effects:
                col.label(text=", ".join(effects), icon="SHADING_TEXTURE")
            missing = charm.missing_files()
            if missing:
                col.label(text=f"Missing: {', '.join(missing[:3])}", icon="ERROR")
            row = box.row()
            row.prop(state, "show_preview", icon="TRIA_DOWN" if state.show_preview else "TRIA_RIGHT",
                     emboss=False)
            if state.show_preview:
                icon_id = registry.preview_icon(charm)
                if icon_id:
                    box.template_icon(icon_value=icon_id, scale=7.0)
                else:
                    box.label(text="No preview image", icon="IMAGE_DATA")

        if slab.is_slab_charm(charm):
            draw_sticker_picker(layout, context)

        warnings = catalog.report.warnings
        if warnings:
            row = layout.row()
            row.prop(state, "show_warnings", icon="ERROR", text=f"{len(warnings)} load warning(s)")
            if state.show_warnings:
                col = layout.column(align=True)
                for msg in warnings[:20]:
                    col.label(text=msg)
        if not utils.user_library_dir():
            layout.label(text="Set a charm folder in the add-on preferences", icon="INFO")


class CSCHARM_PT_placement(_Panel, bpy.types.Panel):
    bl_label = "Placement"
    bl_idname = "CSCHARM_PT_placement"

    def draw(self, context):
        layout = self.layout
        s = context.scene.cs_charm_place

        row = layout.row(align=True)
        sub = row.row(align=True)
        sub.enabled = not s.random_pattern
        sub.prop(s, "pattern")
        row.prop(s, "random_pattern", text="", icon="FILE_REFRESH")

        layout.prop(s, "size_mode", expand=True)
        layout.prop(s, "size_relative" if s.size_mode == "RELATIVE" else "scale")
        layout.prop(s, "align", expand=True)
        col = layout.column(align=True)
        col.prop(s, "rotation")
        col.prop(s, "offset")
        if s.align == "HANG":
            layout.prop(s, "rest_on_surface")
        layout.prop(s, "attach")
        layout.prop(s, "physics")
        layout.operator("cs_charm.reset_placement", icon="LOOP_BACK")

        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("cs_charm.place_interactive", icon="RESTRICT_SELECT_OFF")
        col = layout.column(align=True)
        col.operator("cs_charm.spawn_on_selected", icon="SNAP_FACE")
        col.operator("cs_charm.spawn_at_cursor", icon="PIVOT_CURSOR")


class CSCHARM_PT_active(_Panel, bpy.types.Panel):
    bl_label = "Active Charm"
    bl_idname = "CSCHARM_PT_active"

    @classmethod
    def poll(cls, context):
        return utils.is_charm(context.active_object)

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        state = obj.cs_charm
        charm = charm_of(obj)

        row = layout.row()
        row.label(text=charm.name if charm else obj.name, icon="LINKED")
        row.operator("cs_charm.select_in_library", text="", icon="VIEWZOOM")
        if charm is None:
            layout.label(text="Not in the current library (pattern still works)", icon="INFO")

        # Pattern
        box = layout.box()
        row = box.row(align=True)
        row.prop(state, "pattern")
        row.operator("cs_charm.randomize_pattern", text="", icon="FILE_REFRESH")
        summary = []
        for mat in obj.data.materials if obj.data else ():
            spec = M.spec_from_material(mat)
            if spec is not None:
                summary += S.pattern_summary(spec, state.pattern)
        if summary:
            col = box.column(align=True)
            for label, value in summary:
                col.label(text=f"{label}: {S.format_value(label, value)}")
        else:
            box.label(text="The pattern does not change this charm's look")

        if slab.is_slab(obj):
            self.draw_slab(layout, context, obj)

        # Transform
        box = layout.box()
        box.label(text="Placement", icon="ORIENTATION_GIMBAL")
        col = box.column(align=True)
        col.prop(state, "scale")
        col.prop(state, "rotation")
        col.prop(state, "tilt")
        col.prop(state, "lean")
        col.prop(state, "offset")
        box.row().prop(state, "align", expand=True)
        if state.align == "HANG":
            box.prop(state, "rest_on_surface")
        box.operator("cs_charm.set_anchor", icon="PIVOT_CURSOR")

        # Attachment / physics
        box = layout.box()
        if state.target is not None and state.attach != "NONE":
            mode = "Parent" if state.attach == "PARENT" else "Child Of"
            box.label(text=f"Attached to {state.target.name} ({mode})", icon="LINKED")
        else:
            box.label(text="Not attached", icon="UNLINKED")
        row = box.row(align=True)
        row.operator("cs_charm.attach", text="Parent").mode = "PARENT"
        row.operator("cs_charm.attach", text="Child Of").mode = "CHILD_OF"
        row.operator("cs_charm.detach", text="", icon="X")
        if state.physics:
            box.label(text="Physics on: play the timeline", icon="PHYSICS")
            if state.physics_collider is not None:
                box.label(text=f"Collides with {state.target.name if state.target else 'target'}",
                          icon="MOD_PHYSICS")
            box.operator("cs_charm.remove_physics", icon="CANCEL")
            if obj.rigid_body is not None:
                col = box.column(align=True)
                col.prop(obj.rigid_body, "linear_damping", text="Damping")
                col.prop(obj.rigid_body, "angular_damping", text="Swing Damping")
        else:
            box.prop(state, "physics_collide")
            box.operator("cs_charm.add_physics", icon="PHYSICS")

        layout.operator("cs_charm.delete", icon="TRASH")

    @staticmethod
    def draw_slab(layout, context, obj):
        state = obj.cs_charm
        box = layout.box()
        box.label(text="Sticker Slab", icon="IMAGE_RGB_ALPHA")
        sticker = slab.sticker_of(obj)
        if sticker is not None:
            _sticker_info(box, sticker)
            box.label(text=f"Serial (sticker kit): {sticker.serial()}")
        else:
            box.label(text="No sticker", icon="ERROR")
        row = box.row(align=True)
        row.operator("cs_charm.set_sticker", text="Use Picked Sticker", icon="FILE_REFRESH")
        row.operator("cs_charm.show_sticker", text="", icon="VIEWZOOM")
        box.prop(state, "sticker_wear", slider=True)
        box.prop(state, "label_text", text="", icon="FONT_DATA")
        if not state.label_text and sticker is not None:
            box.label(text=f"Label: {sticker.label_text()}")
        row = box.row(align=True)
        row.prop(state, "use_label_color", text="Custom Color")
        sub = row.row(align=True)
        sub.enabled = state.use_label_color
        sub.prop(state, "label_color", text="")


class CSCHARM_PT_materials(_Panel, bpy.types.Panel):
    bl_label = "Material Parameters"
    bl_idname = "CSCHARM_PT_materials"
    bl_parent_id = "CSCHARM_PT_active"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        layout.operator("cs_charm.reset_materials", icon="LOOP_BACK")
        found = False
        for mat in obj.data.materials if obj.data else ():
            nodes = M.parameter_nodes(mat)
            if not nodes:
                continue
            found = True
            box = layout.box()
            box.label(text=mat.name, icon="MATERIAL")
            for node in nodes:
                col = box.column(align=True)
                if node.name != S.NODE_MAIN:
                    col.label(text=_NODE_TITLES.get(node.name, node.name))
                for sock in node.inputs:
                    if sock.name in _TEXTURE_INPUTS or sock.is_linked or not hasattr(sock, "default_value"):
                        continue
                    col.prop(sock, "default_value", text=sock.name)
        if not found:
            layout.label(text="Plain PBR material (no CS2 parameters)", icon="INFO")


classes = (CSCHARM_PT_library, CSCHARM_PT_placement, CSCHARM_PT_active, CSCHARM_PT_materials)
