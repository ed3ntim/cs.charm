# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Add-on preferences: uninstall button, settings migration, host mode.
The real install/uninstall round trip needs an isolated user folder
(BLENDER_USER_RESOURCES, see CONTEXT.md), so here only the
location lookup and the operator are checked."""

import os
import sys
import tempfile
import types
import unittest

import bpy

from cs_charm import preferences as P
from cs_charm import utils

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class UninstallTest(unittest.TestCase):
    def test_legacy_location(self):
        # The test runner enables the add-on from the repo (legacy module).
        self.assertEqual(P.install_location(bpy.context), ("LEGACY", None, "cs_charm"))

    def test_operator_available(self):
        self.assertTrue(hasattr(bpy.ops.cs_charm, "uninstall"))
        self.assertTrue(bpy.ops.cs_charm.uninstall.poll())

    def test_extension_location(self):
        repos = bpy.context.preferences.extensions.repos
        index = next(i for i, r in enumerate(repos) if r.module == "user_default")
        old = utils.ADDON_ID
        try:
            utils.ADDON_ID = "bl_ext.user_default.cs_charm"
            self.assertEqual(P.install_location(bpy.context), ("EXTENSION", index, "cs_charm"))
            utils.ADDON_ID = "bl_ext.no_such_repo.cs_charm"
            self.assertIsNone(P.install_location(bpy.context))
        finally:
            utils.ADDON_ID = old


class MigrationTest(unittest.TestCase):
    def test_old_values_move_into_settings(self):
        prefs = bpy.context.preferences.addons[utils.ADDON_ID].preferences
        saved = {k: getattr(prefs.settings, k) for k in P.SETTINGS_KEYS}
        try:
            # as stored by 2.0 and older: values on the preferences themselves
            prefs.migrated = False
            prefs.user_path, prefs.sticker_path = "C:/lib", "C:/stk"
            prefs.label_font, prefs.include_incomplete = "C:/font.ttf", False
            self.assertTrue(P.migrate(prefs))
            s = prefs.settings
            self.assertEqual((s.user_path, s.sticker_path, s.label_font, s.include_incomplete),
                             ("C:/lib", "C:/stk", "C:/font.ttf", False))
            self.assertEqual((prefs.user_path, prefs.sticker_path, prefs.label_font), ("", "", ""))
            self.assertEqual(utils.prefs(), prefs.settings)
            prefs.settings["user_path"] = "C:/new"
            self.assertFalse(P.migrate(prefs), "only once")
            self.assertEqual(prefs.settings.user_path, "C:/new")
        finally:
            for k, v in saved.items():
                prefs.settings[k] = v


class FakeHost:
    """Minimal cs.blend host: one settings instance per module on the
    window manager, user folders in a temp dir."""

    def __init__(self, folder):
        self.folder = folder

    def add(self, module):
        bpy.types.WindowManager.fake_host_cs_charm = bpy.props.PointerProperty(type=module.SETTINGS)

    def settings(self, module_id):
        if module_id != "cs_charm":
            return None
        return getattr(bpy.context.window_manager, "fake_host_cs_charm", None)

    def user_path(self, module_id, sub="", create=True):
        path = os.path.join(self.folder, module_id, sub)
        if create:
            os.makedirs(path, exist_ok=True)
        return path


class HostModeTest(unittest.TestCase):
    """The package as sub-module of a host package (fakehost.modules), with
    the standalone add-on disabled meanwhile (same operator names)."""

    def setUp(self):
        import addon_utils
        addon_utils.disable("cs_charm", default_set=True)
        pkg = types.ModuleType("fakehost")
        pkg.__path__ = []
        mods = types.ModuleType("fakehost.modules")
        mods.__path__ = [ROOT]
        sys.modules["fakehost"], sys.modules["fakehost.modules"] = pkg, mods
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        import addon_utils
        for key in [k for k in sys.modules if k == "fakehost" or k.startswith("fakehost.")]:
            del sys.modules[key]
        if hasattr(bpy.types.WindowManager, "fake_host_cs_charm"):
            del bpy.types.WindowManager.fake_host_cs_charm
        addon_utils.enable("cs_charm", default_set=True)
        # enable() may import the package afresh: the fixtures again
        std = sys.modules["cs_charm.utils"]
        std.CORE_LIBRARY_DIR, std.CORE_STICKER_DIR = utils.CORE_LIBRARY_DIR, utils.CORE_STICKER_DIR
        self.tmp.cleanup()

    def test_register_twice_under_a_host(self):
        import importlib
        mod = importlib.import_module("fakehost.modules.cs_charm")
        hutils = importlib.import_module("fakehost.modules.cs_charm.utils")
        self.assertEqual(hutils.ADDON_ID, "fakehost.modules.cs_charm")
        for _ in range(2):
            host = FakeHost(self.tmp.name)
            mod.register(host)
            host.add(mod)
            try:
                bpy.ops.cs_charm.spawn_at_cursor.get_rna_type()
                with self.assertRaises(KeyError):  # no uninstall button under a host
                    bpy.ops.cs_charm.uninstall.get_rna_type()
                self.assertIsNone(bpy.context.preferences.addons.get(hutils.ADDON_ID))
                settings = hutils.prefs()
                self.assertEqual(settings, bpy.context.window_manager.fake_host_cs_charm)
                settings["user_path"] = self.tmp.name
                self.assertEqual(hutils.user_library_dir(), self.tmp.name)
                settings["sticker_path"] = self.tmp.name
                self.assertEqual(hutils.sticker_library_dirs(), [self.tmp.name])
                thumbs = hutils.user_path("sticker_thumbs")
                self.assertTrue(os.path.isdir(thumbs))
                self.assertTrue(thumbs.startswith(self.tmp.name))
                cache = importlib.import_module("fakehost.modules.cs_charm.library.sticker_thumbs")
                self.assertTrue(cache.cache_dir().startswith(self.tmp.name))
                self.assertTrue(callable(mod.draw_prefs))
            finally:
                del bpy.types.WindowManager.fake_host_cs_charm
                mod.unregister()
            self.assertIsNone(hutils.get_host())
            with self.assertRaises(KeyError):
                bpy.ops.cs_charm.spawn_at_cursor.get_rna_type()


if __name__ == "__main__":
    unittest.main()
