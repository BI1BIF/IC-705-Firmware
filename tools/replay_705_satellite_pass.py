"""Replay one historical pass with original J140 GPS and VFO routines; output JSON only."""

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import asin, cos, degrees, dist, radians, sin, sqrt
from pathlib import Path


FIXTURE = Path(__file__).resolve().parents[1] / "samples" / "satellite-pass.json"
C_KM_S = 299792.458
STEP = timedelta(seconds=20)
TIME_TOL_S = 1.0
ANGLE_TOL_DEG = 0.01
RANGE_TOL_KM = 0.1
RATE_TOL_KM_S = 0.002
FREQ_TOL_HZ = 3


def require(condition, message):
    if not condition:
        raise ValueError(message)


def iso(stamp):
    return stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def select(catalog, satellite_id):
    require(satellite_id in catalog, f"unknown satellite ID {satellite_id}; use --list")
    return catalog[satellite_id]


def tle_record(satellite_id, lines):
    from sgp4.api import Satrec

    require(len(lines) == 2, "expected two TLE lines")
    for index, line in enumerate(lines, 1):
        require(len(line) == 69 and line[:2] == f"{index} " and line[2:7] == satellite_id,
                "wrong TLE length, line number or catalog ID")
        checksum = sum(int(c) if c.isdigit() else c == "-" for c in line[:68])
        require(line[-1] == str(checksum % 10), "invalid TLE checksum")
    return Satrec.twoline2rv(*lines)


def julian(stamp):
    from sgp4.api import jday

    return jday(stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute,
                stamp.second + stamp.microsecond / 1e6)


def teme(record, jd, fraction):
    from sgp4.api import SGP4_ERRORS

    error, xyz, velocity = record.sgp4(jd, fraction)
    require(error == 0, f"SGP4 failed: {SGP4_ERRORS.get(error, error)}")
    return xyz, velocity


def geometry(record, stamp, site):
    """Geometric elevation in degrees and slant range in km; UTC approximates UT1."""
    from sgp4.propagation import gstime

    jd, fraction = julian(stamp)
    age_days = (jd - record.jdsatepoch) + (fraction - record.jdsatepochF)
    require(abs(age_days) <= 7, "TLE outside the +/-7 day replay policy")
    (x, y, z), _ = teme(record, jd, fraction)
    angle = gstime(jd + fraction)
    ecef = (cos(angle)*x + sin(angle)*y, -sin(angle)*x + cos(angle)*y, z)
    lat, lon, height_m = site
    phi, lam = radians(lat), radians(lon)
    a, f = 6378.137, 1 / 298.257223563
    e2 = f * (2 - f)
    n = a / sqrt(1 - e2 * sin(phi)**2)
    up = (cos(phi)*cos(lam), cos(phi)*sin(lam), sin(phi))
    observer = tuple(axis*(radius + height_m/1000)
                     for axis, radius in zip(up, (n, n, n*(1-e2))))
    line = tuple(p - q for p, q in zip(ecef, observer))
    slant = dist(ecef, observer)
    vertical = sum(a*b for a, b in zip(up, line)) / slant
    return degrees(asin(min(1.0, max(-1.0, vertical)))), slant


def sample(record, stamp, site):
    elevation, slant = geometry(record, stamp, site)
    half = timedelta(seconds=0.5)
    rate = geometry(record, stamp + half, site)[1] - geometry(record, stamp - half, site)[1]
    return elevation, slant, rate


def times(start, end):
    while start < end:
        yield start
        start += STEP
    yield end


def pass_events(record, site, start, end):
    def altitude(stamp):
        return geometry(record, stamp, site)[0]

    grid = list(times(start, end))
    elevation = [altitude(stamp) for stamp in grid]
    require(elevation[0] < 0 and elevation[-1] < 0, "replay window truncates the pass")
    crossings = []
    for i, (left, right) in enumerate(zip(grid, grid[1:])):
        above = elevation[i] >= 0
        if above == (elevation[i + 1] >= 0):
            continue
        while right - left > timedelta(milliseconds=40):
            middle = left + (right - left)/2
            if (altitude(middle) >= 0) == above:
                left = middle
            else:
                right = middle
        crossings.append(left + (right-left)/2)
    require(len(crossings) == 2, "expected exactly one complete pass")
    index = max(range(len(grid)), key=elevation.__getitem__)
    left, right = grid[index - 1], grid[index + 1]
    while right - left > timedelta(milliseconds=40):
        span = (right-left)/3
        if altitude(left + span) < altitude(right - span):
            left += span
        else:
            right -= span
    return crossings[0], left + (right-left)/2, crossings[1]


def reference(name, lines, site, start, end):
    from skyfield.api import EarthSatellite, load, wgs84

    ts = load.timescale(builtin=True)
    satellite = EarthSatellite(*lines, name, ts)
    observer = wgs84.latlon(*site)
    instants, events = satellite.find_events(observer, ts.from_datetime(start), ts.from_datetime(end),
                                            altitude_degrees=0.0)
    require(list(events) == [0, 1, 2], "Skyfield did not find exactly one complete pass")

    def observe(stamp):
        pos = (satellite - observer).at(ts.from_datetime(stamp))
        _, _, distance, _, _, rate = pos.frame_latlon_and_rates(observer)
        return float(pos.altaz()[0].degrees), float(distance.km), float(rate.km_per_s)

    return [t.utc_datetime() for t in instants], observe


def ingest(gps, station, stamp):
    clock = stamp.strftime("%H%M%S")
    gps.feed(f"GPRMC,{clock}.00,A,{station['latitude_nmea']},{station['longitude_nmea']},"
             f"0.0,0.0,{stamp:%d%m%y},,,A")
    gps.feed(f"GPZDA,{clock}.00,{stamp:%d,%m,%Y},00,00")
    return gps.state()


def gps_fix(state, altitude_m):
    from tools.replay_705_gps_inputs import degrees as decode_degrees

    date, time = state["date_ddmmyy"], state["time_hhmmss"]
    # Fixtures fall in 2000–2099. The stock getter only returns a two-digit year.
    require(len(date) == len(time) == 6 and (date + time).isascii() and (date + time).isdigit(),
            "malformed original GPS date or UTC")
    stamp = datetime.strptime(date[:4] + "20" + date[4:] + time, "%d%m%Y%H%M%S").replace(tzinfo=timezone.utc)
    return stamp, (*map(decode_degrees, state["coordinates"]), altitude_m)


def plan(state, roles, record, altitude_m):
    """Produce advisory frequencies from guest reads. No transport or setter."""
    for flag, reason in (("position_valid", "position_expired"), ("utc_valid", "utc_expired")):
        if not state[flag]:
            return {"status": reason, "targets": {}}
    stamp, site = gps_fix(state, altitude_m)
    elevation, slant, rate = sample(record, stamp, site)
    result = {"status": "below_horizon", "targets": {}, "utc": iso(stamp),
              "elevation_deg": elevation, "range_km": slant, "range_rate_km_s": rate}
    if elevation < 0:
        return result
    split = [role for role in roles if role["split"]]
    listening = [role for role in split if role["receiving"]]
    result["status"] = "tracking" if listening else "not_receiving" if split else "split_off"
    for role in listening:
        rx, tx = role["rx_hz"], role["tx_candidate_hz"]
        drx, dtx = round(-rx*rate/C_KM_S), round(tx*rate/C_KM_S)
        result["targets"][role["selected"]] = {
            "rx_delta_hz": drx, "tx_delta_hz": dtx, "rx_target_hz": rx+drx, "tx_target_hz": tx+dtx,
        }
    return result


def replay(main, satellite_id, entry, station):
    from tools.replay_705_gps_inputs import GPSGuest, POSITION_AGE, UTC_AGE
    from tools.replay_705_vfo_split import replay as replay_vfo

    gps = GPSGuest(main)
    start, end = map(datetime.fromisoformat, entry["window_utc"])
    initial = ingest(gps, station, start)
    altitude_m = station["altitude_m"]
    require(initial["position_valid"] and initial["utc_valid"], f"original GPS did not lock: {initial}")
    first, site = gps_fix(initial, altitude_m)
    require(first == start and all(abs(x-y) < 1e-8 for x, y in zip(site, station["expected_lat_lon"])),
            "original GPS position or UTC differs from the independent fixture")
    record = tle_record(satellite_id, entry["tle"])
    events = pass_events(record, site, first, end)
    ref_events, observe = reference(entry["name"], entry["tle"], site, first, end)
    event_errors = [abs((a-b).total_seconds()) for a, b in zip(events, ref_events)]
    require(max(event_errors) <= TIME_TOL_S, f"pass events differ from reference: {event_errors}")

    vfos = replay_vfo(main)["states"]
    roles = [row for row in vfos if row["split"]]
    require([r["selected"] for r in roles] == ["A", "B"] and
            roles[0]["rx_hz"] == roles[1]["tx_candidate_hz"] and
            roles[1]["rx_hz"] == roles[0]["tx_candidate_hz"], "stock roles did not swap")
    # Original GPS publishes whole seconds. Sample on each side of geometric rise and set.
    def near(stamp, delta):
        return stamp.replace(microsecond=0) + timedelta(seconds=delta)

    rise, peak, setting = events
    checks = [near(event, s) for event in (rise, setting) for s in (-2, 2)]
    stamps = sorted(set(times(first, end)) | set(checks) | {near(peak, 0)})
    rows, by_stamp = [], {}
    errors = {"elevation_deg": 0, "range_km": 0, "range_rate_km_s": 0, "frequency_hz": 0}
    for expected in stamps:
        state = ingest(gps, station, expected)
        require(state["position_valid"] and state["utc_valid"] and
                gps_fix(state, altitude_m) == (expected, site), "original GPS drifted from input fixture")
        row = plan(state, roles, record, altitude_m)
        alt, slant, rate = observe(expected)
        for key, ref in (("elevation_deg", alt), ("range_km", slant), ("range_rate_km_s", rate)):
            errors[key] = max(errors[key], abs(row[key] - ref))
        require(bool(row["targets"]) == (alt >= 0), "tracking disagrees with reference horizon")
        for role in roles if row["targets"] else ():
            target = row["targets"][role["selected"]]
            rx, tx = role["rx_hz"], role["tx_candidate_hz"]
            # Reference uses the received fraction and its reciprocal for uplink precompensation.
            fraction = 1 - rate/C_KM_S
            errors["frequency_hz"] = max(errors["frequency_hz"],
                                         abs(target["rx_target_hz"] - round(rx*fraction)),
                                         abs(target["tx_target_hz"] - round(tx/fraction)))
            if abs(rate) > RATE_TOL_KM_S:
                require(target["rx_delta_hz"]*rate < 0 < target["tx_delta_hz"]*rate,
                        f"Doppler direction disagrees with reference for VFO {role['selected']}")
        by_stamp[expected] = row
        rows.append({**row, "original_gps": state,
                     "reference": {"elevation_deg": alt, "range_km": slant, "range_rate_km_s": rate}})
    require(errors["elevation_deg"] <= ANGLE_TOL_DEG and errors["range_km"] <= RANGE_TOL_KM
            and errors["range_rate_km_s"] <= RATE_TOL_KM_S
            and errors["frequency_hz"] <= FREQ_TOL_HZ, f"sample errors exceed tolerance: {errors}")
    before, arriving, departing, after = [by_stamp[t] for t in checks]
    require([r["status"] for r in (before, arriving, departing, after)] ==
            ["below_horizon", "tracking", "tracking", "below_horizon"], "bad horizon boundary behavior")
    mid = near(peak, 0)
    good = ingest(gps, station, mid)
    controls = {"split_off": plan(good, [vfos[0]], record, altitude_m),
                "not_receiving": plan(good, [{**roles[0], "receiving": False}], record, altitude_m)}
    require(all(x["status"] == key and not x["targets"] for key, x in controls.items()),
            "inhibited VFO produced a target or an incorrect status")
    for counter, reason, other in ((POSITION_AGE, "position_expired", "utc_valid"),
                                   (UTC_AGE, "utc_expired", "position_valid")):
        gps.expire(counter)
        state = gps.state()
        result = plan(state, roles, record, altitude_m)
        require(result == {"status": reason, "targets": {}} and state[other]
                and state["coordinates"] == good["coordinates"], f"did not stop immediately: {reason}")
        restored = ingest(gps, station, mid)
        recovered = plan(restored, roles, record, altitude_m)
        require(recovered["targets"] == by_stamp[mid]["targets"], f"did not resume after {reason}")
        controls[reason] = {"original_gps": state, **result, "restored_gps": restored,
                            "restored_targets": recovered["targets"]}

    return {"satellite_id": satellite_id, "satellite": entry, "site_lat_lon_alt_m": site,
            "stock_vfo": roles, "events": {
                key: {"utc": iso(t), "reference_utc": iso(ref), "error_s": err,
                      "elevation_deg": geometry(record, t, site)[0]}
                for key, t, ref, err in zip(("rise", "peak", "set"), events, ref_events, event_errors)},
            "maximum_errors": errors, "controls": controls, "samples": rows, "nmea": gps.sentences,
            "boundary_sample_utc": [iso(t) for t in checks],
            "timer_model": "original expiry handler after forcing individual countdowns to zero; no real timer",
            "rf_model": "synthetic carrier pair from stock VFO fixture; numerical advisories only"}


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path, nargs="?", help="original Japanese 1.40 DAT")
    parser.add_argument("output", type=Path, nargs="?", help="local JSON result")
    parser.add_argument("--list", action="store_true", help="list built-in historical replay choices")
    parser.add_argument("--satellite", default="25544", help="five-digit catalog ID (default 25544)")
    args = parser.parse_args()
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if args.list:
        for key, entry in fixture["satellites"].items():
            print(f"{key}  {entry['name']}  ({entry['window_utc'][0][:10]})")
        return
    if args.dat is None or args.output is None:
        parser.error("DAT and output are required unless using --list")
    try:
        entry = select(fixture["satellites"], args.satellite)
        require(args.dat.resolve() != args.output.resolve(), "output cannot overwrite the DAT")
        require(not args.output.exists(), "output already exists; choose a new path")
        from tools.decode_705_main import J140_DAT_SHA as DAT_SHA, J140_MAIN_SHA as MAIN_SHA, decode_main

        dat = args.dat.read_bytes()
        require(sha256(dat).hexdigest() == DAT_SHA, "expected the original Japanese IC-705 1.40 DAT")
        _, main, manifest = decode_main(dat)
        require(manifest["main"]["sha256"] == MAIN_SHA, "unexpected J140 main program")
        report = {"dat_sha256": DAT_SHA, "main_sha256": MAIN_SHA,
                  **replay(bytes(main), args.satellite, entry, fixture["station"])}
    except (ModuleNotFoundError, ValueError) as error:
        parser.exit(2, f"Replay failed: {error}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(f"J140 satellite pass passed ({args.satellite}): {args.output}")


if __name__ == "__main__":
    cli()
