# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Read the JSON part of .glb / .gltf files (no geometry), pure Python.

Source2Viewer writes the original CS2 material into each glTF material's
``extras.vmat`` (shader name, Int/Float/Vector/TextureParams). That is
enough to rebuild the material for models exported without
tools/export_cs2_charms.py.
"""

import json
import os
import struct

GLB_MAGIC = 0x46546C67  # b"glTF"
CHUNK_JSON = 0x4E4F534A


def read_json(path):
    """glTF JSON of a .glb or .gltf file. Raises ValueError for bad files."""
    with open(path, "rb") as fh:
        head = fh.read(12)
        if len(head) == 12 and struct.unpack("<I", head[:4])[0] == GLB_MAGIC:
            length, kind = struct.unpack("<II", fh.read(8))
            if kind != CHUNK_JSON:
                raise ValueError(f"{path}: first GLB chunk is not JSON")
            return json.loads(fh.read(length).decode("utf-8"))
        fh.seek(0)
        try:
            return json.loads(fh.read().decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{path}: not a glTF file ({exc})") from None


def material_extras(data):
    """[(material name, vmat dict or None)] in glTF material order."""
    out = []
    for i, mat in enumerate(data.get("materials", [])):
        extras = mat.get("extras") or {}
        vmat = extras.get("vmat") if isinstance(extras, dict) else None
        out.append((mat.get("name") or f"material_{i}", vmat if isinstance(vmat, dict) else None))
    return out


def texture_file(vtex_name, model_dir):
    """PNG Source2Viewer wrote next to the model for a compiled texture
    ("kc_db_chain_ao_png_3d94d397.vtex" -> "<dir>/kc_db_chain_ao_png_3d94d397.png")."""
    base = os.path.basename(vtex_name.replace("\\", "/"))
    stem = base[:-5] if base.lower().endswith(".vtex") else os.path.splitext(base)[0]
    path = os.path.join(model_dir, stem + ".png")
    return path if os.path.isfile(path) else ""


def spec_from_vmat_extras(vmat, model_dir):
    """Material spec (see catalog.MaterialSpec) from glTF ``extras.vmat``.
    Texture paths are absolute; unresolved textures are left out."""
    params = {}
    for key in ("IntParams", "FloatParams", "VectorParams"):
        for name, value in (vmat.get(key) or {}).items():
            params[name] = list(value) if isinstance(value, (list, tuple)) else value
    textures = {}
    for slot, vtex in (vmat.get("TextureParams") or {}).items():
        path = texture_file(vtex, model_dir)
        if path:
            textures[slot] = path
    return {
        "vmat": vmat.get("Name", ""),
        "shader": vmat.get("ShaderName", ""),
        "textures": textures,
        "params": params,
        "dynamic": {},
    }
