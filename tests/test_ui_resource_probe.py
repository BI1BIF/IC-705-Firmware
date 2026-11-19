import unittest

from tools.probe_ui_resources import hits, language_id_probes


class UiResourceProbeTests(unittest.TestCase):
    def test_wire_id_and_decimal_table_have_distinct_encodings(self):
        sample = bytes.fromhex("00 1A 05 01 63 FF A1 00 A2 00 A3 00 A4 00")
        result = hits(sample, language_id_probes())
        self.assertEqual(result["civ_prefix_0163"]["first_file_offsets"], [1])
        self.assertEqual(result["adjacent_decimal_2_little"]["first_file_offsets"], [6])
        self.assertNotIn("civ_prefix_0164", result)
        self.assertNotIn("adjacent_bcd_2_little", result)
