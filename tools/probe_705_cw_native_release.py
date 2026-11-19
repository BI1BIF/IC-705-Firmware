"""Replay a stock J140 pen-up report against two exact packaged CW applications."""

import argparse
import json
from pathlib import Path
from struct import pack

from tools.build_705_cw_sim import load_image
from tools.emulate_705 import call, machine, uc
from tools.probe_705_cw_session import read_session
from tools.render_705_display import require
from tools.replay_705_settings import TOUCH_POLL, TOUCH_SAMPLE


STATE = 0x20900000
PEN_STATE, PEN_AGE, GPIO_INPUT = 0x2038044C, 0x20401FBC, 0xFCFE320C
PUBLISH, STOCK_RELEASE = 0x2008DBDC, 0x20108644
NATIVE_REPORT = pack(">BHH", 0, 9999, 9999)


def press(cpu, x, y):
    cpu.mem_write(TOUCH_SAMPLE, pack(">BHH", 0, x, y))
    call(cpu, TOUCH_POLL)


def release(cpu):
    # This fixture starts after pen-up debounce, before the original release handler.
    cpu.mem_write(PEN_STATE+7, b"\x01")
    cpu.mem_write(PEN_AGE+33, b"\x19")
    cpu.mem_write(GPIO_INPUT, b"\0\x10")
    call(cpu, PUBLISH)
    raw = bytes(cpu.mem_read(TOUCH_SAMPLE, 5))
    require(raw == NATIVE_REPORT, f"stock producer did not publish its sentinel: {raw.hex()}")
    call(cpu, TOUCH_POLL)
    return raw.hex()


def run(bundle, previous):
    (app, _, _, digest, _), meta = load_image(bundle)
    require(meta.get("picker_id") == 277, "requires the native CW selector build")
    cpu = machine(app)
    cpu.mem_map(0xFCFE3000, 0x1000)
    cpu.mem_write(meta["symbols"]["cw_state_anchor"], pack("<I", STATE))
    cpu.mem_write(STATE, pack("<2I", 1, 1))
    cpu.mem_write(STATE+0x5f4, pack("<I", 1))  # Native picker has accepted its opening press.
    cpu.mem_write(STATE+1692, pack("<I", 350))
    cpu.mem_write(0x203E2128, b"\x20")
    stock_releases = []
    cpu.hook_add(uc.UC_HOOK_CODE, lambda *_: stock_releases.append(STOCK_RELEASE),
                 begin=STOCK_RELEASE, end=STOCK_RELEASE)

    reports = [release(cpu)]
    controls = []
    for name, x, y, field in (("SET",430,254,"color_open"), ("SET exit",430,254,"color_open"),
                              ("AUTO/WPM",430,157,"speed_picker"), ("page",48,254,"menu_two")):
        before = read_session(cpu, STATE)[field]
        press(cpu, x, y)
        after = read_session(cpu, STATE)[field]
        controls.append(dict(name=name, before=before, after=after, accepted=before != after))
        reports.append(release(cpu))
    require([control["accepted"] for control in controls] == [not previous]*4,
            f"unexpected button behavior: {controls}")
    require(len(stock_releases) == (0 if previous else len(reports)), "native pen-up not handed back as expected")
    return dict(application_sha256=digest, stock_release_reports=reports,
                original_reader_release_count=len(stock_releases), softkeys=controls)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("previous", "candidate", "report"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    evidence = dict(scope="stock producer from post-debounce pen-up; stock ARM input poll; no radio",
                    previous=run(args.previous, previous=True), candidate=run(args.candidate, previous=False))
    require(evidence["previous"]["application_sha256"] != evidence["candidate"]["application_sha256"],
            "expected distinct applications")
    with args.report.open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, indent=2)
        stream.write("\n")
    print(args.report)


if __name__ == "__main__":
    main()
