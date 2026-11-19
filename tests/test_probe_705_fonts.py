import struct
import unittest
from pathlib import Path

from tools.decode_705_main import decode_main
from tools.probe_705_fonts import glyph4, probe
from tools.probe_705_menu_text import inspect


class FontProbeTests(unittest.TestCase):
    def test_cmap_delta_and_indexed_segments(self):
        # Three synthetic segments: A, BC, and the mandatory 0xFFFF sentinel.
        cmap = struct.pack(">22H", 4, 44, 0, 6, 4, 1, 2,
                           65, 67, 0xFFFF, 0, 65, 66, 0xFFFF,
                           0xFFC2, 3, 1, 0, 4, 0, 9, 0)
        self.assertEqual([glyph4(cmap, n) for n in (64, 65, 66, 67, 68)], [0, 3, 12, 0, 0])

    def test_cmap_rejects_a_range_pointing_out_of_bounds(self):
        cmap = struct.pack(">16H", 4, 32, 0, 4, 4, 1, 0,
                           65, 0xFFFF, 0, 65, 0xFFFF, 0, 1, 8, 0)
        with self.assertRaisesRegex(ValueError, "exceeds bounds"):
            glyph4(cmap, 65)

    def test_stock_display_language_label_when_firmware_is_available(self):
        paths = [Path(__file__).resolve().parents[1] / "firmware" / f"705J{v}.dat" for v in (132, 140)]
        if not any(path.is_file() for path in paths):
            self.skipTest("local official firmware samples are not distributed with this project")
        for path in paths:
            if not path.is_file():
                continue
            with self.subTest(sample=path.name):
                data = path.read_bytes()
                _, main, _ = decode_main(data)
                label = "\u8868\u793a\u8a00\u8a9e"
                missing = "\u9891\u8bbe\u84dd\u7b80"
                menu = inspect(main, label + missing)
                self.assertEqual(menu["stock_text"], label)
                self.assertEqual(menu["unmapped"], list(missing))
                report, _ = probe(data, menu["stock_text"] + missing)
                large, small = [font["glyphs"] for font in report["fonts"]]
                self.assertEqual((large["U+8868"]["glyph_id"], small["U+8868"]["glyph_id"]), (3136, 0))
                self.assertTrue(all(large[f"U+{ord(c):04X}"]["glyph_id"] == 0 for c in missing))
