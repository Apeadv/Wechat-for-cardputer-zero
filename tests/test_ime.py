import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from wz import ime                                  # noqa: E402

DB = os.path.join(ROOT, "assets", "ime.db")


class SyllableTest(unittest.TestCase):
    def test_split(self):
        self.assertEqual(ime.split_pinyin("jintiantianqi"),
                         ["jin", "tian", "tian", "qi"])
        self.assertIsNone(ime.split_pinyin("zzzz"))

    def test_detection(self):
        self.assertTrue(ime.looks_like_pinyin("jintiantianqi"))
        self.assertFalse(ime.looks_like_pinyin("hello"))
        self.assertTrue(ime.is_single_syllable("wo"))
        self.assertFalse(ime.is_single_syllable("woaini"))


@unittest.skipUnless(os.path.exists(DB), "ime.db not present")
class LocalIMETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ime = ime.LocalIME(DB)

    def test_sentence(self):
        cands = self.ime.candidates("jintiantianqi", 9)
        self.assertTrue(cands)
        self.assertEqual(cands[0], "今天天气")

    def test_common_words(self):
        self.assertIn("明天", self.ime.candidates("mingtian", 9))
        self.assertEqual(self.ime.candidates("nihao", 9)[0], "你好")
        self.assertEqual(self.ime.candidates("zaijian", 9)[0], "再见")

    def test_partial_key_uses_fallback(self):
        self.assertTrue(self.ime.candidates("woaini", 9))

    def test_unknown_pinyin(self):
        self.assertEqual(self.ime.candidates("qqqqq", 9), [])


if __name__ == "__main__":
    unittest.main()
