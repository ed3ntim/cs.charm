# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Charm catalog: loading libraries and searching them. Pure Python (no bpy).

A library is a folder with a ``catalog.json`` (written by
tools/export_cs2_charms.py or tools/generate_demo_charms.py)::

    {
      "version": 1,
      "charms": [{
        "id": "cs2_81_kc_db_lighter", "def_index": 81,
        "name": "Butane Buddy", "collection": "Dr Boom Charm Collection",
        "rarity": "ancient", "model": "drboom/kc_db_lighter.glb",
        "icon": "icons/kc_db_lighter.png", "display_seed": 1,
        "slots": {"kc_db_chain": "<material key>", ...},
        "tags": ["kc_db_lighter"]
      }],
      "materials": {
        "<material key>": {"shader": "csgo_weapon.vfx",
                           "textures": {"g_tColor": "drboom/...png"},
                           "params": {"g_fHueShift": 0.0, ...},
                           "dynamic": {"g_fHueShift": "return lerp(...);"}}
      }
    }

Paths are relative to the catalog file. ``slots`` maps glTF material names
of the model to material keys; slots without an entry fall back to the
material Source2Viewer stored in the glTF extras, or to plain PBR.

Loose ``.glb`` / ``.gltf`` files in the user folder (and its first-level
sub-folders) are listed too, with the folder name as collection.
"""

import json
import os
import re
from dataclasses import dataclass, field

from . import patterns

CATALOG_FILE = "catalog.json"
MODEL_EXTENSIONS = (".glb", ".gltf")
DEFAULT_COLLECTION = "User"

SOURCE_CORE = "CORE"
SOURCE_BUNDLED = "BUNDLED"  # full library baked into a personal build
SOURCE_USER = "USER"

SHADER_WEAPON = "csgo_weapon.vfx"
SHADER_LIQUID = "csgo_simple_liquid.vfx"

# (id, label, color) in CS2 order; colors as in the game's rarity bars.
RARITIES = (
    ("common", "Base Grade", (0.69, 0.76, 0.85)),
    ("uncommon", "Medium Grade", (0.37, 0.60, 0.85)),
    ("rare", "High Grade", (0.29, 0.41, 1.00)),
    ("mythical", "Remarkable", (0.53, 0.28, 1.00)),
    ("legendary", "Exotic", (0.83, 0.18, 0.90)),
    ("ancient", "Extraordinary", (0.92, 0.29, 0.29)),
    ("contraband", "Contraband", (0.89, 0.68, 0.22)),
)
RARITY_LABELS = {r[0]: r[1] for r in RARITIES}
RARITY_ORDER = {r[0]: i for i, r in enumerate(RARITIES)}


def rarity_label(rarity):
    return RARITY_LABELS.get(rarity, rarity.title() if rarity else "Unknown")


def make_id(*parts):
    """Stable, filesystem-safe id from arbitrary strings."""
    text = "_".join(str(p) for p in parts if p not in ("", None))
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "charm"


def pretty_name(stem):
    """'kc_db_lighter' -> 'Kc Db Lighter', 'lil_whiskers' -> 'Lil Whiskers'."""
    words = [w for w in re.split(r"[_\-\s]+", stem) if w]
    return " ".join(w[:1].upper() + w[1:] for w in words) or stem


@dataclass
class MaterialSpec:
    """One CS2 material: shader, compiled textures (absolute paths), static
    parameters and the DynamicParams expressions."""
    key: str
    shader: str = ""
    textures: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    dynamic: dict = field(default_factory=dict)

    @property
    def is_liquid(self):
        return self.shader == SHADER_LIQUID

    def flag(self, name):
        try:
            return bool(int(self.params.get(name, 0)))
        except (TypeError, ValueError):
            return False

    def seed_params(self):
        return patterns.seed_params(self.dynamic)

    def missing_files(self):
        return [slot for slot, path in self.textures.items() if not os.path.isfile(path)]

    @classmethod
    def from_dict(cls, key, data, base_dir=""):
        textures = {slot: _abspath(base_dir, p) for slot, p in (data.get("textures") or {}).items() if p}
        return cls(key=key, shader=data.get("shader", ""), textures=textures,
                   params=dict(data.get("params") or {}), dynamic=dict(data.get("dynamic") or {}))


@dataclass
class Charm:
    id: str
    name: str
    collection: str
    rarity: str = ""
    model: str = ""                                  # absolute path to .glb/.gltf
    icon: str = ""                                   # absolute path to a preview PNG
    slots: dict = field(default_factory=dict)        # glTF material name -> MaterialSpec
    def_index: int = 0
    display_seed: int = 0
    source: str = SOURCE_USER
    origin: str = ""                                 # file the entry came from
    tags: tuple = ()

    @property
    def rarity_label(self):
        return rarity_label(self.rarity)

    def materials(self):
        """Distinct material specs in slot order."""
        seen, out = set(), []
        for spec in self.slots.values():
            if spec.key not in seen:
                seen.add(spec.key)
                out.append(spec)
        return out

    def has_pattern(self):
        return any(spec.seed_params() for spec in self.slots.values())

    def effects(self):
        """Short labels of the special effects, for the UI and search."""
        labels = []
        for spec in self.materials():
            seed = set(spec.seed_params())
            if spec.is_liquid:
                labels.append("Liquid")
            if seed & {"g_fHueShift", "g_fSaturation", "g_fBrightness", "g_fContrast",
                       "g_flLiquidColorHueShift"}:
                labels.append("Pattern Color")
            if seed & {"g_flLiquidLevelHeight"}:
                labels.append("Pattern Fill Level")
            if seed & {"g_vDetailTexCoordOffset", "g_vDetailTexCoordScale", "g_flDetailTexCoordRotation"}:
                labels.append("Pattern Placement")
            if spec.flag("F_GLITTER") and float(spec.params.get("g_fGlitterIntensity", 0) or 0) > 0:
                labels.append("Glitter")
            if seed & {"g_fGlitterRainbowBalance", "g_fGlitterScale", "g_fGlitterIntensity"}:
                labels.append("Pattern Glitter")
            if seed & {"g_vMetalnessRemapRange"}:
                labels.append("Pattern Metal")
            if seed & {"g_flPearlescentScale"} or float(spec.params.get("g_flPearlescentScale", 0) or 0) > 0:
                labels.append("Pearlescent")
            if spec.flag("F_IRIDESCENCE") and (float(spec.params.get("g_flIridescentStrength", 0) or 0) > 0
                                               or "g_flIridescentStrength" in seed):
                labels.append("Iridescent")
        return list(dict.fromkeys(labels))

    def missing_files(self):
        missing = [] if self.model and os.path.isfile(self.model) else ["model"]
        for spec in self.materials():
            missing += [f"{spec.key}:{slot}" for slot in spec.missing_files()]
        return missing

    def search_text(self):
        return " ".join((self.name, self.collection, self.rarity, self.rarity_label,
                         " ".join(self.effects()), " ".join(self.tags))).lower()


@dataclass
class LoadReport:
    """Collects problems while loading so the UI can show them."""
    warnings: list = field(default_factory=list)

    def warn(self, msg):
        self.warnings.append(msg)


def _abspath(base_dir, path):
    if not path:
        return ""
    path = path.replace("\\", "/")
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(base_dir, path))


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_catalog_file(path, source, report):
    """Charms from one catalog.json."""
    base_dir = os.path.dirname(os.path.abspath(path))
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        report.warn(f"{path}: {exc}")
        return []
    materials = {key: MaterialSpec.from_dict(key, spec, base_dir)
                 for key, spec in (data.get("materials") or {}).items()}
    charms = []
    for i, entry in enumerate(data.get("charms") or []):
        name = entry.get("name") or pretty_name(os.path.splitext(os.path.basename(entry.get("model", "")))[0])
        if not entry.get("model"):
            report.warn(f"{path}: charm #{i} ({name}) has no model")
            continue
        slots = {}
        for slot, key in (entry.get("slots") or {}).items():
            if isinstance(key, dict):  # inline material
                slots[slot] = MaterialSpec.from_dict(f"{entry.get('id', name)}:{slot}", key, base_dir)
            elif key in materials:
                slots[slot] = materials[key]
            else:
                report.warn(f"{path}: {name}: unknown material {key!r}")
        try:
            def_index = int(entry.get("def_index") or 0)
            display_seed = int(entry.get("display_seed") or 0)
        except (TypeError, ValueError):
            def_index = display_seed = 0
        charms.append(Charm(
            id=entry.get("id") or make_id(source, entry.get("model")),
            name=name,
            collection=entry.get("collection") or DEFAULT_COLLECTION,
            rarity=(entry.get("rarity") or "").lower(),
            model=_abspath(base_dir, entry["model"]),
            icon=_abspath(base_dir, entry.get("icon", "")),
            slots=slots,
            def_index=def_index,
            display_seed=display_seed,
            source=source,
            origin=path,
            tags=tuple(t for t in entry.get("tags") or () if t),
        ))
    return charms


def scan_loose_models(root, source, report, known=()):
    """Charms for .glb/.gltf files that no catalog lists. Looks in ``root``
    and its first-level sub-folders (folder name = collection)."""
    known = {os.path.normcase(os.path.abspath(p)) for p in known}
    charms = []
    folders = [(root, DEFAULT_COLLECTION)]
    try:
        entries = sorted(os.listdir(root))
    except OSError as exc:
        report.warn(f"{root}: {exc}")
        return charms
    folders += [(os.path.join(root, d), d) for d in entries
                if os.path.isdir(os.path.join(root, d)) and not d.startswith((".", "_"))]
    for folder, collection in folders:
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in names:
            stem, ext = os.path.splitext(name)
            path = os.path.join(folder, name)
            if ext.lower() not in MODEL_EXTENSIONS or stem.endswith("_physics"):
                continue
            if os.path.normcase(os.path.abspath(path)) in known:
                continue
            charms.append(Charm(
                id=make_id(source, os.path.relpath(path, root)),
                name=pretty_name(stem),
                collection=collection,
                model=path,
                icon=_find_icon(folder, stem),
                source=source,
                origin=path,
                tags=(stem,),
            ))
    return charms


def _find_icon(folder, stem):
    for candidate in (stem + ".png", stem + "_png.png", stem + "_icon.png"):
        path = os.path.join(folder, "icons", candidate)
        if os.path.isfile(path):
            return path
        path = os.path.join(folder, candidate)
        if os.path.isfile(path) and candidate != stem + ".png":
            return path
    return ""


def load_library(root, source, report):
    """All charms of one library folder: catalog.json files in the root and
    first-level sub-folders, then loose models nobody listed."""
    charms = []
    catalogs = [os.path.join(root, CATALOG_FILE)]
    try:
        catalogs += [os.path.join(root, d, CATALOG_FILE) for d in sorted(os.listdir(root))
                     if os.path.isdir(os.path.join(root, d))]
    except OSError as exc:
        report.warn(f"{root}: {exc}")
        return charms
    for path in catalogs:
        if os.path.isfile(path):
            charms += load_catalog_file(path, source, report)
    if source == SOURCE_USER:
        charms += scan_loose_models(root, source, report, known=[c.model for c in charms])
    return charms


class Catalog:
    """All known charms (core demo set + bundled + user library)."""

    def __init__(self):
        self.charms = []
        self._by_id = {}
        self.report = LoadReport()

    def load(self, core_dir="", user_dir="", bundled_dir=""):
        self.report = LoadReport()
        charms = []
        for root, source in ((core_dir, SOURCE_CORE), (bundled_dir, SOURCE_BUNDLED), (user_dir, SOURCE_USER)):
            if root and os.path.isdir(root):
                charms += load_library(root, source, self.report)
        # Later sources win on id clashes (a user export replaces a bundled entry).
        by_id = {}
        for charm in charms:
            by_id[charm.id] = charm
        self.charms = sorted(by_id.values(), key=lambda c: (c.collection.lower(), RARITY_ORDER.get(c.rarity, 99),
                                                             c.name.lower()))
        self._by_id = {c.id: c for c in self.charms}
        return self

    def get(self, charm_id):
        return self._by_id.get(charm_id)

    def collections(self):
        return sorted({c.collection for c in self.charms}, key=str.lower)

    def rarities(self):
        return sorted({c.rarity for c in self.charms if c.rarity}, key=lambda r: RARITY_ORDER.get(r, 99))

    def filter(self, search="", collection="", rarity=""):
        """Charms matching all given criteria. ``search`` is split into words
        that must all appear in name, collection, rarity, effects or tags."""
        words = search.lower().split()
        for charm in self.charms:
            if collection and charm.collection != collection:
                continue
            if rarity and charm.rarity != rarity:
                continue
            if words:
                text = charm.search_text()
                if not all(w in text for w in words):
                    continue
            yield charm
