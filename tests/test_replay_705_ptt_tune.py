"""Integration check against the local, untracked Japanese 1.40 update."""

from hashlib import sha256
from importlib.util import find_spec
from pathlib import Path
import unittest

from tools.decode_705_main import J140_DAT_SHA, J140_MAIN_SHA, decode_main


DAT = Path(__file__).resolve().parents[1] / "firmware" / "705J140.dat"


@unittest.skipUnless(DAT.is_file() and find_spec("unicorn"), "needs the local J140 DAT and Unicorn")
class StockPttAndTuningTests(unittest.TestCase):
    def test_stock_arm_guest_reaches_all_validated_boundaries(self):
        from tools.replay_705_ptt_tune import replay

        dat = DAT.read_bytes()
        self.assertEqual(sha256(dat).hexdigest(), J140_DAT_SHA)
        _, main, manifest = decode_main(dat)
        self.assertEqual(manifest["main"]["sha256"], J140_MAIN_SHA)
        result = replay(bytes(main))  # The runner checks individual ARM responses and data writes.
        for scenario, wanted in zip(result["tuning"], (436_840_972, 145_896_985), strict=True):
            first, both, *_ = scenario["steps"]
            self.assertNotEqual(first["readback"]["tx_candidate_hz"], wanted)
            self.assertEqual(both["readback"]["tx_candidate_hz"], wanted)
        self.assertEqual(result["ptt"]["status_transitions_published"], 0)
