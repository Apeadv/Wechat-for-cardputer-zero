import os
import sys
import tarfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools import package                           # noqa: E402


class PackageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = package.build()

    def test_contains_runtime_and_dictionary(self):
        with tarfile.open(self.path) as tar:
            names = tar.getnames()
        joined = "\n".join(names)
        self.assertIn("wechat.py", joined)
        self.assertIn("wz/app.py", joined)
        self.assertIn("assets/ime.db", joined)
        self.assertIn("vendor/qrcodegen.py", joined)
        self.assertIn("install.sh", joined)
        self.assertNotIn("__pycache__", joined)
        self.assertNotIn("tests/", joined)

    def test_scripts_are_executable(self):
        with tarfile.open(self.path) as tar:
            modes = {m.name: m.mode for m in tar.getmembers()}
        execs = [k for k in modes if k.endswith("install.sh") or k.endswith("bin/wechat-zero")]
        self.assertTrue(execs)
        for key in execs:
            self.assertEqual(modes[key] & 0o111, 0o111, key)


if __name__ == "__main__":
    unittest.main()
