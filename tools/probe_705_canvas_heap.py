"""Audit the stock J140 heap while the cold-start CW renderer owns its canvas."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import unpack

from tools.attach_705_cw_replay import CURRENT, STATE_RESERVATION, STOCK_CANVAS_ALLOCATION, STOCK_CANVAS_OFFSET, UI_HANDLE
from tools.emulate_705 import arm, uc
from tools.probe_705_cw_pcm import TEST_STATE
from tools.probe_705_cw_session import RTX_CODE, RTX_MEMORY, SCOPE_H, SCOPE_W
from tools.render_705_stock_row import require


HEAP_FIRST, HEAP_LIMIT, FREE_HEAD = 0x20750A44, 0x20830A3C, 0x20381F2C
CANVAS_BYTES = 2*SCOPE_W*SCOPE_H
CANVAS_REQUEST = CANVAS_BYTES+24


class CanvasAudit:
    def __init__(self, cpu, *, stock):
        self.cpu = cpu
        self.stock = stock
        self.snapshots, self.calls = {}, []
        self.base = self.raw = self.blits = 0
        self.state = None
        self.code_range = (RTX_CODE, RTX_CODE+RTX_MEMORY)
        if stock:
            for address in (0x20127A28, 0x20127A78, 0x20263B12):
                cpu.hook_add(uc.UC_HOOK_CODE, self.observe, begin=address, end=address)

    def word(self, addr):
        return unpack("<I", self.cpu.mem_read(addr, 4))[0]

    def free_list(self):
        blocks = []
        node, previous_end = self.word(FREE_HEAD), HEAP_FIRST
        while node:
            require(previous_end <= node < HEAP_LIMIT and node % 8 == HEAP_FIRST % 8,
                    f"invalid or out-of-order stock heap node {node:#x}")
            size, following = unpack("<2I", self.cpu.mem_read(node, 8))
            require(size >= 8 and size % 8 == 0 and node+size <= HEAP_LIMIT,
                    f"invalid stock heap block {node:#x}: {size}")
            blocks.append((node, size))
            previous_end, node = node+size, following
        return blocks

    def observe(self, cpu, pc, *_):
        lr = cpu.reg_read(arm.UC_ARM_REG_LR)
        start, end = self.code_range
        if self.state is None or not start <= (lr & ~1) < end:
            return
        r0 = cpu.reg_read(arm.UC_ARM_REG_R0)
        owner = self.word(CURRENT)
        require(owner == self.word(UI_HANDLE), "CW canvas must belong to the stock UI thread")
        if pc != 0x20263B12:
            self.calls.append(("allocate" if pc == 0x20127A28 else "release", r0, owner))
            return
        base = self.word(self.state+STOCK_CANVAS_OFFSET)
        if base and r0 == base+2*SCOPE_W*(SCOPE_H-1):
            require(cpu.reg_read(arm.UC_ARM_REG_R1) == (-2*SCOPE_W & 0xffffffff), "unexpected CW blit pitch")
            self.blits += 1

    def capture(self, label, *, drawing=False):
        free = self.free_list()
        base = self.word(self.state+STOCK_CANVAS_OFFSET) if self.stock and self.state is not None else 0
        raw = self.word(self.state+STOCK_CANVAS_ALLOCATION) if self.stock and self.state is not None else 0
        require(bool(base) == bool(raw) == (self.stock and drawing), f"CW canvas ownership contradicts {label}")
        if base:
            used = self.word(raw-4)
            require((not self.base or (self.base, self.raw) == (base, raw)) and
                    HEAP_FIRST <= raw-4 < raw <= base <= raw+24 and raw+CANVAS_REQUEST <= HEAP_LIMIT and
                    (base+2*SCOPE_W*(SCOPE_H-1)) % 32 == 0 and used == ((CANVAS_REQUEST+11) & ~7) and
                    all(b+n <= raw-4 or b >= raw-4+used for b, n in free),
                    "CW canvas overlapped free memory or moved between frames")
            self.base, self.raw = base, raw
        self.snapshots[label] = (free, base)

    def state_allocated(self, state):
        before = self.snapshots["stock-home-before-cw"][0]
        after = self.free_list()
        allocated = (STATE_RESERVATION+11) & ~7
        header = state-4
        require(HEAP_FIRST <= header < state+STATE_RESERVATION <= HEAP_LIMIT and self.word(header) == allocated and
                sum(n for _, n in before)-sum(n for _, n in after) == allocated and
                any(b <= header and b+n >= header+allocated for b, n in before) and
                all(b+n <= header or b >= header+allocated for b, n in after), "unexpected original state allocation")
        self.state = state

    def code_allocated(self, base, size, request, before):
        allocated = (request+11) & ~7
        header = base-4
        after = self.free_list()
        require(HEAP_FIRST <= header < base+size <= HEAP_LIMIT and self.word(header) == allocated and
                sum(n for _, n in before)-sum(n for _, n in after) == allocated and
                any(b <= header and b+n >= header+allocated for b, n in before) and
                all(b+n <= header or b >= header+allocated for b, n in after),
                "unexpected original allocation for offline test code")
        self.code_range = (base, base+size)
        return allocated

    def evidence(self, copies):
        before = self.snapshots["stock-home-before-cw"][0]
        after = self.snapshots["stock-home-after-exit"][0]
        source = hex(self.base+2*SCOPE_W*(SCOPE_H-1))
        submitted = [c for c in copies if c["source"] == source and (c["width"], c["height"]) == (SCOPE_W, SCOPE_H)]
        returned = any(b <= self.raw-4 and b+n >= self.raw+CANVAS_REQUEST for b, n in after)
        require(not self.stock or [(op, val) for op, val, _ in self.calls] ==
                [("allocate", CANVAS_REQUEST), ("release", self.raw)] and self.blits == len(submitted) >= 2 and
                returned, f"stock CW canvas lifecycle: {self.calls=} base={self.base:#x} "
                f"{self.blits=} submitted={len(submitted)} {returned=} "
                f"scope copies={[c for c in copies if (c['width'], c['height']) == (SCOPE_W, SCOPE_H)]}")
        return dict(stock_canvas=self.stock, requested_bytes=CANVAS_REQUEST if self.stock else 0, canvas=hex(self.base),
                    **(dict(raw_allocation=hex(self.raw), alignment_padding=self.base-self.raw) if self.stock else {}),
                    **(dict(stock_state=hex(self.state), state_bytes=STATE_RESERVATION,
                            stock_state_end=hex(self.state+STATE_RESERVATION)) if self.state not in (None, TEST_STATE) else {}),
                    canvas_end=hex(self.base+CANVAS_BYTES) if self.stock else None, blits=self.blits,
                    copied_pixel_sha256=[c["sha256"] for c in submitted],
                    original_calls=[[op, val if op == "allocate" else hex(val), hex(tcb)] for op, val, tcb in self.calls],
                    free_list_restored_exactly=before == after, snapshots={label: dict(
                        free_bytes=sum(n for _, n in free), largest_block=max((n for _, n in free), default=0),
                        free_list=[[hex(b), n] for b, n in free], canvas=hex(base))
                        for label, (free, base) in self.snapshots.items()})


def startup_report(folder):
    raw = (folder / "startup-current-format.json").read_bytes()
    return json.loads(raw), sha256(raw).hexdigest()


def panel(report):
    surfaces = report["controls"][0]["eeprom"]["format_record"]["handoff"]["ui"]["display"]["openvg"]["surfaces"]
    return surfaces["startup_resume"]["main_loop_resume"]["startup_input"]


def panel_report(folder):
    report, digest = startup_report(folder)
    return panel(report), digest


def compare(stock_folder, fixed_folder):
    stock, stock_report = panel_report(stock_folder)
    fixed, fixed_report = panel_report(fixed_folder)
    actual, control = (x["cw_stock_canvas"] for x in (stock, fixed))
    requested = actual["requested_bytes"]
    require(actual["stock_canvas"] and not control["stock_canvas"] and requested in (CANVAS_BYTES, CANVAS_REQUEST) and
            actual["blits"] == len(actual["copied_pixel_sha256"]) >= 2 and len(set(actual["copied_pixel_sha256"])) >= 2,
            "reports do not show different stock-canvas copies and a fixed-canvas control")
    live = ("first-cw-frame", "cw-receive")
    for label, frame in actual["snapshots"].items():
        reference = control["snapshots"][label]
        if label in live:
            require(reference["free_bytes"]-frame["free_bytes"] == ((requested+11) & ~7),
                    f"stock canvas had unexpected allocator overhead at {label}")
        else:
            require(frame["free_list"] == reference["free_list"], f"heap differs from control at {label}")

    frames = [row["sha256"] for row in stock["scanout"]]
    require(len(frames) >= 5 and frames == [row["sha256"] for row in fixed["scanout"]] and frames[-1] == frames[4],
            "LCD frames changed from the fixed-canvas control or HOME was not restored")
    voice = (stock["cw_receive"], fixed["cw_receive"])
    fields = ("fed", "shown_text", "pcm_sha256", "dma_groups", "green_text_pixels")
    require(voice[0]["shown_text"] == "CQ" and all(voice[0][k] == voice[1][k] for k in fields)
            and not stock["persistent_writes"] and not fixed["persistent_writes"], "receive or persistent writes differ")
    pngs = sorted(p.name for p in stock_folder.glob("*.png"))
    require({"boot-cw.png", "boot-cw-decoded.png", "boot-home-after-exit.png"} <= set(pngs) and
            set(pngs) == {p.name for p in fixed_folder.glob("*.png")} and
            all((stock_folder / p).read_bytes() == (fixed_folder / p).read_bytes() for p in pngs),
            "PNG exports differed")
    return dict(stock_report_sha256=stock_report, fixed_report_sha256=fixed_report, canvas=actual["canvas"],
                canvas_end=actual["canvas_end"], bytes_with_header=(requested+11) & ~7,
                submitted_copies=actual["blits"], identical_lcd_frames=len(frames), identical_pngs=pngs,
                receive={k: voice[0][k] for k in fields}, heap_matches_control_at_both_home_frames=True,
                persistent_writes=0)


def compare_state(stock_folder, control_folder):
    stock, stock_report = panel_report(stock_folder)
    control, control_report = panel_report(control_folder)
    actual, baseline = (p["cw_stock_canvas"] for p in (stock, control))
    require(actual["stock_canvas"] and baseline["stock_canvas"] and "stock_state" not in baseline,
            "state comparison requires two stock-canvas runs, one with the original fixed state")
    state = int(actual["stock_state"], 16)
    end = int(actual["stock_state_end"], 16)
    block_bytes = (STATE_RESERVATION+11) & ~7
    require(HEAP_FIRST <= state-4 < end <= HEAP_LIMIT and end-state == actual["state_bytes"] == STATE_RESERVATION and
            not stock["cw_old_state_mapped"], "state allocation or old address check failed")
    for name, frame in actual["snapshots"].items():
        previous = baseline["snapshots"][name]
        require(previous["free_bytes"]-frame["free_bytes"] == (0 if name == "stock-home-before-cw" else block_bytes),
                f"unexpected net heap allocation at {name}")
        if name != "stock-home-before-cw":
            require(all(int(b, 16)+n <= state-4 or int(b, 16) >= state-4+block_bytes for b, n in frame["free_list"]),
                    f"original heap considered the live state free at {name}")
    require(actual["copied_pixel_sha256"] == baseline["copied_pixel_sha256"] and actual["blits"] >= 2,
            "moving state changed the wave or waterfall pixel copies")
    fields = ("fed", "shown_text", "pcm_sha256", "dma_groups", "green_text_pixels")
    receive = {k: stock["cw_receive"][k] for k in fields}
    require(receive["shown_text"] == "CQ" and receive == {k: control["cw_receive"][k] for k in fields} and
            not stock["persistent_writes"] and not control["persistent_writes"], "receive or persistent writes differ")
    frames = [row["sha256"] for row in stock["scanout"]]
    require(len(frames) >= 5 and frames == [row["sha256"] for row in control["scanout"]] and frames[-1] == frames[4],
            "LCD frames changed or HOME was not restored")
    return dict(stock_report_sha256=stock_report, control_report_sha256=control_report,
                stock_state=hex(state), stock_state_end=hex(end), state_bytes=STATE_RESERVATION,
                retained_state_bytes_with_header=block_bytes, old_state_mapped=False,
                curve_copies=actual["blits"], identical_lcd_frames=len(frames), receive=receive, persistent_writes=0)


def compare_mmu(mapped_folder, flat_folder):
    mapped_full, mapped_report = startup_report(mapped_folder)
    flat_full, flat_report = startup_report(flat_folder)
    require(all(mapped_full[k] == flat_full[k] for k in ("dat_sha256", "main_sha256")),
            "the MMU and flat comparisons used different stock firmware")
    mapped, flat = panel(mapped_full), panel(flat_full)
    registrations = mapped_full["controls"][0]["stock_mapping"]
    require("stock_mapping" not in flat_full["controls"][0] and registrations[0]["pc"] == "0x200052a0" and
            not int(registrations[0]["sctlr"], 16) & 1 and int(registrations[-1]["sctlr"], 16) & 1 and
            len({row["l1_sha256"] for row in registrations}) == 1 and
            all(row["ttbr0"] == "0x20000009" for row in registrations),
            "the MMU replay did not enable and retain the stock reset table")
    code = mapped["cw_offline_code"]
    require("cw_offline_code" not in flat and all(int(code[k], 16) & 1 for k in
            ("attachment_sctlr", "exit_sctlr")), "expected original MMU and a flat replay control")
    require(not mapped["cw_old_state_mapped"] and not flat["cw_old_state_mapped"],
            "both controls need the stock state allocation")
    stock = mapped["cw_stock_canvas"]
    ref = flat["cw_stock_canvas"]
    require(stock["stock_canvas"] and ref["stock_canvas"] and
            stock["copied_pixel_sha256"] == ref["copied_pixel_sha256"] and stock["blits"] >= 2,
            "original MMU changed the CW waveform or waterfall")
    for stage, snap in stock["snapshots"].items():
        expected = 0 if stage == "stock-home-before-cw" else code["reserved_with_header"]
        if stage in ("first-cw-frame", "cw-receive"):
            expected += stock["requested_bytes"] - ref["requested_bytes"]
        require(ref["snapshots"][stage]["free_bytes"]-snap["free_bytes"] == expected,
                f"unexpected extra heap use in original address map: {stage}")
    fields = ("fed", "shown_text", "pcm_sha256", "dma_groups", "green_text_pixels")
    receive = {k: mapped["cw_receive"][k] for k in fields}
    require(receive["shown_text"] == "CQ" and receive == {k: flat["cw_receive"][k] for k in fields}
            and not mapped["persistent_writes"] and not flat["persistent_writes"], "receive or persistent writes differ")
    frames = [row["sha256"] for row in mapped["scanout"]]
    require(len(frames) >= 5 and frames == [row["sha256"] for row in flat["scanout"]] and frames[-1] == frames[4],
            "LCD frames changed or HOME was not restored")
    pngs = sorted(p.name for p in mapped_folder.glob("*.png"))
    require({"boot-cw.png", "boot-cw-decoded.png", "boot-home-after-exit.png"} <= set(pngs) and
            set(pngs) == {p.name for p in flat_folder.glob("*.png")} and
            all((mapped_folder / p).read_bytes() == (flat_folder / p).read_bytes() for p in pngs),
            "PNG exports differed")
    return dict(original_mmu_report_sha256=mapped_report, flat_report_sha256=flat_report, offline_code=code,
                table_sha256=registrations[0]["l1_sha256"],
                identical_lcd_frames=len(frames), identical_pngs=pngs, curve_copies=stock["blits"],
                original_canvas=stock["canvas"], raw_canvas_allocation=stock.get("raw_allocation", stock["canvas"]),
                canvas_alignment_padding=stock.get("alignment_padding", 0), original_state=stock["stock_state"], receive=receive,
                persistent_writes=0, firmware_does_not_include_extension=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock", type=Path)
    parser.add_argument("fixed", type=Path)
    parser.add_argument("evidence", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--state", action="store_true", help="compare relocated session state against fixed session state")
    mode.add_argument("--mmu", action="store_true", help="compare the stock mapping against the flat control")
    args = parser.parse_args()
    result = (compare_mmu if args.mmu else compare_state if args.state else compare)(args.stock, args.fixed)
    with args.evidence.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2)+"\n")
    print(f"J140 stock {'state' if args.state else 'canvas'}: {result['identical_lcd_frames']} matching LCD frames; {args.evidence}")


if __name__ == "__main__":
    main()
