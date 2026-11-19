"""Replay Japanese IC-705 1.40 GPS sentences and the original RX distance offline."""

import argparse
from hashlib import sha256
import json
from math import acos, cos, radians, sin
from pathlib import Path
from struct import unpack

from tools.decode_705_main import decode_main
from tools.decode_705_main import J140_DAT_SHA as DAT_SHA, J140_MAIN_SHA as MAIN_SHA
from tools.emulate_705 import SCRATCH, arm, call, machine, uc


GPS_MODE = 0x203EAA49 + 0x723
BYTE_RX, GPS_INIT, GPS_EXPIRE = 0x20212A34, 0x20212E64, 0x20213480
POSITION_AGE, UTC_AGE = 0x2038130E, 0x20381310
RECORD, RECORD_VALID = 0x205DDDC8, 0x203813EE
GEOMETRY, DISTANCE_WRITER, DISTANCE_CACHE = 0x20228DE8, 0x20073DF4, 0x203D9E30
PAGE_BUILD, PAGE_DISTANCE = 0x200B34B0, 0x204BACF2
RMC = "GPRMC,{time}.00,A,3530.0000,N,13930.0000,E,1.23,045.0,141126,,,A"
NO_FIX = "GPRMC,000001.00,V,,,,,,,151126,,,N"
ZDA = "GPZDA,000000.00,15,11,2026,00,00"
HERE = ("35300000N", "139300000E")
NORTH = ("35310000N", "139300000E")
EAST = ("35300000N", "139310000E")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nmea(payload, corrupt=False):
    checksum = 0
    for byte in payload.encode("ascii"):
        checksum ^= byte
    return f"${payload}*{checksum ^ int(corrupt):02X}\r\n".encode("ascii")


def degrees(field):
    width = len(field)-7
    value = int(field[:width]) + int(field[width:-1])/600000
    return -value if field[-1] in "SW" else value


def approximate_metres(here, point):
    if here == point:
        return 0.0
    lat, lon = map(lambda field: radians(degrees(field)), here)
    other_lat, other_lon = map(lambda field: radians(degrees(field)), point)
    dot = sin(lat)*sin(other_lat) + cos(lat)*cos(other_lat)*cos(other_lon-lon)
    return round(6371008.8 * acos(min(1, max(-1, dot))), 1)


class GPSGuest:
    def __init__(self, main):
        self.cpu = machine(main)
        self.cpu.reg_write(arm.UC_ARM_REG_C1_C0_2, 0xF00000)
        self.cpu.reg_write(arm.UC_ARM_REG_FPEXC, 0x40000000)
        self.cpu.mem_write(GPS_MODE, b"\1")  # Live GPS; mode 2 bypasses the live position flag.
        self.cpu.mem_write(0x203E84BF + 0x42, b"\1")  # Original RX position page.
        call(self.cpu, GPS_INIT)
        self.sentences = []

    def feed(self, payload, corrupt=False):
        line = nmea(payload, corrupt)
        self.sentences.append(line.decode("ascii").rstrip("\r\n"))
        for byte in line:
            call(self.cpu, BYTE_RX, byte)

    def read(self, address, length):
        return bytes(self.cpu.mem_read(address, length))

    def state(self):
        def get(entry, size):
            call(self.cpu, entry, SCRATCH)
            return self.read(SCRATCH, size).decode("ascii")

        return {
            "position_valid": bool(call(self.cpu, 0x20074650)),
            "utc_valid": bool(call(self.cpu, 0x2021300C)),
            "coordinates": [get(0x20212B20, 9), get(0x20212B40, 10)],
            "date_ddmmyy": get(0x20212B80, 6),
            "time_hhmmss": get(0x20212B64, 6),
            "position_counter": self.read(POSITION_AGE, 1)[0],
            "utc_counter": self.read(UTC_AGE, 1)[0],
            "fix_dimension": call(self.cpu, 0x20212FC0),
        }

    def expire(self, counter):
        require(counter in (POSITION_AGE, UTC_AGE), "expected an original GPS countdown")
        self.cpu.mem_write(counter, b"\0")
        call(self.cpu, GPS_EXPIRE)


def replay(main):
    gps = GPSGuest(main)
    cpu, read, feed = gps.cpu, gps.read, gps.feed
    states, distances, geometry_inputs = {}, {}, []

    def snapshot(name):
        state = gps.state()
        states[name] = state
        return state

    def observe_geometry(_cpu, _pc, _size, _data):
        regs = (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3)
        geometry_inputs.append([read(cpu.reg_read(reg), width).decode("ascii")
                                for reg, width in zip(regs, (9, 10, 9, 10))])

    cpu.hook_add(uc.UC_HOOK_CODE, observe_geometry, begin=GEOMETRY, end=GEOMETRY)

    def distance(name, point, valid=True):
        cpu.mem_write(RECORD_VALID, bytes((valid,)))
        cpu.mem_write(RECORD+0x0D, "".join(point).encode("ascii"))
        geometry_inputs.clear()
        call(cpu, DISTANCE_WRITER, 0, instruction_limit=500_000)
        raw, = unpack("<I", read(DISTANCE_CACHE, 4))
        call(cpu, PAGE_BUILD)
        page = read(PAGE_DISTANCE, 7).decode("ascii").rstrip()
        reference = approximate_metres(tuple(geometry_inputs[0][2:]), point) if geometry_inputs else None
        distances[name] = {"remote_record_valid": valid, "remote_coordinates": list(point),
                           "geometry_arguments": geometry_inputs.copy(), "distance_dm": raw,
                           "page_distance": page, "reference_metres": reference}
        return raw, page

    cold = snapshot("cold")
    require(not cold["position_valid"] and not cold["utc_valid"], "GPS flags set at initialization")
    feed(NO_FIX)
    require(not snapshot("cold_void_rmc")["position_valid"], "void RMC created a cold fix")
    for stamp in ("235957", "235958", "235959"):
        feed(RMC.format(time=stamp))
        state = snapshot(f"rmc_{stamp}")
        require(state["coordinates"] == list(HERE) and state["position_valid"], "RMC did not set position")
        require(state["utc_valid"] == (stamp == "235959"), "RMC time qualification changed")
    require((state["date_ddmmyy"], state["time_hhmmss"]) == ("141126", "235959"), "RMC UTC mismatch")

    feed("GPGSA,A,3,04,05,09,12,24,25,29,31,,,,,1.8,0.9,1.2")
    feed("GPGGA,235959.00,3530.0000,N,13930.0000,E,1,08,0.9,123.4,M,39.0,M,,")
    call(cpu, 0x20212BD8)  # Original altitude updater; firmware calls it after parsing.
    altitude, = unpack("<i", read(0x205DC900, 4))
    require(call(cpu, 0x20212FC0) == 3 and altitude == call(cpu, 0x20212CDC) == 4049,
            "unexpected GSA fix dimension or GGA altitude")
    feed(ZDA)
    midnight = snapshot("zda_midnight")
    require(midnight["utc_valid"] and (midnight["date_ddmmyy"], midnight["time_hhmmss"]) == ("151126", "000000")
            and midnight["position_counter"] == midnight["utc_counter"] == 120,
            "ZDA midnight rollover failed")

    require(distance("same_position", HERE) == (0, "0m"), "identical coordinates produced a nonzero range")
    for name, point, stock in (("north_one_minute", NORTH, (18522, "1852m")),
                               ("east_one_minute", EAST, (15079, "1508m"))):
        raw, page = distance(name, point)
        require((raw, page) == stock and abs(raw/10 - approximate_metres(HERE, point)) < 5
                and geometry_inputs == [[*point, *HERE]], f"unexpected original distance: {name}")
    require(distance("invalid_remote", NORTH, False) == (0xFFFFFFFF, "-----km") and not geometry_inputs,
            "invalid remote record reached geometry")

    # Drop both counters below their refresh value so the negative controls also detect refresh.
    cpu.mem_write(POSITION_AGE, bytes((119,)))
    cpu.mem_write(UTC_AGE, bytes((117,)))
    before_invalid = snapshot("before_invalid_sentences")
    feed("GPRMC,000001.00,A,3540.0000,N,13940.0000,E,1.23,045.0,151126,,,A", corrupt=True)
    feed("GPZDA,120000.00,15,11,2026,00,00", corrupt=True)
    require(snapshot("bad_checksums") == before_invalid, "bad checksum changed the published GPS data")
    feed(NO_FIX)
    require(snapshot("void_rmc_retains_fix") == before_invalid, "void RMC retention behavior changed")
    require(distance("void_rmc_before_expiry", NORTH) == (18522, "1852m"), "old fix stopped early")

    # Set only countdowns to their expiry value; let the original handler invalidate data.
    gps.expire(POSITION_AGE)
    expired = snapshot("position_expired")
    require(not expired["position_valid"] and expired["utc_valid"] and expired["coordinates"] == list(HERE)
            and expired["fix_dimension"] == 3,
            "position expiry did not separate coordinates from validity")
    require(distance("expired_local_valid_remote", NORTH) == (18522, "-----km"),
            "page consumed stale distance after the live fix expired")
    gps.expire(UTC_AGE)
    expired = snapshot("both_expired")
    require(not expired["position_valid"] and not expired["utc_valid"] and
            expired["date_ddmmyy"] == expired["time_hhmmss"] == " "*6, "UTC expiry did not clear published time")

    feed("GPRMC,000002.00,A,3531.0000,N,13930.0000,E,1.23,045.0,151126,,,A")
    reacquired = snapshot("position_reacquired")
    require(reacquired["position_valid"] and not reacquired["utc_valid"] and
            reacquired["coordinates"] == list(NORTH), "position did not recover independently")
    feed("GPZDA,000002.00,15,11,2026,00,00")
    reacquired = snapshot("position_and_utc_reacquired")
    require(reacquired["position_valid"] and reacquired["utc_valid"] and reacquired["time_hhmmss"] == "000002" and
            distance("reacquired_same_as_remote", NORTH) == (0, "0m"), "new fix did not reach the page")
    gps.expire(UTC_AGE)
    utc_lost = snapshot("utc_expired_position_remains")
    require(utc_lost["position_valid"] and not utc_lost["utc_valid"] and utc_lost["coordinates"] == list(NORTH),
            "UTC expiry incorrectly invalidated position")
    return {"sentences": gps.sentences, "states": states, "distances": distances, "altitude_internal": altitude,
            "altitude_input_metres": 123.4,
            "timer_model": "countdowns set to zero in guest RAM; real handler run; no elapsed-time claim"}


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("output", type=Path, help="JSON report path")
    args = parser.parse_args()
    dat = args.dat.read_bytes()
    require(sha256(dat).hexdigest() == DAT_SHA, "expected the original Japanese IC-705 1.40 DAT")
    _, main, manifest = decode_main(dat)
    require(manifest["main"]["sha256"] == MAIN_SHA, "unexpected J140 main program")
    report = {"dat_sha256": DAT_SHA, "main_sha256": MAIN_SHA, **replay(bytes(main))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(f"J140 GPS replay passed: {args.output}")


if __name__ == "__main__":
    cli()
