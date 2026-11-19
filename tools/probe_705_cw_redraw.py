"""Compare automatic CW refresh requests in exact PC images, without a radio.

Run with the existing Unicorn dependencies on PYTHONPATH:
python -m tools.probe_705_cw_redraw old.ic705sim new.ic705sim report.json

The fixture supplies the stock millisecond clock and decoded-frame counter.
This measures requests, not physical LCD frame rate or ARM cycle time.
"""

import argparse
import json
from pathlib import Path
from struct import pack, unpack_from

from tools.build_705_cw_sim import load_image
from tools.emulate_705 import BASE, call, machine
from tools.probe_705_cw_field_audio import STATE, bl_target
from tools.render_705_display import require


INPUT = 0x2007F1A4
CLOCK, DIRTY = 0x20381E08, 0x203806F7


def first_call(main, entry):
    calls = [entry + offset for offset in range(0, 80, 4)
             if unpack_from("<I", main, entry + offset - BASE)[0] & 0xFF000000 == 0xEB000000]
    require(calls, "no A32 bridge call")
    return bl_target(main, calls[0])


def measure(path, start=0):
    (main, _, _, digest, _), meta = load_image(path)
    cpu = machine(main)
    cpu.mem_write(meta["symbols"]["cw_state_anchor"], pack("<I", STATE))
    cpu.mem_write(STATE, pack("<I", 1))
    cpu.mem_write(0x203E2128, b"\x20")
    # Same already-open page, no diagnostic count changes or simulated hardware keys.
    cpu.mem_write(STATE + 0x74C, pack("<I", start))
    entry = first_call(main, int(meta["branch_sites"][hex(INPUT)], 16))
    requests = []
    for ms in range(0, 1001, 10):
        cpu.mem_write(CLOCK, pack("<I", (start + ms) & 0xFFFFFFFF))
        cpu.mem_write(STATE + 8, pack("<I", ms // 10))
        cpu.mem_write(DIRTY, b"\x00")
        call(cpu, entry)
        if cpu.mem_read(DIRTY, 1)[0] & 0x40:
            requests.append(ms)
    return dict(application_sha256=digest, start_ms=start, request_ms=requests, count=len(requests))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("previous", "candidate", "report"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    before, after = measure(args.previous), measure(args.candidate)
    require(before["count"] == 12 and after["count"] == 8 and
            min(b-a for a, b in zip(after["request_ms"], after["request_ms"][1:])) >= 120,
            f"unexpected refresh cadence: {before}, {after}")
    wrap = measure(args.candidate, 0xFFFFFF00)
    # The first absolute timestamp can request one early frame; subsequent deltas
    # must remain bounded as the stock clock wraps.
    require(all(b-a >= 120 for a, b in zip(wrap["request_ms"], wrap["request_ms"][1:])),
            f"clock wrap changed the refresh bound: {wrap}")
    result = dict(scope="isolated packaged ARM input routine; simulated clock/frame inputs only",
                  previous=before, candidate=after, clock_wrap=wrap,
                  limitation="No physical frame-time or touchscreen sampling measurement.")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
