import struct
import tempfile
import unittest
import wave
from pathlib import Path

from tools.score_arrl_cw import body, edit_distance, measure


class ArrlScoreTests(unittest.TestCase):
    def test_body_keeps_errors_without_scoring_announcement_or_prosign(self):
        self.assertIsNone(body("THIS IS ONLY A FRAGMENT"))
        ref = body("TEXT IS FROM QST PAGE 44 =\nONE TWO,\n= END OF 20 WPM TEXT = <")
        obs = body("PAGE 44 = ONE T<...>O\n= END OF 20 WPM TEXT")
        self.assertEqual(ref, "ONETWO,")
        self.assertEqual(edit_distance(ref, obs), 2)

    def test_timing_is_estimated_from_pcm(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "synthetic.wav"
            short = [10000] * (65 * 8)
            long = [10000] * (185 * 8)
            gap = [0] * (65 * 8)
            x = (gap + short + gap + long) * 3
            with wave.open(str(path), "wb") as stream:
                stream.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                stream.writeframes(struct.pack(f"<{len(x)}h", *x))
            self.assertEqual([row["estimated_wpm"] for row in measure(path)], [20, 20])
