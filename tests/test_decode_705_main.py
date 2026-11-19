import unittest

from tools.decode_705_main import decode_main, lzss


class MainDecoderTests(unittest.TestCase):
    def test_literal_then_overlapping_match(self):
        self.assertEqual(lzss(b"\x01A\xee\xf2\xff", 6), (b"AAAAAA", 4))

    def test_rejects_incomplete_and_overlong_tokens(self):
        with self.assertRaisesRegex(ValueError, "truncated"):
            lzss(b"\x00\xee", 3)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            lzss(b"\x00\xee\xf1", 3)

    def test_rejects_unrecognized_envelope(self):
        with self.assertRaisesRegex(ValueError, "unrecognized"):
            decode_main(b"\x00" * 0x10000)

    def test_initial_7300_caps_last_match_but_rejects_uninitialized_history(self):
        self.assertEqual(lzss(b"\x01A\xee\xf2", 3, original_7300=True), (b"AAA", 4))
        with self.assertRaisesRegex(ValueError, "uninitialized"):
            lzss(b"\x00\xee\xf0", 3, original_7300=True)
