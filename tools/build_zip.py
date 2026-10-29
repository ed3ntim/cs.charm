# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Build the installable zip: dist/cs_charm-<version>.zip

The zip holds a single top-level folder ``cs_charm/`` with source code,
manifest, LICENSE.md, COMMERCIAL.md and the core demo charms only (no tests, tools or repo
docs). That layout installs both as an extension (Blender detects the
manifest in the sub-folder) and as a legacy add-on.

    python tools/build_zip.py
    python tools/build_zip.py --with-charms D:/cs2_charms   # personal full build

``--with-charms`` bakes a library made by tools/export_cs2_charms.py
into cs_charm/charms/bundled/ -> dist/cs_charm-<version>-full.zip.
That zip contains Valve game assets: for your own use only, never publish
it (tools/publish.py refuses to).
"""

import argparse
import json
import os
import re
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "cs_charm")
DIST = os.path.join(ROOT, "dist")

EXCLUDE_DIRS = {"__pycache__", ".pytest_cache"}
EXCLUDE_EXT = {".pyc", ".pyo", ".blend1", ".orig", ".bak"}
LICENSE_FILES = ("LICENSE.md", "COMMERCIAL.md")


def version():
    with open(os.path.join(PKG, "blender_manifest.toml"), encoding="utf-8") as fh:
        m = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.M)
    if not m:
        raise SystemExit("version not found in blender_manifest.toml")
    return m.group(1)


BUNDLED_ARC = "cs_charm/charms/bundled"


def _add_bundled(zf, library):
    """Add the whole library folder (catalog.json, models, textures, icons;
    working folders starting with "_" or "." are skipped). PNG / GLB are
    stored, they are compressed already. Returns the number of files added."""
    with open(os.path.join(library, "catalog.json"), encoding="utf-8") as fh:
        catalog = json.load(fh)
    files = []
    for folder, dirs, names in os.walk(library):
        dirs[:] = sorted(d for d in dirs if not d.startswith(("_", ".")))
        files += [os.path.join(folder, n) for n in sorted(names)]
    referenced = {c.get("model", "") for c in catalog.get("charms", [])}
    missing = [m for m in referenced if m and not os.path.isfile(os.path.join(library, m))]
    if missing:
        raise SystemExit(f"{len(missing)} models listed in catalog.json are missing, e.g. {missing[0]}")
    for i, path in enumerate(files, 1):
        rel = os.path.relpath(path, library).replace(os.sep, "/")
        compress = zipfile.ZIP_DEFLATED if rel.endswith(".json") else zipfile.ZIP_STORED
        zf.write(path, f"{BUNDLED_ARC}/{rel}", compress_type=compress)
        if i % 500 == 0:
            print(f"  {i}/{len(files)} charm files")
    print(f"  bundled {len(catalog.get('charms', []))} charms ({len(files)} files)")
    return len(files)


def main(with_charms=""):
    os.makedirs(DIST, exist_ok=True)
    suffix = "-full" if with_charms else ""
    out = os.path.join(DIST, f"cs_charm-{version()}{suffix}.zip")
    if with_charms and not os.path.isfile(os.path.join(with_charms, "catalog.json")):
        raise SystemExit(f"no catalog.json in {with_charms} (run tools/export_cs2_charms.py first)")
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as zf:
        # License files travel next to the manifest.
        for name in LICENSE_FILES:
            zf.write(os.path.join(ROOT, name), f"cs_charm/{name}")
        for folder, dirs, files in os.walk(PKG):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS
                             and os.path.join(folder, d) != os.path.join(PKG, "charms", "bundled"))
            for name in sorted(files):
                if os.path.splitext(name)[1].lower() in EXCLUDE_EXT:
                    continue
                path = os.path.join(folder, name)
                zf.write(path, os.path.relpath(path, ROOT).replace(os.sep, "/"))
                count += 1
        if with_charms:
            count += _add_bundled(zf, with_charms)
    if with_charms:
        print("NOTE: this zip contains Valve game assets. Personal use only, do not publish.")
    print(f"{out}: {count + len(LICENSE_FILES)} files, {os.path.getsize(out) / 1024:.0f} KiB")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build the installable add-on zip.")
    ap.add_argument("--with-charms", default="", metavar="LIBRARY",
                    help="bake a library from export_cs2_charms.py into a personal -full zip")
    main(ap.parse_args().with_charms)
