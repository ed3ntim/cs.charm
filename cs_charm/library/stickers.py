# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Stickers for the Sticker Slab, read from a cs.sticker library.

Pure Python (no bpy). cs.charm reads only the ``catalog.json`` that
cs.sticker's exporter writes (tools/export_cs2_stickers.py) or that ships
with cs.sticker's core set; it never imports cs_sticker code::

    {"stickers": [{
        "id": "cs2_4609_alyx_big_hugs_holo", "name": "Big Hugs (Holo)",
        "collection": "Alyx", "finish": "HOLO",
        "textures": {"base": "textures/...png", "holomask": "...", ...},
        "params": {"Wear Bias": 0.6},
        "tags": ["alyx/big_hugs_holo", "mythical"],
        # newer catalogs (cs.sticker-dev#10), optional:
        "rarity": "mythical", "event": "Katowice 2015", "kit_id": 4609
    }]}

Older catalogs carry the rarity only as the last tag (``item_rarity`` of
the sticker kit), the event only as the collection and the sticker kit id
only in the id (``cs2_<kit id>_<material>``), so all three have
fallbacks. Texture paths are relative to the catalog file.

The kit id is the slab's serial number: the in-game label prints it with
10 digits (Titan (Holo) | Katowice 2015 = kit 343 = ``0000000343``), for
event and non-event stickers alike.
"""

import json
import os
import re
from dataclasses import dataclass, field

from . import catalog as C

CATALOG_FILE = "catalog.json"

# Finish ids as cs.sticker uses them, with display labels.
FINISHES = (
    ("PAPER", "Paper"),
    ("GLITTER", "Glitter"),
    ("HOLO", "Holo"),
    ("FOIL", "Foil"),
    ("GOLD", "Gold"),
    ("LENTICULAR", "Lenticular"),
    ("EMBROIDERED", "Embroidered"),
)
FINISH_LABELS = dict(FINISHES)
DEFAULT_FINISH = "PAPER"

# Texture roles of cs.sticker catalogs (cs_sticker/library/finishes.py).
ROLE_BASE = "base"
ROLE_NORMAL = "normal"
ROLE_HOLOMASK = "holomask"
ROLE_HOLOSPECTRUM = "holospectrum"
ROLE_GLITTER = "glitter"
ROLE_ROUGHNESS = "roughness"
ROLE_METALNESS = "metalness"
ROLE_EMISSION = "emission"
ROLE_WEARMASK = "wearmask"
ROLE_SCRATCHES = "scratches"
ROLE_FLAKES = "flakes"
ROLES = (ROLE_BASE, ROLE_NORMAL, ROLE_HOLOMASK, ROLE_HOLOSPECTRUM, ROLE_GLITTER, ROLE_ROUGHNESS,
         ROLE_METALNESS, ROLE_EMISSION, ROLE_WEARMASK, ROLE_SCRATCHES, ROLE_FLAKES)
DATA_ROLES = frozenset(ROLES) - {ROLE_BASE, ROLE_HOLOSPECTRUM}

# Sticker kits use the item rarities of the game; "immortal" is shown as
# Contraband (the Howl sticker).
RARITY_ALIASES = {"immortal": "contraband", "default": "common"}
STICKER_RARITIES = ("rare", "mythical", "legendary", "ancient", "contraband")

# Label header texts, as on the in-game slab.
LABEL_HEADER_LEFT = "COUNTER-STRIKE 2"
LABEL_HEADER_RIGHT = "MINT GRADED STICKER"
SERIAL_DIGITS = 10

_YEAR = re.compile(r"\b(19|20)\d\d\b")
_KIT_ID = re.compile(r"^cs2_(\d+)_")
_FINISH_SUFFIX = re.compile(r"\s*\(([^()]+)\)\s*$")


# CS2 wear masks: 0 outside the shape, inside > 0. Some masks (Katowice
# 2019, cs.sticker #14) have 4/255 outside. Shape = mask > floor + ~0.4 %.
MASK_SHAPE_GAIN = 128.0
MASK_FLOOR_MAX = 8.0 / 255.0


def mask_floor(red):
    """Background level of a wear mask (as in cs.sticker): median of the four
    4x4 corners of the red channel (2D numpy array), 0 above MASK_FLOOR_MAX."""
    import numpy as np
    k = 4
    corners = np.concatenate([red[:k, :k].ravel(), red[:k, -k:].ravel(),
                              red[-k:, :k].ravel(), red[-k:, -k:].ravel()])
    floor = float(np.median(corners)) if corners.size else 0.0
    return floor if 0.0 < floor <= MASK_FLOOR_MAX else 0.0


def _param(value):
    """Catalog param usable as a group input: a number or a color (3-4 numbers)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    return (isinstance(value, (list, tuple)) and len(value) in (3, 4)
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value))


def normalize_rarity(value):
    value = (value or "").strip().lower()
    return RARITY_ALIASES.get(value, value)


def rarity_color(rarity):
    """sRGB color of a rarity (white for unknown rarities, like the game's
    fallback in the slab material)."""
    rarity = normalize_rarity(rarity)
    for rid, _label, color in C.RARITIES:
        if rid == rarity:
            return color
    return (1.0, 1.0, 1.0)


def looks_like_event(collection):
    """Tournament collections carry a year ("Paris 2023", "2020 RMR");
    capsules like "Alyx" or folder names do not. The in-game name only
    has the " | Event" part for tournament stickers."""
    return bool(collection and _YEAR.search(collection))


def format_serial(number):
    return str(max(0, int(number)) % 10 ** SERIAL_DIGITS).zfill(SERIAL_DIGITS)


def kit_id_from(entry_id):
    """Sticker kit id from a cs.sticker export id ("cs2_343_..."), else 0."""
    m = _KIT_ID.match(entry_id or "")
    return int(m.group(1)) if m else 0


@dataclass
class Sticker:
    id: str
    name: str                                     # "Titan (Holo)"
    collection: str = ""
    finish: str = DEFAULT_FINISH
    rarity: str = ""
    event: str = ""                               # "Katowice 2015" or ""
    kit_id: int = 0                               # sticker kit id of the game, 0 = unknown
    textures: dict = field(default_factory=dict)  # role -> absolute path
    params: dict = field(default_factory=dict)    # finish group inputs, e.g. {"Wear Bias": 0.6}
    tags: tuple = ()
    origin: str = ""

    @property
    def finish_label(self):
        return FINISH_LABELS.get(self.finish, self.finish.title())

    @property
    def rarity_label(self):
        return C.rarity_label(self.rarity)

    @property
    def color(self):
        return rarity_color(self.rarity)

    @property
    def base_path(self):
        return self.textures.get(ROLE_BASE, "")

    def label_text(self):
        """Main line of the slab label: market name without "Sticker | "."""
        return f"{self.name} | {self.event}" if self.event else self.name

    def serial(self):
        """Serial number on the slab label: the sticker kit id, 10 digits."""
        return format_serial(self.kit_id)

    def search_text(self):
        return " ".join((self.name, self.collection, self.event, self.finish, self.finish_label,
                         self.rarity, self.rarity_label, " ".join(self.tags))).lower()

    def to_dict(self):
        """JSON-able copy, stored on slab objects so a slab keeps working
        (wear, text, rebuild) without the library."""
        return {"id": self.id, "name": self.name, "collection": self.collection,
                "finish": self.finish, "rarity": self.rarity, "event": self.event,
                "kit_id": self.kit_id, "textures": dict(self.textures), "params": dict(self.params)}

    @classmethod
    def from_dict(cls, data):
        return cls(id=str(data.get("id", "")), name=str(data.get("name", "")),
                   collection=str(data.get("collection", "")),
                   finish=str(data.get("finish") or DEFAULT_FINISH).upper(),
                   rarity=normalize_rarity(data.get("rarity")), event=str(data.get("event", "")),
                   kit_id=_int(data.get("kit_id")) or kit_id_from(str(data.get("id", ""))),
                   textures=dict(data.get("textures") or {}), params=dict(data.get("params") or {}))


def _int(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _abspath(base_dir, path):
    path = str(path).replace("\\", "/")
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(base_dir, path))


def _rarity_from_tags(tags):
    known = {r[0] for r in C.RARITIES} | set(RARITY_ALIASES)
    for tag in reversed(tags):
        if tag.lower() in known:
            return normalize_rarity(tag)
    return ""


def sticker_from_entry(entry, base_dir, origin=""):
    """Sticker from one catalog entry, or None if it is unusable."""
    if not isinstance(entry, dict):
        return None
    name = str(entry.get("name") or "").strip()
    textures_in = entry.get("textures") or {}
    if not name or not isinstance(textures_in, dict):
        return None
    collection = str(entry.get("collection") or "").strip()
    event = str(entry.get("event") or "").strip()
    # Some sources keep the full market name: "Titan (Holo) | Katowice 2015".
    if " | " in name:
        name, tail = (p.strip() for p in name.rsplit(" | ", 1))
        event = event or tail
    if not event and "event" not in entry and looks_like_event(collection):
        event = collection
    tags = tuple(str(t) for t in entry.get("tags") or () if t)
    finish = str(entry.get("finish") or "").upper()
    if finish not in FINISH_LABELS:
        m = _FINISH_SUFFIX.search(name)
        guess = m.group(1).upper() if m else ""
        finish = guess if guess in FINISH_LABELS else DEFAULT_FINISH
    textures = {str(role).lower(): _abspath(base_dir, rel)
                for role, rel in textures_in.items() if rel and str(role).lower() in ROLES}
    sticker_id = str(entry.get("id") or C.make_id(collection, name, finish))
    return Sticker(
        id=sticker_id,
        name=name,
        collection=collection or "User",
        finish=finish,
        rarity=normalize_rarity(entry.get("rarity")) or _rarity_from_tags(tags),
        event=event,
        kit_id=_int(entry.get("kit_id")) or kit_id_from(sticker_id),
        textures=textures,
        params={k: (list(v) if isinstance(v, (list, tuple)) else v)
                for k, v in (entry.get("params") or {}).items() if _param(v)},
        tags=tags,
        origin=origin,
    )


def load_catalog_file(path, report=None):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        if report is not None:
            report.warn(f"{path}: {exc}")
        return []
    entries = data.get("stickers") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        if report is not None:
            report.warn(f"{path}: no 'stickers' list")
        return []
    base_dir = os.path.dirname(os.path.abspath(path))
    out = []
    for entry in entries:
        sticker = sticker_from_entry(entry, base_dir, path)
        if sticker is not None:
            out.append(sticker)
    return out


def catalog_files(root):
    """catalog.json in ``root`` and its first-level sub-folders."""
    if not root or not os.path.isdir(root):
        return []
    found = [os.path.join(root, CATALOG_FILE)]
    try:
        found += [os.path.join(root, d, CATALOG_FILE) for d in sorted(os.listdir(root))
                  if os.path.isdir(os.path.join(root, d))]
    except OSError:
        return []
    return [p for p in found if os.path.isfile(p)]


def is_library(root):
    return bool(catalog_files(root))


class StickerLibrary:
    """All stickers of one or more library folders."""

    def __init__(self):
        self.stickers = []
        self.roots = []
        self._by_id = {}
        self.report = C.LoadReport()

    def load(self, *roots):
        self.report = C.LoadReport()
        self.roots = [r for r in roots if r]
        by_id = {}
        for root in self.roots:
            for path in catalog_files(root):
                for sticker in load_catalog_file(path, self.report):
                    by_id[sticker.id] = sticker
        self.stickers = sorted(by_id.values(), key=lambda s: (s.collection.lower(), s.name.lower()))
        self._by_id = {s.id: s for s in self.stickers}
        return self

    def __len__(self):
        return len(self.stickers)

    def get(self, sticker_id):
        return self._by_id.get(sticker_id)

    def collections(self):
        return sorted({s.collection for s in self.stickers}, key=str.lower)

    def finishes(self):
        present = {s.finish for s in self.stickers}
        return [f for f, _label in FINISHES if f in present]

    def rarities(self):
        order = C.RARITY_ORDER
        return sorted({s.rarity for s in self.stickers if s.rarity}, key=lambda r: order.get(r, 99))

    def filter(self, search="", collection="", finish="", rarity=""):
        """Stickers matching all criteria; ``search`` words must all appear
        in name, collection, event, finish, rarity or tags."""
        words = search.lower().split()
        for sticker in self.stickers:
            if collection and sticker.collection != collection:
                continue
            if finish and sticker.finish != finish:
                continue
            if rarity and sticker.rarity != rarity:
                continue
            if words:
                text = sticker.search_text()
                if not all(w in text for w in words):
                    continue
            yield sticker
