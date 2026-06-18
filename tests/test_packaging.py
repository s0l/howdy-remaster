import os
import re
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BUILD_DEB = os.path.join(ROOT, "scripts", "build-deb.sh")


class DebianPackagingSecurityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(BUILD_DEB, encoding="utf-8") as script_file:
            cls.script = script_file.read()
        config_path = os.path.join(ROOT, "howdy", "src", "config.ini")
        with open(config_path, encoding="utf-8") as config_file:
            cls.config = config_file.read()
        meson_path = os.path.join(ROOT, "howdy", "src", "meson.build")
        with open(meson_path, encoding="utf-8") as meson_file:
            cls.meson = meson_file.read()
        pam_path = os.path.join(ROOT, "howdy", "src", "pam", "main.cc")
        with open(pam_path, encoding="utf-8") as pam_file:
            cls.pam = pam_file.read()

    def test_postinst_does_not_recursive_chown_runtime_state(self):
        self.assertNotRegex(self.script, re.compile(r"chown\s+-R[^\n]*(/etc/howdy|/var/cache/howdy|/var/log/howdy)"))

    def test_postinst_keeps_sensitive_runtime_directories_private(self):
        self.assertIn("chmod 700 /etc/howdy/models /var/cache/howdy", self.script)
        self.assertIn("chmod 700 /var/log/howdy /var/log/howdy/snapshots", self.script)

    def test_package_tree_keeps_sensitive_runtime_directories_private(self):
        self.assertIn('"$root_dir/etc/howdy/models"', self.script)
        self.assertIn('"$root_dir/var/cache/howdy"', self.script)
        self.assertIn('"$root_dir/var/log/howdy/snapshots"', self.script)

    def test_package_depends_on_acl_for_kde_lockscreen_model_access(self):
        self.assertIn("acl, curl | wget", self.script)

    def test_postinst_migrates_existing_model_acls_by_numeric_uid(self):
        self.assertIn('uid="$(id -u -- "$user" 2>/dev/null || true)"', self.script)
        self.assertIn('setfacl -m "u:$uid:--x" /etc/howdy/models || true', self.script)
        self.assertIn('setfacl -m "u:$uid:r--" "$model_file" || true', self.script)

    def test_privilege_services_require_explicit_confirmation_by_default(self):
        self.assertRegex(
            self.config,
            re.compile(r"^confirmation_services\s*=\s*polkit-1,sudo,sudo-i\s*$", re.MULTILINE),
        )

    def test_unsafe_device_paths_are_disabled_by_default(self):
        self.assertRegex(
            self.config,
            re.compile(r"^allow_unsafe_device_path\s*=\s*false\s*$", re.MULTILINE),
        )

    def test_camera_helper_is_installed_with_python_sources(self):
        self.assertRegex(
            self.meson,
            re.compile(r"py_sources\s*=\s*\[[^\]]*'camera_helper\.py'", re.DOTALL),
        )

    def test_postinst_keeps_installed_python_sources_not_writable_by_group_or_world(self):
        self.assertIn("find /lib/security/howdy /lib/security/howdy-gtk -xdev -type d -exec chmod 755 {} +", self.script)
        self.assertIn("find /lib/security/howdy /lib/security/howdy-gtk -xdev -type f -exec chmod 644 {} +", self.script)

    def test_pam_terminates_compare_process_group(self):
        self.assertIn("POSIX_SPAWN_SETPGROUP", self.pam)
        self.assertIn("posix_spawnattr_setpgroup(&spawn_attr, 0)", self.pam)
        self.assertIn("kill(-child_pid, SIGTERM)", self.pam)


if __name__ == "__main__":
    unittest.main()
