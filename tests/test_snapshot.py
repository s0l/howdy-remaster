import importlib
import os
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HOWDY_SRC = os.path.join(ROOT, "howdy", "src")
if HOWDY_SRC not in sys.path:
    sys.path.insert(0, HOWDY_SRC)


class SnapshotSecurityTest(unittest.TestCase):
    def test_generate_writes_private_snapshot_and_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths_factory = types.ModuleType("paths_factory")
            snapshots_dir = os.path.join(tmpdir, "snapshots")
            paths_factory.snapshots_dir_path = lambda: snapshots_dir
            paths_factory.snapshot_path = lambda name: os.path.join(snapshots_dir, name)
            paths_factory.logo_path = lambda: os.path.join(tmpdir, "missing-logo.png")
            sys.modules["paths_factory"] = paths_factory
            sys.modules.pop("snapshot", None)
            snapshot = importlib.import_module("snapshot")

            frame = np.zeros((2, 2, 3), dtype=np.uint8)
            with mock.patch.object(snapshot.cv2, "imwrite", side_effect=lambda path, image: open(path, "wb").close()):
                path = snapshot.generate([frame], ["SUCCESS LOGIN"])

            self.assertIsNotNone(path)
            self.assertEqual(stat.S_IMODE(os.stat(snapshots_dir).st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
