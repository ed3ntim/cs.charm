# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 ed3n
"""Run all tests inside Blender (headless):

    blender -b --factory-startup --python tests/run_tests.py

Exit code is non-zero when a test fails.
"""

import os
import sys
import unittest

import addon_utils
import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

# Enable as a legacy add-on from the repo so preferences exist.
addon_utils.enable("cs_charm", default_set=True, persistent=True)
if "cs_charm" not in bpy.context.preferences.addons:
    print("FAILED: add-on could not be enabled")
    sys.exit(1)

# The add-on ships no charms; the tests use the generated fixtures
# (set after enabling: enable() may import the package afresh).
from cs_charm import utils  # noqa: E402
FIXTURES = os.path.join(HERE, "fixtures", "library")
utils.CORE_LIBRARY_DIR = FIXTURES
utils.CORE_STICKER_DIR = os.path.join(FIXTURES, "stickers")

suite = unittest.defaultTestLoader.discover(HERE, pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
