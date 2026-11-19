import unittest

from tools.make_cw_fixtures import PAD_FRAMES, render


class CWFixtureTests(unittest.TestCase):
    def test_clean_dash_word_gap_and_dot_at_twenty_wpm(self):
        pcm = render("T E", 20, 600, None)
        unit = 480
        self.assertEqual(len(pcm) // 2, 2 * PAD_FRAMES + 11 * unit)
        gap_start = (PAD_FRAMES + 3 * unit) * 2
        gap_end = gap_start + 7 * unit * 2
        self.assertTrue(any(pcm[PAD_FRAMES * 2:gap_start]))
        self.assertFalse(any(pcm[gap_start:gap_end]))
        self.assertTrue(any(pcm[gap_end:gap_end + unit * 2]))
