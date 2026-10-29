# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Export all CS2 charms from your own game installation into a cs.charm
library (catalog.json + glTF models + textures + icons), using
Source2Viewer-CLI.

    python tools/export_cs2_charms.py --out D:/cs2_charms --download-s2v
    python tools/export_cs2_charms.py --out D:/cs2_charms --s2v C:/tools/Source2Viewer-CLI.exe

Then either point the add-on's "Charm Library Folder" at --out, or build a
personal add-on zip with everything included:

    python tools/build_zip.py --with-charms D:/cs2_charms

What it does:
1. reads ``keychain_definitions`` from scripts/items/items_game.txt (names
   from the localization, collections from the charm loot lists, rarity),
2. exports each charm model as .glb with materials (Source2Viewer writes
   the compiled textures next to the model and the CS2 material into the
   glTF extras),
3. decompiles the charm materials for their ``DynamicParams`` (the pattern
   formulas) and exports the textures of override materials (community
   charms share one blank model and swap the material),
4. exports the inventory images as previews and writes catalog.json.

Requirements: CS2 installed via Steam, Source2Viewer-CLI
(https://github.com/ValveResourceFormat/ValveResourceFormat/releases,
asset "cli-windows-x64.zip"; --download-s2v fetches it). Python 3.9+, no
other packages. A full export is ~350 MB and takes a few minutes; after a
CS2 update simply run it again.

The models and textures are Valve's copyrighted game assets: export them
for your own use only and do not redistribute them.
"""

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import types
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_DIR = os.path.join(ROOT, "cs_charm", "library")

S2V_RELEASES = "https://api.github.com/repos/ValveResourceFormat/ValveResourceFormat/releases/latest"
S2V_ASSET = "cli-windows-x64.zip"
S2V_NAMES = ("Source2Viewer-CLI.exe", "Source2Viewer-CLI")

ITEMS_GAME = "scripts/items/items_game.txt"
ICON_ROOT = "panorama/images/"
RAW_DIR = "_raw"
ICON_DIR = "icons"
BATCH = 80  # file filters per Source2Viewer call (Windows command line limit)


# ---------------------------------------------------------------------------
# Library modules (loaded without bpy / the add-on package __init__)
# ---------------------------------------------------------------------------

def _load_library():
    """Import cs_charm/library/{expr,patterns,gltf,catalog}.py as a
    stand-alone package so the shared code runs outside Blender."""
    pkg = types.ModuleType("cclib")
    pkg.__path__ = [LIB_DIR]
    sys.modules["cclib"] = pkg
    mods = {}
    for name in ("expr", "patterns", "gltf", "catalog"):
        spec = importlib.util.spec_from_file_location(f"cclib.{name}", os.path.join(LIB_DIR, f"{name}.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        mods[name] = mod
    return mods["gltf"], mods["catalog"], mods["patterns"]


G, C, PAT = _load_library()


# ---------------------------------------------------------------------------
# Locating CS2 and Source2Viewer
# ---------------------------------------------------------------------------

def _steam_roots():
    roots = []
    if sys.platform == "win32":
        try:
            import winreg
            for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        for value in ("SteamPath", "InstallPath"):
                            try:
                                roots.append(winreg.QueryValueEx(k, value)[0])
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
        roots += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    else:
        home = os.path.expanduser("~")
        roots += [os.path.join(home, ".steam", "steam"), os.path.join(home, ".local", "share", "Steam"),
                  os.path.join(home, "Library", "Application Support", "Steam")]
    return [os.path.normpath(r) for r in roots if r and os.path.isdir(r)]


def find_cs2(explicit=""):
    """Path to game/csgo (the folder holding pak01_dir.vpk)."""
    candidates = []
    if explicit:
        candidates += [explicit, os.path.join(explicit, "game", "csgo")]
    for steam in _steam_roots():
        libraries = [steam]
        vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
        if os.path.isfile(vdf):
            with open(vdf, encoding="utf-8", errors="replace") as fh:
                libraries += [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', fh.read())]
        for lib in libraries:
            candidates.append(os.path.join(lib, "steamapps", "common", "Counter-Strike Global Offensive", "game", "csgo"))
    for c in candidates:
        if os.path.isfile(os.path.join(c, "pak01_dir.vpk")):
            return os.path.normpath(c)
    raise SystemExit("CS2 not found. Pass --cs2 <...>/Counter-Strike Global Offensive")


def download_s2v(dest):
    print("downloading Source2Viewer-CLI (latest release) ...")
    req = urllib.request.Request(S2V_RELEASES, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        release = json.load(resp)
    asset = next((a for a in release.get("assets", []) if a["name"] == S2V_ASSET), None)
    if asset is None:
        raise SystemExit(f"release {release.get('tag_name')} has no {S2V_ASSET}")
    os.makedirs(dest, exist_ok=True)
    zpath = os.path.join(dest, S2V_ASSET)
    urllib.request.urlretrieve(asset["browser_download_url"], zpath)
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(dest)
    print(f"Source2Viewer-CLI {release.get('tag_name')} -> {dest}")


def find_s2v(explicit, tools_dir, download):
    candidates = [explicit] if explicit else []
    candidates += [os.path.join(tools_dir, n) for n in S2V_NAMES]
    candidates += [shutil.which(n) or "" for n in S2V_NAMES]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    if download:
        download_s2v(tools_dir)
        return find_s2v("", tools_dir, False)
    raise SystemExit("Source2Viewer-CLI not found. Pass --s2v <path> or use --download-s2v")


def run_s2v(exe, vpk, out, filters, extensions=None, decompile=True, threads=8, extra=()):
    """Run Source2Viewer-CLI over ``filters`` (paths or folder prefixes) in batches."""
    filters = sorted(set(filters))
    started, written = time.time(), 0
    for i in range(0, len(filters), BATCH):
        cmd = [exe, "-i", vpk, "-o", out, "-f", ",".join(filters[i:i + BATCH]), "--threads", str(threads)]
        if extensions:
            cmd += ["-e", extensions]
        if decompile:
            cmd.append("-d")
        cmd += list(extra)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace")
        for line in proc.stdout:
            if "Dump written" in line or "written to" in line:
                written += 1
            elif re.search(r"\berror\b|exception", line, re.I):
                print("  " + line.rstrip())
        if proc.wait() != 0:
            raise SystemExit(f"Source2Viewer-CLI failed (exit {proc.returncode})")
    print(f"  done: {written} files in {time.time() - started:.0f}s")


# ---------------------------------------------------------------------------
# KeyValues (items_game.txt, localization, decompiled .vmat)
# ---------------------------------------------------------------------------

_KV_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])|//[^\n]*|([^\s{}"]+)')


def parse_kv(text):
    """Parse KeyValues1 into nested lists of (key, value) pairs; values are
    strings or lists. Keeps duplicate keys (items_game has several
    "keychain_definitions" blocks)."""
    stack = [[]]
    key = None
    for m in _KV_TOKEN.finditer(text):
        quoted, brace, bare = m.groups()
        if brace == "{":
            block = []
            stack[-1].append((key, block))
            stack.append(block)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif quoted is not None or bare is not None:
            tok = quoted if quoted is not None else bare
            if key is None:
                key = tok
            else:
                stack[-1].append((key, tok))
                key = None
    return stack[0]


def find_blocks(pairs, name):
    for key, value in pairs:
        if isinstance(value, list):
            if key and key.lower() == name:
                yield value
            else:
                yield from find_blocks(value, name)


def _to_dict(block):
    """Nested KV list -> dict (first key wins)."""
    out = {}
    for key, value in block:
        if key is not None and key not in out:
            out[key] = _to_dict(value) if isinstance(value, list) else value
    return out


def load_tokens(path):
    """Localization tokens, lower-cased keys."""
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        data = parse_kv(fh.read())
    tokens = {}
    for block in find_blocks(data, "tokens"):
        for key, value in block:
            if isinstance(value, str) and key:
                tokens.setdefault(key.lower(), value)
    return tokens


def load_items(path):
    """(keychain definitions by def index, charm name -> loot pack)."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        data = parse_kv(fh.read())
    defs = {}
    for block in find_blocks(data, "keychain_definitions"):
        for def_index, fields in block:
            if isinstance(fields, list):
                defs[def_index] = _to_dict(fields)
    packs = {}
    pack_re = re.compile(r"^keychain_pack_(.+?)_(common|uncommon|rare|mythical|legendary|ancient)$")
    item_re = re.compile(r"^\[([^\]]+)\]keychain$")
    for block in find_blocks(data, "client_loot_lists"):
        for list_name, entries in block:
            m = pack_re.match(list_name or "")
            if not m or not isinstance(entries, list):
                continue
            for key, _value in entries:
                im = item_re.match(key or "")
                if im:
                    packs.setdefault(im.group(1), m.group(1))
    return defs, packs


def _number(text):
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        try:
            return [float(x) for x in text[1:-1].split()]
        except ValueError:
            return None
    try:
        value = float(text)
    except ValueError:
        return None
    return int(value) if value.is_integer() and "." not in text else value


def parse_vmat(path):
    """Decompiled .vmat -> spec dict with compiled texture paths (relative
    to the VPK root, ".vtex") instead of files."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        data = parse_kv(fh.read())
    layer = next(iter(find_blocks(data, "layer0")), None) or data
    spec = {"shader": "", "params": {}, "dynamic": {}, "compiled": {}}
    for key, value in layer:
        if key is None:
            continue
        if isinstance(value, list):
            low = key.lower()
            if low == "compiled textures":
                spec["compiled"] = {k: v for k, v in value if isinstance(v, str)}
            elif low == "dynamicparams":
                spec["dynamic"] = {k: v.replace("\\n", "\n") for k, v in value if isinstance(v, str)}
            continue
        if key == "shader":
            spec["shader"] = value
        elif key.startswith(("g_", "F_")):
            num = _number(value)
            if num is not None:
                spec["params"][key] = num
    return spec


# ---------------------------------------------------------------------------
# Building the library
# ---------------------------------------------------------------------------

def _vpk_to_raw(raw, vpk_path, ext):
    """raw/<vpk path without extension>.<ext>"""
    stem = vpk_path.replace("\\", "/")
    for suffix in ("_c", ".vmdl", ".vmat", ".vtex"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
    return os.path.join(raw, *stem.split("/")) + ext


def model_raw_path(raw, vmdl):
    return _vpk_to_raw(raw, vmdl, ".glb")


def icon_raw_path(raw, image_inventory):
    return os.path.join(raw, *(ICON_ROOT + image_inventory).split("/")) + "_png.png"


def describe(def_index, entry, tokens, packs):
    """(name, collection) for a keychain definition."""
    name = tokens.get(entry.get("loc_name", "").lstrip("#").lower(), "") or C.pretty_name(entry.get("name", ""))
    collection = ""
    pack = packs.get(entry.get("name", ""))
    if pack:
        collection = tokens.get(f"csgo_crate_keychain_pack_{pack}_capsule", "")
    if not collection:
        tag = (entry.get("tags") or {}).get("KeychainCapsule") or {}
        collection = tokens.get(str(tag.get("tag_text", "")).lstrip("#").lower(), "")
    if not collection:
        parts = entry.get("pedestal_display_model", "").replace("\\", "/").split("/")
        collection = C.pretty_name(parts[2]) if len(parts) > 2 else "Charms"
    return name, collection


def charm_entries(defs):
    """Keychain definitions that have a model of their own (highlight reels
    reuse their base model and are skipped)."""
    out = []
    for def_index, entry in defs.items():
        if entry.get("highlight_reel") or not entry.get("pedestal_display_model"):
            continue
        out.append((def_index, entry))
    return sorted(out, key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0)


def slot_vmats(glb_path, entry):
    """[(slot name, vmat path, extras)] for a model, with the definition's
    material override applied (every slot except the chain)."""
    data = G.read_json(glb_path)
    override = entry.get("keychain_material", "").replace("\\", "/")
    out = []
    for slot, vmat in G.material_extras(data):
        path = (vmat or {}).get("Name", "").replace("\\", "/")
        if override and "chain" not in os.path.basename(path).lower():
            path = override
            vmat = None  # extras describe the blank's material, not the override
        out.append((slot, path, vmat))
    return out


def build_library(out, raw, defs, tokens, packs, move=False):
    """Write out/catalog.json, copy models, textures and icons.
    Returns (charms, skipped, warnings)."""
    charms, materials, warnings, skipped = [], {}, [], 0
    copied = {}

    def place(src, group):
        """Copy/move one file to out/<group>/, once. Returns the relative path."""
        key = os.path.normcase(os.path.abspath(src))
        if key not in copied:
            dst = os.path.join(out, group, os.path.basename(src))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            (shutil.move if move else shutil.copy2)(src, dst)
            copied[key] = os.path.relpath(dst, out).replace(os.sep, "/")
        return copied[key]

    for def_index, entry in charm_entries(defs):
        vmdl = entry["pedestal_display_model"].replace("\\", "/")
        glb = model_raw_path(raw, vmdl)
        if not os.path.isfile(glb):
            skipped += 1
            warnings.append(f"{entry.get('name')}: model not exported ({vmdl})")
            continue
        group = vmdl.split("/")[2] if vmdl.startswith("weapons/keychains/") else "misc"
        glb_dir = os.path.dirname(glb)
        name, collection = describe(def_index, entry, tokens, packs)
        slots = {}
        for slot, vmat_path, extras in slot_vmats(glb, entry):
            key = vmat_path or f"{entry['name']}:{slot}"
            if key not in materials:
                spec = _material_spec(raw, vmat_path, extras, glb_dir)
                if spec is None:
                    warnings.append(f"{name}: no material data for slot {slot} ({vmat_path})")
                    continue
                materials[key] = spec
            slots[slot] = key
        icon = icon_raw_path(raw, entry.get("image_inventory", ""))
        charms.append({
            "id": f"cs2_{def_index}_{C.make_id(entry['name'])}",
            "def_index": int(def_index) if str(def_index).isdigit() else 0,
            "name": name,
            "collection": collection,
            "rarity": entry.get("item_rarity", ""),
            "model": glb,
            "icon": icon if os.path.isfile(icon) else "",
            "display_seed": int(entry.get("display_seed", 0) or 0),
            "slots": slots,
            "tags": [entry["name"]],
            "_group": group,
        })

    # Second pass: files are shared (chains, blanks), resolve all before moving.
    groups = {}
    for charm in charms:
        for key in charm["slots"].values():
            groups.setdefault(key, charm["_group"])
    for key, spec in materials.items():
        spec["textures"] = {slot: place(src, groups.get(key, "misc")) for slot, src in spec["textures"].items()}
    for charm in charms:
        group = charm.pop("_group")
        glb = charm["model"]
        # The glb references its textures by file name: keep them next to it.
        # Charms sharing a model: it may already be moved, its textures too.
        if os.path.normcase(os.path.abspath(glb)) not in copied:
            for uri in _image_uris(glb):
                src = os.path.join(os.path.dirname(glb), uri)
                if os.path.isfile(src):
                    place(src, group)
        charm["model"] = place(glb, group)
        if charm["icon"]:
            charm["icon"] = place(charm["icon"], ICON_DIR)

    catalog = {
        "version": 1,
        "generator": "cs.charm tools/export_cs2_charms.py",
        "note": "Valve game assets exported from a local CS2 install. Personal use only.",
        "charms": charms,
        "materials": materials,
    }
    with open(os.path.join(out, C.CATALOG_FILE), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(catalog, fh, indent=1, ensure_ascii=False)
    return charms, skipped, warnings


def _image_uris(glb):
    try:
        data = G.read_json(glb)
    except ValueError:
        return []
    return [img["uri"] for img in data.get("images", []) if img.get("uri") and "/" not in img["uri"]]


def _material_spec(raw, vmat_path, extras, glb_dir):
    """Spec with absolute texture sources: decompiled vmat (params,
    DynamicParams, compiled textures) merged over the glTF extras."""
    spec = {"shader": "", "params": {}, "dynamic": {}, "textures": {}}
    if extras:
        base = G.spec_from_vmat_extras(extras, glb_dir)
        spec.update({k: base[k] for k in ("shader", "params", "textures")})
    vmat_file = _vpk_to_raw(raw, vmat_path, ".vmat") if vmat_path else ""
    if vmat_file and os.path.isfile(vmat_file):
        parsed = parse_vmat(vmat_file)
        spec["shader"] = parsed["shader"] or spec["shader"]
        spec["params"].update(parsed["params"])
        spec["dynamic"] = parsed["dynamic"]
        for slot, vtex in parsed["compiled"].items():
            if slot in spec["textures"]:
                continue
            for candidate in (_vpk_to_raw(raw, vtex, ".png"), G.texture_file(vtex, glb_dir)):
                if candidate and os.path.isfile(candidate):
                    spec["textures"][slot] = candidate
                    break
    if not spec["shader"]:
        return None
    return spec


def needed_textures(raw, defs):
    """Compiled textures of override materials that no model export wrote."""
    out = set()
    for _idx, entry in charm_entries(defs):
        override = entry.get("keychain_material", "")
        vmat_file = _vpk_to_raw(raw, override, ".vmat") if override else ""
        if vmat_file and os.path.isfile(vmat_file):
            for vtex in parse_vmat(vmat_file)["compiled"].values():
                out.add(vtex.replace("\\", "/") + "_c")
    return out


def main():
    ap = argparse.ArgumentParser(description="Export CS2 charms into a cs.charm library.")
    ap.add_argument("--out", required=True, help="library folder to create/update")
    ap.add_argument("--cs2", default="", help="CS2 install folder (auto-detected via Steam)")
    ap.add_argument("--s2v", default="", help="path to Source2Viewer-CLI(.exe)")
    ap.add_argument("--download-s2v", action="store_true", help="download Source2Viewer-CLI if not found")
    ap.add_argument("--language", default="english", help="localization for names (default english)")
    ap.add_argument("--threads", type=int, default=max(2, (os.cpu_count() or 4) - 1))
    ap.add_argument("--keep-raw", action="store_true", help="keep the raw Source2Viewer export in <out>/_raw")
    ap.add_argument("--skip-export", action="store_true", help="reuse an existing <out>/_raw export")
    args = ap.parse_args()

    out = os.path.abspath(args.out)
    raw = os.path.join(out, RAW_DIR)
    os.makedirs(raw, exist_ok=True)
    loc_file = f"resource/csgo_{args.language}.txt"
    items_game = os.path.join(raw, *ITEMS_GAME.split("/"))
    loc_path = os.path.join(raw, *loc_file.split("/"))

    exe = vpk = None
    if not args.skip_export:
        game = find_cs2(args.cs2)
        vpk = os.path.join(game, "pak01_dir.vpk")
        exe = find_s2v(args.s2v, os.path.join(out, "_tools"), args.download_s2v)
        print(f"CS2: {game}\nSource2Viewer: {exe}")
        print("1/5 metadata")
        run_s2v(exe, vpk, raw, [ITEMS_GAME, loc_file], decompile=False, threads=1)
    if not os.path.isfile(items_game):
        raise SystemExit(f"missing {items_game}: run without --skip-export")
    defs, packs = load_items(items_game)
    tokens = load_tokens(loc_path) if os.path.isfile(loc_path) else {}
    entries = charm_entries(defs)
    print(f"{len(defs)} keychain definitions, {len(entries)} with their own model")

    if not args.skip_export:
        models = {e["pedestal_display_model"].replace("\\", "/") + "_c" for _i, e in entries}
        print(f"2/5 models ({len(models)}, glTF with materials)")
        run_s2v(exe, vpk, raw, models, extensions="vmdl_c", threads=args.threads,
                extra=("--gltf_export_format", "glb", "--gltf_export_materials"))
        vmats = set()
        for _i, entry in entries:
            glb = model_raw_path(raw, entry["pedestal_display_model"])
            if os.path.isfile(glb):
                vmats.update(p + "_c" for _s, p, _x in slot_vmats(glb, entry) if p)
        print(f"3/5 materials ({len(vmats)}, for the pattern formulas)")
        run_s2v(exe, vpk, raw, vmats, extensions="vmat_c", threads=args.threads)
        textures = needed_textures(raw, defs)
        print(f"4/5 override textures ({len(textures)})")
        if textures:
            run_s2v(exe, vpk, raw, textures, extensions="vtex_c", threads=args.threads)
        icons = {ICON_ROOT + e["image_inventory"] + "_png.vtex_c" for _i, e in entries if e.get("image_inventory")}
        print(f"5/5 inventory images ({len(icons)})")
        run_s2v(exe, vpk, raw, icons, extensions="vtex_c", threads=args.threads)

    # Rebuilt from raw every time, keeps the library in sync.
    for name in os.listdir(out):
        path = os.path.join(out, name)
        if os.path.isdir(path) and not name.startswith("_"):
            shutil.rmtree(path)
    charms, skipped, warnings = build_library(out, raw, defs, tokens, packs, move=not args.keep_raw)
    if not args.keep_raw:
        shutil.rmtree(raw, ignore_errors=True)

    for w in warnings:
        print("  warning: " + w)
    by_collection = {}
    for c in charms:
        by_collection[c["collection"]] = by_collection.get(c["collection"], 0) + 1
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(out)
               for f in fs if not d.startswith(os.path.join(out, "_")))
    print(f"\n{len(charms)} charms -> {os.path.join(out, C.CATALOG_FILE)} ({size / 2**20:.0f} MiB)")
    for name, count in sorted(by_collection.items()):
        print(f"  {name}: {count}")
    patterned = sum(1 for c in charms if c["slots"])
    if skipped:
        print(f"  skipped (no model): {skipped}")
    print(f"  with material data: {patterned}")
    print("Reminder: these are Valve's assets. Personal use only, do not redistribute.")


if __name__ == "__main__":
    main()
