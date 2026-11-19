from hashlib import md5
import random
from struct import pack_into
import unittest

from tools.probe_icom_comparators import PAGE, compare_tail, probe


class IcomComparatorTests(unittest.TestCase):
    def test_905_cut_depends_on_its_tail_field_without_assuming_a_705_digest(self):
        header = bytearray(b"\x44\x22\x00\x99" + bytes(0x84))
        front = bytes(range(256)) * 20
        tail = b"\xff" * 256
        pack_into("<III", header, 0x3C, len(front + tail), 0xC00000, len(tail))
        info, actual = probe(bytes(header) + front + tail + bytes(18))
        self.assertEqual(actual, tail)
        self.assertEqual(info["tail"]["relative_start"], len(front))
        self.assertTrue(info["period_256_stops_at_split"])
        self.assertFalse(info["first_payload"]["adjacent_md5_matches"])

    def test_9700_adjacent_records_validate_each_payload_independently(self):
        header = bytearray(b"\x33\x99\x11\x33" + bytes(0x34))
        first, second = bytes(0x800000), b"other payload"
        pack_into("<I", header, 0x1C, len(first))
        pack_into("<I", header, 0x30, len(second))
        raw = bytes(header) + first
        suffix = bytes(16) + second + md5(second, usedforsecurity=False).digest() + bytes(18)
        info, _ = probe(raw + md5(first, usedforsecurity=False).digest() + suffix)
        self.assertTrue(info["first_payload"]["adjacent_md5_matches"])
        self.assertTrue(info["second_payload"]["adjacent_md5_matches"])
        corrupt, _ = probe(raw + bytes(16) + suffix)
        self.assertFalse(corrupt["first_payload"]["adjacent_md5_matches"])
        self.assertTrue(corrupt["second_payload"]["adjacent_md5_matches"])

    def test_aligned_correlation_is_distinct_from_equality_and_shift_control(self):
        left = random.Random(0).randbytes(2 * PAGE)
        right = bytes(value ^ 1 for value in left)
        direct = compare_tail(left, right)
        self.assertEqual(direct["equal_bytes"], 0)
        self.assertEqual(direct["nonperiodic_pages_at_most_16_xor_values"], 2)
        shifted = compare_tail(left, right, PAGE)
        self.assertEqual(shifted["nonperiodic_pages"], 1)
        self.assertEqual(shifted["nonperiodic_pages_at_most_16_xor_values"], 0)
