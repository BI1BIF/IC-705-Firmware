"""Check the desktop tracking policy against changing samples and VFO faults."""

import unittest

from tools.satellite_panel_state import SatellitePanel, VfoState, VirtualVfo


def example():
    valid = {"position_valid": True, "utc_valid": True}
    def sample(offset=None):
        targets = {}
        if offset is not None:
            targets = {
                "A": {"rx_target_hz": 145_900_000 + offset, "tx_target_hz": 436_850_000 - offset*3},
                "B": {"rx_target_hz": 436_850_000 + offset*3, "tx_target_hz": 145_900_000 - offset},
            }
        return {"original_gps": valid, "targets": targets}

    return {"samples": [sample(), sample(3000), sample(1500), sample(-1400), sample(-3000), sample()],
            "controls": {"position_expired": {"original_gps": dict(valid, position_valid=False)},
                         "utc_expired": {"original_gps": dict(valid, utc_valid=False)}}}


class SatellitePanelTests(unittest.TestCase):
    def setUp(self):
        self.initial = VfoState(145_500_000, 433_500_000, "FM", "USB", "B", False)
        self.vfo = VirtualVfo(self.initial)
        self.panel = SatellitePanel(self.vfo)
        self.report = example()
        self.panel.select(self.report)

    def test_preview_does_not_write_and_armed_below_horizon_waits(self):
        other = example()
        self.panel.select(other)
        self.assertIs(self.panel.report, other)
        self.panel.choose_role("B")
        self.panel.step(1)
        self.assertEqual(self.panel.target["rx_target_hz"], 436_859_000)
        self.assertEqual(self.vfo.read(), self.initial)
        self.panel.step(0)
        self.panel.enable()
        self.assertEqual(self.panel.status, "below_horizon")
        self.assertFalse(self.vfo.writes)
        self.panel.step(1)
        self.assertEqual(self.vfo.read(), VfoState(145_897_000, 436_859_000, "FM", "FM", "B", True))
        self.panel.select(self.report)
        self.panel.choose_role("A")
        self.panel.step(0)
        self.assertIs(self.panel.report, other)
        self.assertEqual((self.panel.role, self.panel.index), ("B", 1))

    def test_ptt_hold_releases_to_latest_target_and_manual_stays_in_control(self):
        self.panel.step(1)
        self.panel.enable()
        frozen = self.vfo.read()
        self.panel.set_ptt(True)
        self.panel.step(2)
        self.panel.step(3)
        self.assertEqual(self.vfo.read(), frozen)
        self.assertEqual(len(self.vfo.writes), 1)
        self.panel.set_ptt(False)
        self.assertEqual(self.vfo.read(), VfoState(145_898_600, 436_854_200, "FM", "FM", "A", True))
        self.panel.take_over()
        self.panel.manual_tune()
        self.panel.step(4)
        self.assertEqual(self.panel.status, "manual")
        self.assertEqual(self.vfo.read().a_hz, 145_899_600)
        self.assertEqual(self.vfo.writes, [("tune", "accepted"), ("tune", "accepted"), ("manual", "accepted")])
        self.panel.restore()
        self.assertEqual(self.vfo.read(), self.initial)
        self.assertEqual(self.panel.status, "restored")

    def test_exit_waits_for_ptt_release_and_does_not_apply_pending_track(self):
        self.panel.step(1)
        self.panel.enable()
        self.panel.set_ptt(True)
        self.panel.step(4)
        self.panel.restore()
        self.assertEqual(self.panel.status, "exit_pending")
        self.assertEqual(self.vfo.writes, [("tune", "accepted")])
        self.panel.set_ptt(False)
        self.assertEqual(self.vfo.writes, [("tune", "accepted"), ("restore", "accepted")])
        self.assertEqual(self.vfo.read(), self.initial)

    def test_exit_waits_for_confirmed_rx_if_status_is_unknown_or_tx(self):
        self.panel.step(1)
        self.panel.enable()
        self.panel.set_ptt(True)
        self.panel.set_tx_status(True)
        self.panel.restore()
        self.panel.set_ptt(False)
        self.panel.set_tx_status(None)
        self.assertEqual((self.panel.status, self.panel.snapshot), ("exit_pending", self.initial))
        self.assertEqual(self.vfo.writes, [("tune", "accepted")])
        self.panel.set_tx_status(False)
        self.assertEqual(self.panel.status, "restored")
        self.assertEqual(self.vfo.read(), self.initial)

    def test_gps_and_utc_gate_tuning_even_when_releasing_ptt(self):
        self.panel.step(1)
        self.panel.enable()
        for index, flag in enumerate(("position_expired", "utc_expired"), 2):
            with self.subTest(flag=flag):
                frozen, count = self.vfo.read(), len(self.vfo.writes)
                self.panel.set_ptt(True)
                self.panel.set_gps(flag)
                self.panel.step(index)
                self.panel.set_ptt(False)
                self.assertEqual(self.panel.status, flag)
                self.assertIsNone(self.panel.target)
                self.assertEqual((self.vfo.read(), len(self.vfo.writes)), (frozen, count))
                self.panel.set_gps(None)
                self.assertEqual(self.panel.status, "tracking")
                self.assertEqual(len(self.vfo.writes), count + 1)
        frozen = self.vfo.read()
        self.panel.step(5)
        self.assertEqual((self.panel.status, self.vfo.read()), ("below_horizon", frozen))

    def test_failed_update_latches_and_failed_restore_retains_snapshot(self):
        for failure, expected in (("reject", "rejected"), ("mismatch", "mismatch")):
            with self.subTest(failure=failure):
                self.setUp()
                self.panel.step(1)
                self.panel.failure = failure
                self.panel.enable()
                self.assertEqual(self.panel.status, f"tune_{expected}")
                self.panel.step(2)
                self.assertEqual(len(self.vfo.writes), 1)
                if failure == "mismatch":
                    self.panel.failure = failure
                    self.panel.restore()
                    self.assertEqual(self.panel.status, f"restore_{expected}")
                    self.assertEqual(self.panel.snapshot, self.initial)
                self.panel.restore()
                self.assertEqual(self.vfo.read(), self.initial)
                self.assertIsNone(self.panel.snapshot)

    def test_unsolicited_vfo_change_does_not_get_overwritten(self):
        self.panel.step(1)
        self.panel.enable()
        changed = self.vfo.read().tuned(A=145_500_000)
        self.vfo.state = changed
        self.panel.step(2)
        self.assertEqual(self.panel.status, "unexpected_readback")
        self.assertEqual(self.vfo.read(), changed)
        self.assertEqual(len(self.vfo.writes), 1)


if __name__ == "__main__":
    unittest.main()
