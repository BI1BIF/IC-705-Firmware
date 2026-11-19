import unittest

from tools.probe_705_setting_map import SETTINGS, cell_tables, packed_pairs, parse_icf


class SettingMapTests(unittest.TestCase):
    def test_icf_read_rejects_bad_lengths_and_non_contiguous_offsets(self):
        header = b"40750001\r\n#Comment=\r\n#MapRev=6\r\n"
        trailer = b"#CD=" + b"0" * 32 + b"\r\n"
        first = b"00000000020304\r\n"
        self.assertEqual(parse_icf(header + first + b"000000020105\r\n" + trailer), (6, 2, b"\3\4\5"))
        for invalid in (b"000000020205\r\n", b"000000030105\r\n", b"000000000105\r\n"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_icf(header + first + invalid + trailer)

    def test_unaligned_packed_pair_is_recovered_without_matching_distant_literals(self):
        left = SETTINGS["digital_repeater_set"].to_bytes(3, "big")
        right = SETTINGS["repeater_monitor_timer"].to_bytes(3, "big")
        data = b"\xff" + right + b"\xff" * 3 + left + b"\xff" * 80 + right
        hits = packed_pairs(data, base=0x100)
        self.assertEqual(hits["repeater_3_big"], {
            "literal_counts": [1, 2], "first_literal_file_offsets": [[0x107], [0x101, 0x15a]],
            "pair_count": 1, "first_pairs": [[0x107, 0x101]],
        })
        self.assertEqual(hits["repeater_4_big"]["pair_count"], 0)

    def test_read_choices_and_report_file_offset_within_pe_data(self):
        marker = b"#GI_Sheet_Sel_Common_DigiRpt_Cells\0"
        table = marker + b"{S(%Flex0[1])}ON\0{S(%Flex0[2])}ON (GW)\0#\0"
        hits = cell_tables(b"skip" + table, 4, 4 + len(table))
        self.assertEqual(hits["Common_DigiRpt"], [{"file_offset": 4, "choices": {1: "ON", 2: "ON (GW)"}}])
