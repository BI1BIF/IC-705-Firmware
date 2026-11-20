"""Compare RX3/RX4 with the same WSJT-X FT8 waveforms and native audio path."""

import json
import random
import shutil
import subprocess
import wave
from array import array
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from struct import pack
from unittest.mock import patch

from tools import render_705_stock_row as renderer
from tools.build_705_ftx_rx import OUT
from tools.replay_705_ftx_live import ROOT, decode_main
from tools.replay_705_gps_inputs import GPS_INIT, GPS_MODE
from tools.replay_705_settings import SettingsGuest
from tools.verify_705_ftx_rx import (
    BASE,
    call,
    fixture,
    gps,
    load,
    menu_init,
    published_rows,
    recording,
    session_heap,
    symbols,
    val,
)


def run(folder, paths, mandatory_only=False, budget=None, delayed=False, *, exchange=None, ft4=False, pause_worker=False):
    dat = (folder / "bench-rx.dat").read_bytes()
    image = bytes(decode_main(dat)[1])
    sy = symbols(folder / "rx.elf")
    stock = load((ROOT / "firmware/705J140.dat").read_bytes())
    with patch.object(renderer, "HEAP_START", 0x20700000):
        panel = SettingsGuest(stock, front_panel=True)
    c = panel.cpu
    c.mem_write(BASE, image)
    c.ctl_remove_cache(BASE, BASE + len(image))
    menu_init(c, image)
    if "ft_data_ready" in sy:
        from tools.verify_705_ftx_rx import map_atlas
        map_atlas(c,dat);assert call(c,sy["ft_data_ready"])
    feed = fixture(c)
    # Exercise the worker independently of panel timing. The panel test covers
    # the real selector, shared RTX dispatch and native input routing.
    c.mem_write(0x203E2128, bytes([16, 1]))
    c.mem_write(sy["state"], pack("<I", 1))
    if ft4: c.mem_write(sy["ftx_ft4"],pack("<I",1))
    with session_heap(panel.surface, budget, 2 if mandatory_only else None) as requests:
        call(c, sy["ftx_step"], instruction_limit=0, timeout_us=30000000)
    assert val(c, sy["state"]) == 2 and (not mandatory_only or len(requests) > 3)
    c.mem_write(GPS_MODE, bytes([1]))
    call(c, GPS_INIT)
    count=60000 if ft4 else 120000
    first_reply_ms=None
    if exchange:
        # Replay the receive state immediately after a completed A transmission.
        for name in ("sequence_on","has_sent","ft_page"):
            c.mem_write(sy[name],pack("<I",1))
    empty = bytes(2*count)
    waves = [recording(p,count) if p else empty for p in paths]
    previous = None
    found = {}
    reports = {}
    assisted = {}
    for base in range(-48000, count * len(waves) + 16002, 576):
        end = min(base + 576, count * len(waves) + 16002)
        pos = base
        while pos < end:
            slot, offset = divmod(pos, count)
            if slot != previous:
                c.mem_write(0x180000, waves[slot] if 0 <= slot < len(waves) else empty)
                previous = slot
            sec = pos // 8000
            if pos == ((sec * 8000 + 5) // 6) * 6:
                gps(c, sec)
            stop = min(end, (slot + 1) * count, ((sec + 1) * 8000 + 5) // 6 * 6)
            call(c, feed, 0x180000 + offset * 2, (stop - pos) // 6, instruction_limit=0)
            pos = stop
        # One two-second interruption exceeds the queue; complete later slots
        # must still publish once the original worker can run again.
        if pause_worker and count <= base < count + 16000:
            continue
        # Compare identical late worker wakes while the DMA producer keeps running.
        if (
            delayed
            and base >= 120000
            and ((base + 48000) // 576 % 2 or 12000 <= base % 120000 < 17800)
        ):
            continue
        call(c, sy["ftx_step"], instruction_limit=0, timeout_us=30000000)
        m = val(c, sy["middle"])
        if m & 4:
            b = val(c, sy["ftx_memory"]) + 32768 + (m & 3) * (8 + 48 * 44)
            slot = val(c, b + 4) % (86400*8000//count)
            messages, raw = published_rows(c, b, legacy=folder != OUT)
            if exchange and slot==1 and exchange in messages and first_reply_ms is None:
                first_reply_ms=(end-2*count)/8
            reports[slot] = messages
            assisted[slot] = [
                messages[i]
                for i in range(len(messages))
                if folder == OUT and raw[i][35] & 1
            ]
            found[slot] = "CQ K1ABC FN42" in messages
    assert delayed or pause_worker or (
        set(found) == set(range(len(waves)))
        and not val(c, sy["overruns"])
        and not val(c, sy["gaps"])
    ), found
    return {
        "dat_sha256": sha256(dat).hexdigest(),
        "first_reply_ms_from_next_edge": first_reply_ms,
        "decoded": [found.get(i, False) for i in range(len(waves))],
        "overruns": val(c, sy["overruns"]),
        "gaps": val(c, sy["gaps"]),
        "messages": reports,
        "assisted": assisted,
    }


if __name__ == "__main__":
    # WSJT-X ft8sim "CQ K1ABC FN42" 1500 0 0 DEL 3 -SNR.
    # The two directories use DEL=0 and DEL=1, respectively.
    generator = ["ft8sim"] if shutil.which("ft8sim") else ["wsl", "-e", "ft8sim"]
    for name, delay in (("awgn", 0), ("weak", 1)):
        for level in (16, 18, 20, 22, 24):
            folder = OUT / name / str(level)
            if len(list(folder.glob("*.wav"))) == 3:
                continue
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / "generated.txt").open("w") as log:
                subprocess.run(
                    [
                        *generator,
                        "CQ K1ABC FN42",
                        "1500",
                        "0",
                        "0",
                        str(delay),
                        "3",
                        str(-level),
                    ],
                    cwd=folder,
                    stdout=log,
                    check=True,
                )
    inputs = sorted((OUT / "awgn").glob("*/*.wav")) + sorted(
        (OUT / "weak").glob("*/*.wav")
    )
    assert len(inputs) == 30
    noise = OUT / "noise-control.wav"
    rng = random.Random(705)
    with wave.open(str(noise), "wb") as wav:
        wav.setparams((1, 2, 12000, 0, "NONE", "not compressed"))
        wav.writeframes(
            array("h", (round(rng.gauss(0, 100)) for _ in range(180000))).tobytes()
        )
    inputs.append(noise)
    result = {
        "samples": [
            {
                "file": str(p.relative_to(OUT)),
                "db": -int(p.parent.name) if p != noise else None,
                "sha256": sha256(p.read_bytes()).hexdigest(),
            }
            for p in inputs
        ]
    }
    with ProcessPoolExecutor(max_workers=3) as pool:
        builds = {
            name: pool.submit(run, OUT if name=="tx1" else OUT.parent / ("j140-ftx-" + name), inputs)
            for name in ("rx4", "tx1")
        }
        builds["tx1_compact"] = pool.submit(run, OUT, inputs, False, 210000)
        for name, job in builds.items():
            result[name] = job.result()
            assert result[name]["messages"][len(inputs) - 1] == []
            print(name, result[name]["decoded"], flush=True)
    for mode in ("tx1", "tx1_compact"):
        for rows in result[mode]["messages"].values():
            assert all(row == "CQ K1ABC FN42" for row in rows), rows
    (OUT / "weak.json").write_text(json.dumps(result, indent=2))
