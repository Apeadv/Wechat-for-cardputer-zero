import json
import os
import sys
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools import build_deb, build_release       # noqa: E402


def read_ar(path):
    data = open(path, "rb").read()
    assert data.startswith(b"!<arch>\n")
    off, out = 8, {}
    while off + 60 <= len(data):
        header = data[off:off + 60]
        name = header[:16].decode().strip().rstrip("/")
        size = int(header[48:58].decode().strip())
        body = data[off + 60:off + 60 + size]
        out[name] = body
        off += 60 + size + (size % 2)
    return out


class DebTest(unittest.TestCase):
    def test_deb_structure_and_metadata(self):
        cfg = build_release.load_config()
        with tempfile.TemporaryDirectory() as tmp:
            info = build_deb.build(tmp, release=cfg)
            self.assertTrue(os.path.exists(info["path"]))
            members = read_ar(info["path"])
        self.assertEqual(members["debian-binary"], b"2.0\n")

        with tempfile.TemporaryDirectory() as tmp:
            for name in ("control.tar.gz", "data.tar.gz"):
                open(os.path.join(tmp, name), "wb").write(members[name])
            with tarfile.open(os.path.join(tmp, "control.tar.gz")) as tar:
                control = tar.extractfile("./control").read().decode()
                postinst = tar.extractfile("./postinst")
                self.assertIsNotNone(postinst)
            with tarfile.open(os.path.join(tmp, "data.tar.gz")) as tar:
                names = tar.getnames()
                modes = {m.name: m.mode for m in tar.getmembers()}
        self.assertIn("Package: wechat-zero", control)
        self.assertIn("Version: 1.1.0", control)
        self.assertIn("Architecture: all", control)
        self.assertIn("python3-pil", control)
        self.assertIn("./opt/wechat-zero/assets/ime.db", names)
        self.assertIn("./opt/wechat-zero/wechat.py", names)
        self.assertIn("./usr/share/APPLaunch/bin/wechat-zero", names)
        self.assertEqual(modes["./usr/share/APPLaunch/bin/wechat-zero"] & 0o111, 0o111)
        self.assertEqual(modes["./opt/wechat-zero/assets/ime.db"] & 0o777, 0o644)


class ReleaseBundleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.cfg = build_release.load_config()
        cls.info = build_release.build(cls.tmp.name, cls.cfg, "1.1.0")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_store_metadata(self):
        store = self.info["store"]
        meta = json.load(open(os.path.join(store, "meta.json"), encoding="utf-8"))
        self.assertEqual(meta["share_code"], self.cfg["share_code"])
        self.assertTrue(meta["permissions"]["network"])
        self.assertGreaterEqual(len(meta["screenshots"]), 1)
        self.assertEqual(meta["license"], "MIT")
        for shot in meta["screenshots"]:
            self.assertTrue(os.path.exists(os.path.join(store, shot)), shot)

    def test_release_manifest(self):
        store = self.info["store"]
        name = "wechat-zero_1.1.0_all.deb.release.json"
        data = json.load(open(os.path.join(store, name), encoding="utf-8"))
        deb = os.path.join(store, "wechat-zero_1.1.0_all.deb")
        self.assertEqual(data["sha256"], build_deb._sha256(deb))
        self.assertEqual(data["size"], os.path.getsize(deb))
        self.assertEqual(data["architecture"], "all")
        self.assertIn("/releases/download/v1.1.0/", data["url"])

    def test_source_and_github_bundle(self):
        gh = self.info["github"]
        for name in ("wechat-zero-1.1.0-source.tar.gz",
                     "wechat-zero-1.1.0-source.zip",
                     "wechat-zero_1.1.0_all.deb",
                     "SHA256SUMS", "get.sh", "RELEASE_NOTES.md"):
            self.assertTrue(os.path.exists(os.path.join(gh, name)), name)
        sums = open(os.path.join(gh, "SHA256SUMS"), encoding="utf-8").read()
        self.assertIn("wechat-zero_1.1.0_all.deb", sums)

    def test_icon_and_screenshots_are_valid(self):
        from PIL import Image
        icon = os.path.join(ROOT, "packaging", "icon-256.png")
        self.assertEqual(Image.open(icon).size, (256, 256))
        shots = os.path.join(ROOT, "packaging", "screenshots")
        files = [f for f in os.listdir(shots) if f.endswith(".png")]
        self.assertGreaterEqual(len(files), 1)
        for f in files:
            self.assertEqual(Image.open(os.path.join(shots, f)).size, (320, 170))


if __name__ == "__main__":
    unittest.main()
