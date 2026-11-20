"""Exercise allocator failure, rollback and zero-overlap RX on the two actual DATs."""

import json
from hashlib import sha256
from struct import pack

from tools.build_705_ftx_rx import OUT
from tools.replay_705_ftx_live import LIB, ROOT, decode_main
from tools.verify_705_ftx_rx import (
    BASE,
    SettingsGuest,
    call,
    load,
    session_heap,
    symbols,
    val,
)
from tools.verify_705_ftx_weak import run


def trial(folder):
    dat = (folder / "bench-rx.dat").read_bytes()
    image = bytes(decode_main(dat)[1])
    sy = symbols(folder / "rx.elf")
    p = SettingsGuest(
        load((ROOT / "firmware/705J140.dat").read_bytes()), front_panel=True
    )
    c = p.cpu
    c.mem_write(BASE, image)
    c.ctl_remove_cache(BASE, BASE + len(image))
    if "ft_data_ready" in sy:
        from tools.verify_705_ftx_rx import map_atlas
        map_atlas(c,dat);assert call(c,sy["ft_data_ready"])
    cases = []
    old = folder != OUT
    for mode in (0, 1):
        c.mem_write(sy["ftx_ft4"], pack("<I", mode))
        budgets = (
            [151944 if mode else 280700]
            if old
            else [0, 90000, 120000 if mode else 210000, 151944 if mode else 280700]
        )
        for budget in budgets:
            baseline = dict(p.surface.blocks)
            c.mem_write(sy["state"], pack("<I", 1))
            with session_heap(p.surface, budget) as allocations:
                call(c, sy["ftx_step"], instruction_limit=0, timeout_us=30000000)
            requests = [n for n, _ in allocations]
            state = val(c, sy["state"])
            ptr = call(c, sy["ftx_status"])
            message = bytes(c.mem_read(ptr, 50)).split(b"\0")[0].decode()
            expected = (
                "RX memory unavailable"
                if old
                else "RX spectrum RAM unavailable"
                if budget == 0
                else "RX work RAM unavailable"
                if budget == 90000
                else "Waiting for GPS UTC"
            )
            assert message == expected and state == (
                2 if message.startswith("Waiting") else 4
            ), (message, requests)
            if state == 4:
                assert p.surface.blocks == baseline
            c.mem_write(sy["state"], pack("<I", 3))
            call(c, sy["ftx_step"])
            assert p.surface.blocks == baseline and not val(c, sy["ftx_memory"])
            cases.append(
                {"ft4": mode, "budget": budget, "requests": requests, "status": message}
            )
    return {"dat_sha256": sha256(dat).hexdigest(), "cases": cases}


if __name__ == "__main__":
    report = {"rx3": trial(OUT.parent / "j140-ftx-rx3"), "tx1": trial(OUT)}
    # Even when every optional prefix allocation fails, real input and both
    # overlapping slot boundaries must survive. Pace the bench by ADC groups.
    result = run(OUT, [LIB / "test/wav/websdr_test1.wav"] * 2, mandatory_only=True)
    assert all("CQ IK4LZH JN54" in group for group in result["messages"].values())
    report["zero_prefix_ft8"] = result
    (OUT / "memory.json").write_text(json.dumps(report, indent=2))
    print(report)
    stalled = {}
    for name, folder in (("rx4", OUT.parent / "j140-ftx-rx4"), ("tx1", OUT)):
        replay = run(
            folder, [LIB / "test/wav/websdr_test1.wav"] * 3, budget=280700, delayed=True
        )
        stalled[name] = {k: replay[k] for k in ("dat_sha256", "overruns", "gaps")}
        stalled[name]["rows"] = {
            slot: len(rows) for slot, rows in replay["messages"].items()
        }
    assert stalled["rx4"]["overruns"] and stalled["rx4"]["gaps"]
    assert not stalled["tx1"]["overruns"] and not stalled["tx1"]["gaps"]
    assert list(stalled["tx1"]["rows"].values()) == [13, 13, 13]
    (OUT / "delayed-wakes.json").write_text(json.dumps(stalled, indent=2))

    from tools.verify_705_ftx_rx import LAB
    recovery = {}
    for mode, clip, expected in (
        ("FT8", LIB / "test/wav/websdr_test1.wav", 13),
        ("FT4", LAB.parent / "FT4/busy/000000_000001.wav", 12),
    ):
        trial = run(OUT, [clip]*5, ft4=mode=="FT4", pause_worker=True)
        rows = {slot:len(messages) for slot,messages in trial["messages"].items()}
        assert trial["overruns"] and trial["gaps"]
        assert all(rows.get(slot)==expected for slot in (2,3,4)), rows
        recovery[mode] = {key:trial[key] for key in ("dat_sha256","overruns","gaps")}
        recovery[mode]["rows"] = rows
    (OUT/"worker-recovery.json").write_text(json.dumps(recovery, indent=2))
