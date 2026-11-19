import struct
import unittest
from hashlib import md5

from tools.firmware_scan import arm, compare, compare_groups, layout, scan, strings


class FirmwareScanTests(unittest.TestCase):
    def test_layout_checks_group_b_as_one_and_reports_corruption(self):
        header = bytearray(0x64)
        header[:4] = b"\x44\x00\x77\x55"
        for offset, length in zip((0x38, 0x44, 0x4C, 0x54, 0x5C), (1, 2, 3, 4, 5)):
            struct.pack_into("<I", header, offset, length)
        for offset, value in zip((0x48, 0x50, 0x58, 0x60), (20, 30, 40, 50)):
            struct.pack_into("<I", header, offset, value)
        groups = (b"a", b"bbbbb", b"cccc", b"ddddd")
        data = header + b"".join(group + md5(group, usedforsecurity=False).digest() for group in groups) + b"@u"
        result = layout(data)
        self.assertTrue(result["all_md5_match"])
        self.assertEqual(result["group_b_candidate_split"], 0x77)
        self.assertEqual([(p["name"], p["stored_size"], p["neighbor_value"]) for p in result["size_pairs"]],
                         [("B1", 2, 20), ("B2", 3, 30), ("C", 4, 40), ("D", 5, 50)])
        data[0x64] ^= 1
        self.assertEqual([g["match"] for g in layout(data)["groups"]], [False, True, True, True])
        with self.assertRaisesRegex(ValueError, "lengths"):
            layout(data[:-1])

    def test_layout_checks_japan_empty_b_record_separately(self):
        header = bytearray(0x64)
        header[:4] = b"\x44\x00\x77\x55"
        for offset in (0x38, 0x54, 0x5C):
            struct.pack_into("<I", header, offset, 1)
        group = b"x" + md5(b"x", usedforsecurity=False).digest()
        data = header + group + bytes(16) + group * 2 + b"@u"
        report = layout(data)
        self.assertIsNone(report["group_b_candidate_split"])
        self.assertEqual(report["groups"][1]["record_kind"], "empty_placeholder")
        self.assertIsNone(report["groups"][1]["match"])
        self.assertTrue(report["all_records_valid"])
        data[0x64 + len(group)] = 1
        report = layout(data)
        self.assertTrue(report["all_md5_match"])
        self.assertFalse(report["all_records_valid"])

    def test_compare_groups_recovers_identical_suffix_after_missing_b(self):
        def envelope(a, b):
            header = bytearray(0x64)
            header[:4] = b"\x44\x00\x77\x55"
            for offset, size in zip((0x38, 0x44, 0x4C, 0x54, 0x5C), (1, len(b)//2, len(b)//2, 1, 1)):
                struct.pack_into("<I", header, offset, size)
            return bytes(header) + b"".join(
                group + (md5(group, usedforsecurity=False).digest() if group else bytes(16))
                for group in (a, b, b"c", b"d")
            ) + b"@u"

        result = compare_groups(envelope(b"a", b"bb"), envelope(b"z", b""), 16)["groups"]
        self.assertEqual([g["identical"] for g in result], [False, False, True, True])
        self.assertEqual(result[0]["difference_group_relative"]["changed_blocks"][0]["first"], 0)
        self.assertNotEqual(result[2]["left"]["offset"], result[2]["right"]["offset"])

    def test_uniform_entropy_can_hide_periodicity(self):
        result = scan(bytes(range(256)) * 2, 512)
        self.assertEqual(result["file_entropy"], 8)
        self.assertEqual(result["blocks"][0]["lag_256_equal_fraction"], 1)

    def test_signature_and_partial_block(self):
        result = scan(b"\x00\x7fELF", 4)
        self.assertEqual(result["signature_candidates"]["elf"]["first_offsets"], [1])
        self.assertEqual(result["blocks"][1]["size"], 1)
        self.assertEqual(scan(b"", 4)["file_entropy"], 0)

    def test_strings_include_offset_and_encoding(self):
        data = b"\xffplain\xff" + "wide".encode("utf-16le")
        self.assertEqual(strings(data, 4, 2), {
            "ascii": [{"offset": 1, "text": "plain"}],
            "utf-16le": [{"offset": 7, "text": "wide"}],
        })

    def test_compare_adjacent_blocks_and_extra_tail(self):
        result = compare(b"abcdefghx", b"abcdefghy!", 4)
        self.assertEqual(result["identical_block_ranges"], [[0, 8]])
        self.assertEqual(result["changed_blocks"], [{"block_offset": 8, "different_bytes": 1, "first": 8, "last": 8}])
        self.assertEqual(result["unpaired_tail_bytes"], 1)

    def test_arm_branch_sign_and_literal_target(self):
        data = struct.pack("<5I", 0xEA000001, 0xEBFFFFFD, 0xE51FF00C, 0xE12FFF1E, 0)
        self.assertEqual(arm(data, 0, len(data))["first_matches"], [
            {"offset": 0, "kind": "B", "target_offset": 12},
            {"offset": 4, "kind": "BL", "target_offset": 0},
            {"offset": 8, "kind": "LDR_PC_literal", "literal_offset": 4},
        ])


if __name__ == "__main__":
    unittest.main()
