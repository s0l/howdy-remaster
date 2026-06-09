import importlib
import os
from pathlib import PurePath
import sys
import types
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HOWDY_SRC = os.path.join(ROOT, "howdy", "src")
if HOWDY_SRC not in sys.path:
    sys.path.insert(0, HOWDY_SRC)


def load_paths_factory(models_dir="/etc/howdy/models", gtk_bin="/usr/bin/howdy-gtk"):
    paths = types.ModuleType("paths")
    paths.dlib_data_dir = PurePath("/etc/howdy/dlib-data")
    paths.face_data_dir = PurePath("/etc/howdy/face-models")
    paths.user_models_dir = PurePath(os.path.abspath(models_dir))
    paths.config_dir = PurePath("/etc/howdy")
    paths.log_path = PurePath("/var/log/howdy")
    paths.data_dir = PurePath("/usr/share/howdy")
    paths.gtk_bin_path = PurePath(gtk_bin)
    sys.modules["paths"] = paths
    sys.modules.pop("paths_factory", None)
    return importlib.import_module("paths_factory")


class PathsFactorySecurityTest(unittest.TestCase):
    def test_user_model_path_accepts_normal_usernames(self):
        paths_factory = load_paths_factory("/tmp/howdy-models")

        self.assertEqual(
            paths_factory.user_model_path("s0l"),
            os.path.join("/tmp/howdy-models", "s0l.dat"),
        )

    def test_user_model_path_rejects_path_traversal(self):
        paths_factory = load_paths_factory("/tmp/howdy-models")

        for username in ["../root", "sub/user", "sub\\user", "", ".", "..", "bad\nuser"]:
            with self.subTest(username=username):
                with self.assertRaises(ValueError):
                    paths_factory.user_model_path(username)

    def test_gtk_bin_path_uses_generated_absolute_path(self):
        paths_factory = load_paths_factory("/tmp/howdy-models", "/usr/bin/howdy-gtk")

        self.assertEqual(paths_factory.gtk_bin_path(), "/usr/bin/howdy-gtk")


if __name__ == "__main__":
    unittest.main()
