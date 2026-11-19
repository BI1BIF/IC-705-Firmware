from hashlib import md5
import struct
import unittest

from tools.probe_705_a_index import a_split, plain_fields


class AIndexProbeTests(unittest.TestCase):
    def test_split_uses_header_and_checks_trailing_digest_as_a_separate_hypothesis(self):
        header = bytearray(0x64)
        struct.pack_into("<I", header, 0x40, 48)
        tail = b"z" * 32
        raw = bytes(header) + bytes(4096) + tail + md5(tail, usedforsecurity=False).digest()
        split = a_split(raw, {"offset": 0x64, "end_exclusive": len(raw), "bytes": 4096 + 48},
                        [{"end_exclusive": 4096}])
        self.assertEqual(split["tail"]["start"], 0x1064)
        self.assertTrue(split["period_256_stops_at_split"])
        self.assertTrue(split["tail_last_16_matches_md5_of_preceding_bytes"])
        self.assertEqual(split["aligned_header_fields_matching_a_tail_at_a_period_end"], [0x40])

    def test_fixed_and_local_fields_use_holdout_values_not_training_values(self):
        edges = [(512 + i * 32, 600 + i * 32) for i in range(5)]
        data = []
        for i, (start, end) in enumerate(edges):
            sample = bytearray(2048)
            struct.pack_into("<I", sample, 0x30, start + (i == 4))
            struct.pack_into(">I", sample, end + 12, end)
            struct.pack_into(">I", sample, 0x20, start + 0x18000000)
            data.append(bytes(sample))
        hits = plain_fields(data, edges, [(0x64, 2048)] * 5, 4)
        self.assertIn({"field": "file_start", "width": 4, "endian": "little", "kind": "fixed",
                       "file_offset": 0x30, "holdouts_match": [False]}, hits)
        self.assertIn({"field": "file_end", "width": 4, "endian": "big", "kind": "after_end",
                       "delta": 12, "holdouts_match": [True]}, hits)
        self.assertIn({"field": "start_plus_constant", "width": 4, "endian": "big", "kind": "header",
                       "delta": 0x20, "constant": 0x18000000, "holdouts_match": [True]}, hits)
