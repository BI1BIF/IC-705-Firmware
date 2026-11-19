"""Replay stock J140 split tuning and PTT boundaries in Unicorn; no radio transport."""

import argparse
import json
from hashlib import sha256
from pathlib import Path
from struct import pack, unpack

from tools.decode_705_main import decode_main, J140_DAT_SHA, J140_MAIN_SHA
from tools.emulate_705 import arm, call, machine, uc
from tools.replay_705_vfo_split import (
    FREQ_HZ, QUERIES, SELECT_VFO, SET_SPLIT, VFO, exchange_in_guest,
    frequency, read_in_guest, require, seed_vfos,
)


INIT_RANGES, RANGES = 0x20098B50, 0x203DABD8
CLASSIFIED_HZ, PARSED_HZ, COMMIT_VFO = 0x2001CC50, 0x2001D67C, 0x20103BA0
FLAGS, PTT_SOURCE, PANEL_PTT = 0x203806F4, 0x20380703, 0x203809C4
OPERATING_FREQUENCY, PTT_INIT = 0x20103258, 0x2010B2F8
PTT_PASSES = (0x2010B948, 0x2010BE98, 0x2010CBC0, 0x2010CD18, 0x2010C850)
STATUS_TASK, STATUS_STORE = 0x20109E74, 0x2010A084
PORT_MODE, PORT_PTT = 0xFCFE3204, 0xFCFE3210
TARGETS = ((145_903_015, 436_840_972), (145_896_985, 436_859_028))


def word(cpu, address):
    return unpack("<I", cpu.mem_read(address, 4))[0]


def byte(cpu, address):
    return cpu.mem_read(address, 1)[0]


def radio(main, selected, initialized=True, *, pair=FREQ_HZ, split=True):
    cpu = machine(main)
    seed_vfos(cpu, pair)
    if initialized:
        call(cpu, INIT_RANGES)
    require(call(cpu, SELECT_VFO[selected]) == 0, "stock VFO selection failed")
    call(cpu, SET_SPLIT, 0, int(split))
    return cpu


def readbacks(cpu, selected, pair, tx=False):
    replies = {command: read_in_guest(cpu, command)[0] for command in QUERIES}
    cached, current, other, candidate = (
        frequency(replies[c]) for c in ("03", "25 00", "25 01", "1c 03"))
    require(replies["0f"] == b"\1" and replies["1c 00"] == bytes([tx]),
            "Split or RX/TX readback changed unexpectedly")
    require((byte(cpu, VFO + 74) >> 2) & 1 == selected, "selected VFO changed unexpectedly")
    require((cached, current, other, candidate) == (pair[selected], pair[selected],
                                                     pair[1 - selected], pair[1 - selected]),
            "CI-V frequency readback disagrees with split fixture")
    working = [word(cpu, VFO + off) for off in (1, 37)]
    backing = [word(cpu, VFO + off) for off in (79, 115)]
    require(working == backing == [current, other], "guest VFO records disagree")
    operating = call(cpu, OPERATING_FREQUENCY, 0)
    require(operating == (candidate if tx else current), "stock operating frequency disagrees")
    return {"selected": "AB"[selected], "split": True, "tx_status": tx, "cache_03_hz": cached,
            "operating_helper_hz": operating, "tx_candidate_hz": candidate,
            "a_hz": backing[selected], "b_hz": backing[1 - selected]}


def tune(cpu, relative, hz):
    trace = {}

    def capture(cpu, address, _size, _data):
        trace[address] = cpu.reg_read(arm.UC_ARM_REG_R0)

    hooks = [cpu.hook_add(uc.UC_HOOK_CODE, capture, begin=pc, end=pc)
             for pc in (CLASSIFIED_HZ, PARSED_HZ, COMMIT_VFO)]
    try:
        payload = bytes([0x25, relative]) + bytes.fromhex(f"{hz:010d}")[::-1]
        response, _ = exchange_in_guest(cpu, payload)
    finally:
        for hook in hooks:
            cpu.hook_del(hook)
    require(response[2:-1] in (b"\xfb", b"\xfa") and CLASSIFIED_HZ in trace and PARSED_HZ in trace,
            "unexpected stock tuning path")
    return {"relative_vfo": relative, "requested_hz": hz, "reply": response[2:-1].hex().upper(),
            "range_classifier": trace[CLASSIFIED_HZ], "validated_hz": trace[PARSED_HZ],
            "record_commit": COMMIT_VFO in trace}


def tuning_replay(main, selected):
    cpu = radio(main, selected, initialized=False)
    targets = TARGETS[selected]
    other = 1 - selected
    initial = readbacks(cpu, selected, FREQ_HZ)
    miss = tune(cpu, 1, targets[other])
    require(miss["range_classifier"] & 0x80 and miss["reply"] == "FA"
            and miss["validated_hz"] == 0 and not miss["record_commit"],
            "uninitialized range table did not reject the target before commit")
    unchanged = readbacks(cpu, selected, FREQ_HZ)
    require(unchanged == initial, "rejected tuning changed A/B or Split")

    # Only let the original routine populate the range table. No host-supplied ranges.
    call(cpu, INIT_RANGES)
    ranges = [list(unpack("<II", cpu.mem_read(RANGES + 8*i, 8))) for i in range(3)]
    require(all(lo <= hi for lo, hi in ranges) and word(cpu, RANGES + 24) == 0xffffffff,
            "unexpected stock range table")
    steps = []
    pair = list(FREQ_HZ)
    for label, goal in (("tune", targets), ("restore", FREQ_HZ)):
        for relative, slot in enumerate((selected, other)):
            step = tune(cpu, relative, goal[slot])
            require(step["reply"] == "FB" and not step["range_classifier"] & 0x80
                    and step["validated_hz"] == goal[slot] and step["record_commit"],
                    "expected stock VFO commit")
            pair[slot] = goal[slot]
            steps.append({"stage": label, **step, "readback": readbacks(cpu, selected, pair)})
    require(steps[-1]["readback"] == initial, "A/B restore did not restore all initial readbacks")
    return {"selected": "AB"[selected], "initial": initial, "missing_range_control": miss,
            "after_rejection": unchanged, "initialized_receive_ranges_hz": ranges, "steps": steps}


def ptt_replay(main):
    cpu = radio(main, 0)
    cpu.mem_map(0xFCFE3000, 0x1000)
    cpu.mem_write(PORT_MODE, pack("<H", 0x40))
    cpu.mem_write(PORT_PTT, pack("<H", 0x2000))

    def guard(_cpu, kind, address, size, _value, _data):
        require(kind == uc.UC_MEM_READ and size == 2 and address in (PORT_MODE, PORT_PTT),
                f"unexpected guest I/O at {address:#x}")

    cpu.hook_add(uc.UC_HOOK_MEM_READ | uc.UC_HOOK_MEM_WRITE, guard, begin=0xFCFE3000, end=0xFCFE3FFF)
    call(cpu, PTT_INIT)
    status_stores = []

    def observe_store(_cpu, address, _size, _data):
        status_stores.append(address)

    cpu.hook_add(uc.UC_HOOK_CODE, observe_store, begin=STATUS_STORE, end=STATUS_STORE)

    def state():
        return {"ptt_ram_hex": bytes(cpu.mem_read(PANEL_PTT, 3)).hex(),
                "control_flags_hex": f"{byte(cpu, FLAGS):02x}", "request_source": byte(cpu, PTT_SOURCE),
                "readback": readbacks(cpu, 0, FREQ_HZ)}

    def passes():
        for _ in range(3):
            for entry in PTT_PASSES:
                call(cpu, entry)
            call(cpu, STATUS_TASK)

    physical = []
    for label, down in (("idle", False), ("pressed", True), ("held", True), ("released", False)):
        cpu.mem_write(PORT_PTT, pack("<H", 0 if down else 0x2000))
        passes()
        require(bool(byte(cpu, PANEL_PTT) & 1) == down and not byte(cpu, FLAGS) & 0xA0,
                "guest key state/request mismatch")
        physical.append({"edge": label, **state()})
    requests = []
    for down in (True, True, False, False):
        response, _ = exchange_in_guest(cpu, bytes([0x1c, 0, down]))
        passes()
        require(response[2:-1] == b"\xfb" and bool(byte(cpu, FLAGS) & 0x20) == down
                and byte(cpu, PTT_SOURCE) == 2, "guest request bit did not follow CI-V acknowledgement")
        requests.append({"requested": down, "reply": "FB", **state()})
    require(not status_stores, "stock task published a change in the isolated fixture")

    # Separate positive control: supply only the published status consumer's input in guest RAM.
    # This does not simulate a producer, execute a transmit sequence or authorize any radio action.
    control = []
    for selected in (0, 1):
        isolated = radio(main, selected)
        for status in (False, True, False):
            isolated.mem_write(FLAGS, bytes([0x80 if status else 0]))
            control.append(readbacks(isolated, selected, FREQ_HZ, tx=status))
    return {"synthetic_panel_pin": physical, "civ_request": requests, "injected_status_control": control,
            "task_passes_per_edge": 3, "status_task_called": True, "status_transitions_published": len(status_stores)}


def replay(main):
    return {"tuning": [tuning_replay(main, selected) for selected in (0, 1)], "ptt": ptt_replay(main)}


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("output", type=Path, help="new JSON report (will not overwrite files)")
    args = parser.parse_args()
    dat = args.dat.read_bytes()
    require(sha256(dat).hexdigest() == J140_DAT_SHA, "expected the original Japanese IC-705 1.40 DAT")
    _, main, manifest = decode_main(dat)
    require(manifest["main"]["sha256"] == J140_MAIN_SHA, "unexpected J140 main program")
    result = {"dat_sha256": J140_DAT_SHA, "main_sha256": J140_MAIN_SHA, **replay(bytes(main))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as out:
        json.dump(result, out, indent=2)
        out.write("\n")
    print(f"J140 offline PTT/tuning replay passed: {args.output}")


if __name__ == "__main__":
    cli()
