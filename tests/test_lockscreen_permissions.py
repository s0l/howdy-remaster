import importlib
import os
from pathlib import PurePath
import sys
import types
import unittest
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HOWDY_SRC = os.path.join(ROOT, "howdy", "src")
if HOWDY_SRC not in sys.path:
    sys.path.insert(0, HOWDY_SRC)


def load_lockscreen_permissions(models_dir="/etc/howdy/models"):
    paths = types.ModuleType("paths")
    paths.dlib_data_dir = PurePath("/etc/howdy/dlib-data")
    paths.face_data_dir = PurePath("/etc/howdy/face-models")
    paths.user_models_dir = PurePath(os.path.abspath(models_dir))
    paths.config_dir = PurePath("/etc/howdy")
    paths.log_path = PurePath("/var/log/howdy")
    paths.data_dir = PurePath("/usr/share/howdy")
    paths.gtk_bin_path = PurePath("/usr/bin/howdy-gtk")
    sys.modules["paths"] = paths
    sys.modules.pop("paths_factory", None)
    sys.modules.pop("lockscreen_permissions", None)
    importlib.import_module("paths_factory")
    return importlib.import_module("lockscreen_permissions")


class LockscreenPermissionsTest(unittest.TestCase):
    def test_grant_uses_numeric_uid_and_minimal_acl(self):
        lockscreen_permissions = load_lockscreen_permissions("/tmp/howdy-models")

        with mock.patch.object(lockscreen_permissions.pwd, "getpwnam", return_value=types.SimpleNamespace(pw_uid=1000)):
            with mock.patch.object(lockscreen_permissions.subprocess, "run") as run:
                lockscreen_permissions.grant_lockscreen_model_access("s0l")

        self.assertEqual(
            run.call_args_list,
            [
                mock.call(["setfacl", "-m", "u:1000:--x", "/tmp/howdy-models"], check=True),
                mock.call(["setfacl", "-m", "u:1000:r--", "/tmp/howdy-models/s0l.dat"], check=True),
            ],
        )

    def test_grant_accepts_explicit_model_path(self):
        lockscreen_permissions = load_lockscreen_permissions("/tmp/howdy-models")

        with mock.patch.object(lockscreen_permissions.pwd, "getpwnam", return_value=types.SimpleNamespace(pw_uid=1001)):
            with mock.patch.object(lockscreen_permissions.subprocess, "run") as run:
                lockscreen_permissions.grant_lockscreen_model_access("alice", "/tmp/model.dat")

        self.assertEqual(
            run.call_args_list[-1],
            mock.call(["setfacl", "-m", "u:1001:r--", "/tmp/model.dat"], check=True),
        )

    def test_revoke_removes_file_acl_only_when_file_exists(self):
        lockscreen_permissions = load_lockscreen_permissions("/tmp/howdy-models")

        with mock.patch.object(lockscreen_permissions.pwd, "getpwnam", return_value=types.SimpleNamespace(pw_uid=1000)):
            with mock.patch.object(lockscreen_permissions.os.path, "exists", return_value=False):
                with mock.patch.object(lockscreen_permissions.subprocess, "run") as run:
                    lockscreen_permissions.revoke_lockscreen_model_access("s0l", "/tmp/howdy-models/s0l.dat")

        self.assertEqual(
            run.call_args_list,
            [
                mock.call(["setfacl", "-x", "u:1000", "/tmp/howdy-models"], check=False),
            ],
        )

    def test_revoke_removes_file_and_directory_acl(self):
        lockscreen_permissions = load_lockscreen_permissions("/tmp/howdy-models")

        with mock.patch.object(lockscreen_permissions.pwd, "getpwnam", return_value=types.SimpleNamespace(pw_uid=1000)):
            with mock.patch.object(lockscreen_permissions.os.path, "exists", return_value=True):
                with mock.patch.object(lockscreen_permissions.subprocess, "run") as run:
                    lockscreen_permissions.revoke_lockscreen_model_access("s0l", "/tmp/howdy-models/s0l.dat")

        self.assertEqual(
            run.call_args_list,
            [
                mock.call(["setfacl", "-x", "u:1000", "/tmp/howdy-models/s0l.dat"], check=False),
                mock.call(["setfacl", "-x", "u:1000", "/tmp/howdy-models"], check=False),
            ],
        )


if __name__ == "__main__":
    unittest.main()
