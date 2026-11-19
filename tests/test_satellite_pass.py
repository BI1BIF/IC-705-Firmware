"""Orbit fixtures, including a horizon crossing with no in-view Doppler reversal."""

from datetime import datetime, timedelta
import importlib.util
import json
import unittest

from tools import replay_705_satellite_pass as orbit


FIXTURE = json.loads(orbit.FIXTURE.read_text(encoding="utf-8"))
CATALOG = FIXTURE["satellites"]
SITE = (*FIXTURE["station"]["expected_lat_lon"], FIXTURE["station"]["altitude_m"])


class SatelliteSelectionTests(unittest.TestCase):
    def test_exact_id_preserves_leading_zeroes(self):
        self.assertEqual(orbit.select(CATALOG, "00005")["tle"][0][2:7], "00005")
        with self.assertRaisesRegex(ValueError, "unknown satellite ID"):
            orbit.select(CATALOG, "5")

    def test_either_invalid_gps_flag_stops_before_reading_stale_values(self):
        for flags, reason in (((False, True), "position_expired"), ((True, False), "utc_expired")):
            state = dict(zip(("position_valid", "utc_valid"), flags))
            self.assertEqual(orbit.plan(state, (), None, 0), {"status": reason, "targets": {}})


@unittest.skipUnless(importlib.util.find_spec("sgp4"), "install optional orbit requirements")
class SatelliteOrbitTests(unittest.TestCase):
    def setUp(self):
        self.lines = CATALOG["00005"]["tle"]
        self.record = orbit.tle_record("00005", self.lines)

    def test_vallado_epoch_teme(self):
        pos, vel = orbit.teme(self.record, self.record.jdsatepoch, self.record.jdsatepochF)
        for actual, expected in zip(pos, (7022.46529266, -1400.08296755, 0.03995155)):
            self.assertAlmostEqual(actual, expected, delta=1e-7)
        for actual, expected in zip(vel, (1.893841015, 6.405893759, 4.534807250)):
            self.assertAlmostEqual(actual, expected, delta=1e-8)

    def test_bad_checksum_and_stale_orbit(self):
        with self.assertRaisesRegex(ValueError, "checksum"):
            orbit.tle_record("00005", (self.lines[0][:-1] + "4", self.lines[1]))
        with self.assertRaisesRegex(ValueError, "replay policy"):
            orbit.geometry(self.record, datetime.fromisoformat("2000-07-08T00:00:00Z"), SITE)

    def test_grazing_pass_is_still_approaching_at_set(self):
        start = datetime.fromisoformat("2000-06-28T00:10:00Z")
        end = start + timedelta(minutes=25)
        rise, peak, setting = orbit.pass_events(self.record, SITE, start, end)
        self.assertLess(orbit.geometry(self.record, peak, SITE)[0], 2)
        before = setting - timedelta(seconds=2)
        after = setting + timedelta(seconds=2)
        self.assertGreater(orbit.geometry(self.record, before, SITE)[0], 0)
        self.assertLess(orbit.geometry(self.record, after, SITE)[0], 0)
        self.assertLess(orbit.sample(self.record, before, SITE)[2], 0)
        with self.assertRaisesRegex(ValueError, "truncates"):
            orbit.pass_events(self.record, SITE, rise + timedelta(seconds=2), end)
