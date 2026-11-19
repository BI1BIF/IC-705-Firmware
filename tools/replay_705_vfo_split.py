"""Replay the Japanese IC-705 1.40 VFO and Split readbacks, entirely in guest RAM."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack, unpack

from tools.decode_705_main import decode_main
from tools.decode_705_main import J140_DAT_SHA as DAT_SHA, J140_MAIN_SHA as MAIN_SHA
from tools.emulate_705 import call, machine


RADIO_ADDRESS = 0x203EAAD6
CIV_BYTE, CIV_DISPATCH = 0x20029F94, 0x2001B988
MAILBOX, FRAME_PENDING = 0x20388673, 0x20389660
VFO, ACTIVE_HZ = 0x203EBC2E, 0x20380714
SELECT_VFO, SET_SPLIT = (0x2001DEA8, 0x2001DEBC), 0x20103914
TX_CANDIDATE, PANEL_SUBFREQ = 0x201031DC, 0x20094AB0
PANEL_FIELD = 0x204BAB5C + 0x5D
FREQ_HZ = (145_900_000, 436_850_000)
QUERIES = ("03", "25 00", "25 01", "0f", "1c 00", "1c 03")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def frequency(payload):
    digits = payload[::-1].hex()
    require(len(payload) == 5 and digits.isdigit(), f"unexpected CI-V frequency: {payload.hex()}")
    return int(digits)


def seed_vfos(cpu, pair=FREQ_HZ):
    cpu.mem_write(RADIO_ADDRESS, b"\xa4")
    # Backing VFO pair, copied and ordered by the original select routine.
    for address, hz in zip((VFO + 79, VFO + 115), pair, strict=True):
        cpu.mem_write(address, pack("<I", hz))


def exchange_in_guest(cpu, payload, address=0xA4, *, invoke=None):
    """Pass bytes between stock ARM routines and their RAM mailbox in Unicorn."""
    def read(addr, length):
        return bytes(cpu.mem_read(addr, length))

    if invoke is None:
        def invoke(entry, *args):
            return call(cpu, entry, *args)
    request = bytes((0xFE, 0xFE, address, 0xE0)) + payload + b"\xfd"
    # Clear the per-frame completion bit between calls (normally done by the transport task).
    require(read(MAILBOX + 1, 1) == b"\0", "stale request in guest mailbox")
    cpu.mem_write(FRAME_PENDING, b"\0")
    cpu.mem_write(MAILBOX + 0x82, b"\0")
    cpu.mem_write(MAILBOX + 0x83, bytes(128))
    cpu.mem_write(MAILBOX + 0x103, b"\0")
    ready = [invoke(CIV_BYTE, 0, byte) for byte in request]
    accepted = int(address == 0xA4)
    require(ready == [0] * (len(request) - 1) + [accepted],
            f"unexpected receive flags for {request.hex(' ')}")
    invoke(CIV_DISPATCH)
    require(read(MAILBOX + 0x103, 1)[0] == accepted, "unexpected response flag")
    raw = read(MAILBOX + 0x83, 128)
    if accepted:
        require(b"\xfd" in raw and raw.startswith(b"\xe0\xa4"),
                f"unexpected reply to guest payload {payload.hex(' ')}")
        response = raw[:raw.index(0xFD) + 1]
    else:
        require(not any(raw), "rejected frame wrote a response")
        response = b""
    return response, {"request": request.hex(" "), "reply_body": response.hex(" ")}


def read_in_guest(cpu, command, address=0xA4):
    require(command in QUERIES, f"only read queries are modeled: {command}")
    payload = bytes.fromhex(command)
    response, frame = exchange_in_guest(cpu, payload, address)
    require(not response or response[2:].startswith(payload), f"unexpected reply for {command}")
    return response[2 + len(payload):-1], frame


def replay(main):
    cpu = machine(main)
    seed_vfos(cpu)

    def read(address, length):
        return bytes(cpu.mem_read(address, length))

    def query(command, address=0xA4):
        return read_in_guest(cpu, command, address)

    _, wrong_address = query("03", address=0xA5)
    states = []
    for selected, split in ((0, 0), (0, 1), (1, 1), (1, 0), (0, 0)):
        # Call stock routines against synthetic RAM; no device transport or PTT.
        require(call(cpu, SELECT_VFO[selected]) == 0, "stock VFO selection did not succeed")
        call(cpu, SET_SPLIT, 0, split)
        require((read(VFO + 74, 1)[0] & 4) == selected << 2, "stock A/B marker mismatch")
        active, alternate = FREQ_HZ[selected], FREQ_HZ[1 - selected]
        cache_hz, = unpack("<I", read(ACTIVE_HZ, 4))
        slots = [unpack("<I", read(VFO + offset, 4))[0] for offset in (1, 37)]
        require(cache_hz == active and slots == [active, alternate], "stock VFO order/cache mismatch")

        replies = {command: query(command) for command in QUERIES}
        operating_hz, selected_hz, unselected_hz, tx_hz = (
            frequency(replies[command][0]) for command in ("03", "25 00", "25 01", "1c 03"))
        require(operating_hz == selected_hz == active and unselected_hz == alternate,
                "operating or VFO frequency mismatch")
        require(replies["0f"][0] == bytes((split,)), "Split readback mismatch")
        require(replies["1c 00"][0] == b"\0", "guest is no longer in receive state")
        require(tx_hz == call(cpu, TX_CANDIDATE, 0) == (alternate if split else active),
                "TX frequency readback mismatch")

        call(cpu, PANEL_SUBFREQ, 0)
        panel_mode, *panel_bytes = read(PANEL_FIELD, 12)
        panel_text = bytes(panel_bytes).decode("ascii").strip()
        require(panel_mode == split, "stock panel did not toggle the sub-frequency field")
        require((panel_text.replace(".", "") + "0" == str(tx_hz)) if split else not panel_text,
                "stock panel sub-frequency does not match the CI-V reply")
        states.append({"selected": "AB"[selected], "split": bool(split), "receiving": True,
                       "rx_hz": operating_hz, "unselected_hz": unselected_hz, "tx_candidate_hz": tx_hz,
                       "stock_panel_subfrequency": panel_text,
                       "civ": {command: frame for command, (_, frame) in replies.items()}})
    require(states[0] == states[-1], "selecting A again did not restore the initial readbacks")
    return {"fixture_hz": dict(zip("AB", FREQ_HZ)), "states": states, "wrong_destination": wrong_address,
            "reply_boundary": "guest mailbox before the transport adds FE FE"}


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("output", type=Path, help="JSON report path")
    args = parser.parse_args()
    dat = args.dat.read_bytes()
    require(sha256(dat).hexdigest() == DAT_SHA, "expected the original Japanese IC-705 1.40 DAT")
    _, main, manifest = decode_main(dat)
    require(manifest["main"]["sha256"] == MAIN_SHA, "unexpected J140 main program")
    result = {"dat_sha256": DAT_SHA, "main_sha256": MAIN_SHA, **replay(bytes(main))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"J140 VFO/Split replay passed: {args.output}")


if __name__ == "__main__":
    cli()
