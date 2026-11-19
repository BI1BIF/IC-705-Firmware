import random
from struct import pack
import unittest

from tools.probe_705_tail_records import header_rejection, offset_tables, phase_repeats


class TailRecordProbeTests(unittest.TestCase):
    def test_exact_run_and_periodic_control(self):
        raw = bytearray(random.Random(0).randbytes(4096))
        motif = bytes(range(67))
        raw[400:467] = raw[1424:1491] = motif
        raw[399], raw[1423], raw[467], raw[1491] = 0, 1, 0, 1
        self.assertEqual(phase_repeats(bytes(raw), 256, 3072), [(144, 1024, 67)])
        self.assertEqual(phase_repeats(bytes(range(256)) * 16, 256, 3072), [])

    def test_offset_table_requires_increasing_in_range_values(self):
        marker = {"format": "<H", "window_offset": 1, "entries": 8, "most_common_step": [2, 7],
                  "landmarks_referenced": [0, 8]}
        valid = b"X" + pack("<8H", *range(0, 16, 2))
        invalid = b"X" + pack("<8H", 0, 2, 4, 6, 8, 10, 12, 99)
        self.assertIn(marker, list(offset_tables(valid, {0, 8})))
        self.assertNotIn(("<H", 1), [(r["format"], r["window_offset"]) for r in offset_tables(invalid)])

    def test_short_magic_does_not_override_size_or_reserved_fields(self):
        invalid_bmp = b"BM" + pack("<IHHII", 62, 1, 0, 54, 40) + bytes(44)
        self.assertIsNotNone(header_rejection(invalid_bmp, 0, "bmp"))
        self.assertIsNotNone(header_rejection(b"\x00\x03" + pack("<I", 1024), 0, "fnt3"))
        self.assertIsNotNone(header_rejection(b"\x36\x04\xfd\x10" + bytes(8192), 0, "psf1"))
