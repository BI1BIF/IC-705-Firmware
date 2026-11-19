import struct
import unittest

from tools.probe_icom_cpu_record import FIRST, SPAN, STEP, signature, vector_tables


class IcomCpuRecordTests(unittest.TestCase):
    def test_periodic_record_requires_only_the_expected_bit_flips(self):
        data = bytearray(FIRST + 2 * STEP + SPAN)
        for index in range(15, SPAN, 17):
            data[FIRST + STEP + index] = 0x80
        self.assertTrue(signature(data)["matches"])
        data[FIRST + STEP] = 0x80
        self.assertFalse(signature(data)["matches"])

    def test_vector_table_resolves_reset_literal_at_unaligned_file_offset(self):
        data = struct.pack("<9I", *([0xE59FF018] * 5), 0, *([0xE59FF018] * 2), 0x1800008C)
        self.assertEqual(vector_tables(b"x" + data), [{"offset": 1, "first_literal": "0x1800008c"}])
        self.assertEqual(vector_tables(data[:28]), [])
