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

    def test_postinst_does_not_recursive_chown_runtime_state(self):
        self.assertNotRegex(self.script, re.compile(r"chown\s+-R[^\n]*(/etc/howdy|/var/cache/howdy|/var/log/howdy)"))

    def test_postinst_keeps_sensitive_runtime_directories_private(self):
        self.assertIn("chmod 700 /etc/howdy/models /var/cache/howdy", self.script)
        self.assertIn("chmod 700 /var/log/howdy /var/log/howdy/snapshots", self.script)

    def test_package_tree_keeps_sensitive_runtime_directories_private(self):
        self.assertIn('"$root_dir/etc/howdy/models"', self.script)
        self.assertIn('"$root_dir/var/cache/howdy"', self.script)
        self.assertIn('"$root_dir/var/log/howdy/snapshots"', self.script)


if __name__ == "__main__":
    unittest.main()
