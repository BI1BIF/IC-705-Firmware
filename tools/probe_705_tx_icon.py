"""Trace the stock J140 HOME TX marker against emulated transmit inputs."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack

from tools.emulate_705 import call, uc
from tools.probe_705_cw_menu import MODE_UI_A, MODE_VFO_A
from tools.probe_705_cw_pcm import BUILD_REQUEST, DSP_STATUS, DSP_TX, FILTER_REQUEST, feed_dsp_tx
from tools.render_705_display import PAGE, load
from tools.render_705_stock_row import require
from tools.replay_705_ptt_tune import FLAGS, PORT_MODE, PORT_PTT, PTT_INIT, STATUS_STORE, STATUS_TASK, byte
from tools.replay_705_vfo_split import exchange_in_guest, read_in_guest, seed_vfos
from tools.virtual_705_panel import start


ICON_FIELD, ICON_STORE, ICON_DRAW = PAGE+0x28, 0x2009588C, 0x2015AF48
TX_GRAY_FLAGS = 0x203806F5
SPRITES = {1: "0x18ae0d40", 2: "0x18ae2540", 3: "0x18adebc0"}


def probe(images, output):
    guest = start(images)
    cpu = guest.cpu
    seed_vfos(cpu)
    for address in (MODE_UI_A, MODE_VFO_A):
        cpu.mem_write(address, b"\x20")  # CW, as in the original menu replay.
    cpu.mem_map(0xFCFE3000, 4096)
    cpu.mem_write(PORT_MODE, pack("<H", 0x40))
    cpu.mem_write(PORT_PTT, pack("<H", 0x2000))

    def gpio(_cpu, kind, address, size, value, _data):
        expected = ((uc.UC_MEM_READ, PORT_MODE, 2, 0), (uc.UC_MEM_READ, PORT_PTT, 2, 0),
                    (uc.UC_MEM_READ, 0xFCFE3214, 2, 0), (uc.UC_MEM_WRITE, 0xFCFE3114, 4, 0x10000))
        require((kind, address, size, value) in expected, f"unexpected simulated GPIO: {address:#x}")

    cpu.hook_add(uc.UC_HOOK_MEM_READ | uc.UC_HOOK_MEM_WRITE, gpio, begin=0xFCFE3000, end=0xFCFE3FFF)
    call(cpu, PTT_INIT)
    writes, draws, status_writes, stages = [], [], [], {}
    cpu.hook_add(uc.UC_HOOK_CODE, lambda c, *_: writes.append(byte(c, ICON_FIELD)),
                 begin=ICON_STORE+4, end=ICON_STORE+4)
    cpu.hook_add(uc.UC_HOOK_CODE, lambda *_: draws.append(1), begin=ICON_DRAW, end=ICON_DRAW)
    cpu.hook_add(uc.UC_HOOK_CODE, lambda c, *_: status_writes.append(byte(c, FLAGS) >> 7),
                 begin=STATUS_STORE+4, end=STATUS_STORE+4)

    def frame(label, icon, tx, requested=False, dsp=False):
        writes.clear()
        draws.clear()
        labels, png = guest.render()
        require("CW" in labels and writes == [icon] and draws, f"missing stock HOME icon: {label}, {writes}")
        positions = [item for item in guest.surface.image_draws if item["source"] in SPRITES.values()]
        require(any(item["source"] == SPRITES[icon] and item["matrix"][2] == 2 for item in positions),
                f"wrong stock TX sprite: {label}, {positions}")
        readback, = read_in_guest(cpu, "1c 00")[0]
        require((readback, bool(byte(cpu, FLAGS) & 0x20), bool(byte(cpu, DSP_STATUS) & DSP_TX))
                == (tx, requested, dsp), f"unexpected stock transmit state: {label}")
        stages[label] = dict(ui_code=icon, sprite=SPRITES[icon], ci_v_tx=tx, ci_v_request=requested,
                             dsp_tx=dsp, png_sha256=sha256(png).hexdigest())
        (output / f"{label}.png").write_bytes(png)

    def request(down):
        response, _ = exchange_in_guest(cpu, bytes((0x1C, 0, down)))
        require(response[2:-1] == b"\xfb", "stock CI-V request was rejected")

    def publish():
        for routine in (BUILD_REQUEST, FILTER_REQUEST, STATUS_TASK):
            call(cpu, routine)

    frame("01-idle", 1, 0)
    request(True)
    frame("02-request-accepted", 1, 0, requested=True)
    publish()
    frame("03-tx-published", 1, 1, requested=True)
    feed_dsp_tx(cpu, True)
    frame("04-dsp-tx", 2, 1, requested=True, dsp=True)
    request(False)
    frame("05-release-pending", 2, 1, dsp=True)
    publish()
    frame("06-rx-published-dsp-still-on", 2, 0, dsp=True)
    feed_dsp_tx(cpu, False)
    frame("07-dsp-clear", 1, 0)
    flags = byte(cpu, TX_GRAY_FLAGS)
    cpu.mem_write(TX_GRAY_FLAGS, bytes((flags | 0x08,)))  # Isolate one stock branch.
    frame("08-gray-control", 3, 0)
    feed_dsp_tx(cpu, True)
    frame("09-gray-overrides-feedback", 3, 0, dsp=True)
    cpu.mem_write(TX_GRAY_FLAGS, bytes((flags,)))
    frame("10-feedback-still-on", 2, 0, dsp=True)
    for first, second in (("08-gray-control", "09-gray-overrides-feedback"),
                          ("06-rx-published-dsp-still-on", "10-feedback-still-on")):
        require(stages[first]["png_sha256"] == stages[second]["png_sha256"], "TX pixels differed")
    feed_dsp_tx(cpu, False)
    require(status_writes == [1, 0], f"stock status publication differed: {status_writes}")
    return dict(stock_main_sha256=guest.main_hash, status_writes=status_writes, stages=stages)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    result = probe(load(args.dat.read_bytes()), args.output)
    (args.output / "evidence.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(f"J140 TX icon and stock state matched: {args.output}")


if __name__ == "__main__":
    main()
