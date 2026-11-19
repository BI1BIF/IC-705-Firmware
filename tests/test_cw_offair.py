import json
from pathlib import Path
import tempfile
import unittest

from tools.probe_705_cw_offair import measure, read_windows
from tools.probe_705_cw_continuous import assess


class OffAirScoringTest(unittest.TestCase):
    def test_continuous_counts_noise_separately_and_does_not_skip_wrong_initial(self):
        report = assess([(60, "~"), (100, "X"), (190, "C"), (300, "Y"), (470, "J"), (525, "J")],
                        [[0, 100, "", None], [100, 300, "C", 130], [300, 450, None, None],
                         [450, 500, "J", 480], [500, 600, "J", 510]])
        noise, wrong, unknown, early, correct = report["segments"]
        self.assertEqual((report["background_symbols"], report["unlabelled_symbols"], report["edit_errors"]),
                         (1, 1, 1))
        self.assertEqual(wrong["first_scored_output"], (100, "X"))
        self.assertIsNone(wrong["correct_initial_delay_ms"])
        self.assertIsNone(early["correct_initial_delay_ms"])
        self.assertEqual(correct["correct_initial_delay_ms"], 15)

    def test_score_does_not_fold_noise_into_transcript(self):
        report = measure([(0, "E"), (90, "TT"), (100, "C Q"), (200, "T")],
                         [[0, 100, ""], [100, 200, "CQ"], [200, 300, "X"]])
        self.assertEqual((report["reference_chars"], report["edit_errors"], report["extra_chars_in_controls"]),
                         (3, 1, 3))
        self.assertEqual((report["matched_boundaries"], report["extra_spaces"], report["missing_spaces"]),
                         (1, 1, 0))

    def test_measures_spacing_only_across_two_adjacent_matched_characters(self):
        report = measure([(25, "   A B"), (50, " CD, E"), (85, "Q F GH   ")],
                         [[0, 100, "AB CD EF GH"]])
        self.assertEqual((report["edit_errors"], report["matched_boundaries"], report["extra_spaces"],
                          report["missing_spaces"]), (1, 6, 1, 0))
        report = measure([(25, "CQDE A B")], [[0, 100, "CQ DE AB"]])
        self.assertEqual((report["edit_errors"], report["matched_boundaries"], report["extra_spaces"],
                          report["missing_spaces"]), (0, 5, 1, 1))

    def test_overlapping_windows_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "windows.json"
            path.write_text(json.dumps([[0, 121, ""], [120, 220, "CQ"]]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "overlapping"):
                read_windows(path, 300)
