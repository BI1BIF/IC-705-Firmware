"""Check the CW lab's memory budget and the untouched J140 startup mappings."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack, unpack_from
from tempfile import TemporaryDirectory

from tools.attach_705_cw_replay import STATE_RESERVATION, WORKER_STACK_REQUEST
from tools.emulate_705 import BASE, arm, machine, uc
from tools.probe_705_cw_pcm import TEST_STATE
from tools.probe_705_cw_session import RTX_CODE, RTX_MEMORY, SCOPE_CANVAS, SCOPE_H, SCOPE_MEMORY, SCOPE_W, build
from tools.render_705_display import load
from tools.render_705_stock_row import require


RESET, TABLE_READY = BASE + 0x60, BASE + 0xBC
ENABLE, ENABLED = 0x20125520, 0x20125568
READ_WORD, MOV_TIMER_ID = 0x20125230, 0x201254F0
SENTINEL = 0x78563412


def probe(main, data_endpoints=()):
    cpu = machine(main)
    cpu.mem_map(0xFCFE1000, 4096)  # Only the reset routine's AXI register accesses.
    for address in (TEST_STATE, RTX_CODE, SCOPE_CANVAS):
        cpu.mem_map(address, 4096)
        cpu.mem_write(address, pack("<I", SENTINEL if address != RTX_CODE else 0xE3A0002A))

    def cpr(crn, opc2=0):
        return cpu.cpr_read(15, 0, crn, 0, opc2, 0, False)

    def reg(name):
        return cpu.reg_read(getattr(arm, "UC_ARM_REG_" + name))

    def run(begin, end):
        cpu.emu_start(begin, end, count=1_000_000)
        require(reg("PC") == end, f"startup stopped at {reg('PC'):#x}, expected {end:#x}")

    run(RESET, TABLE_READY)
    ttbr0, ttbcr, dacr = cpr(2), cpr(2, 2), cpr(3)
    require(ttbr0 == 0x20000009 and ttbcr == 0 and dacr == 1 and not cpr(1) & 1,
            "unexpected original ARM translation mode")
    table = bytes(cpu.mem_read(ttbr0 & ~0x3FFF, 0x4000))
    addresses = (0x18000000, BASE, 0x20800000, 0x20900000, 0x20A00000, 0x60000000,
                 TEST_STATE, RTX_CODE, SCOPE_CANVAS, *data_endpoints)
    entries = {hex(a): hex(unpack_from("<I", table, (a >> 20)*4)[0]) for a in addresses}
    require(all(int(entries[hex(a)], 16) & 3 == 0 for a in (TEST_STATE, RTX_CODE, SCOPE_CANVAS)),
            "stock table did not leave the lab window unmapped")
    exceptions = []

    def trap(c, number, _):
        exceptions.append(number)
        c.emu_stop()

    cpu.hook_add(uc.UC_HOOK_INTR, trap)

    def check(address, execute, expected=None, fault=None):
        exceptions.clear()
        if execute:
            start = address
        else:
            cpu.reg_write(arm.UC_ARM_REG_R0, address)
            start = READ_WORD
        cpu.emu_start(start, start+4, count=1)
        if fault is not None:
            require(exceptions == [fault], f"{address:#x} did not raise the expected abort")
            return dict(address=hex(address), kind="fetch" if execute else "read", arm_exception=fault)
        found = reg("R0" if execute else "R3")
        require(not exceptions and reg("PC") == start+4 and found == expected, f"control failed at {address:#x}")
        return dict(address=hex(address), kind="fetch" if execute else "read", value=hex(found))

    controls = [(BASE, False, unpack_from("<I", main)[0]), (MOV_TIMER_ID, True, 134)]
    extension = [(TEST_STATE, False, SENTINEL), (RTX_CODE, True, 42), (SCOPE_CANVAS, False, SENTINEL)]
    flat = [check(*item) for item in controls + extension]
    run(ENABLE, ENABLED)
    require(cpr(1) & 1 and bytes(cpu.mem_read(ttbr0 & ~0x3FFF, 0x4000)) == table,
            "the CPU did not enable the unmodified startup table")
    translated = [check(*item) for item in controls]
    translated.extend(check(a, execute, fault=3 if execute else 4) for a, execute, _ in extension)
    for address in data_endpoints:
        # These belong to allocators which are not active in this reset-only guest.
        require(not address & 3 and unpack_from("<I", main, 0x20125248-BASE)[0] == 0xE5801000,
                "unexpected data address or original store instruction")
        before = bytes(cpu.mem_read(address, 4))
        exceptions.clear()
        cpu.reg_write(arm.UC_ARM_REG_R0, address)
        cpu.reg_write(arm.UC_ARM_REG_R1, SENTINEL)
        run(0x20125248, 0x2012524C)
        require(not exceptions and bytes(cpu.mem_read(address, 4)) == pack("<I", SENTINEL),
                "original ARM store did not reach the expected physical address")
        translated.append(dict(check(address, False, SENTINEL), kind="write/read", physical_address=hex(address)))
        cpu.mem_write(address, before)
    return dict(ttbr0=hex(ttbr0), ttbcr=ttbcr, dacr=hex(dacr), sctlr_enabled=hex(cpr(1)),
                stock_table_sha256=sha256(table).hexdigest(), first_level_entries=entries,
                mmu_off=flat, stock_mmu_on=translated)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--worker-stack-report", type=Path, help="cross-check the measured RTX stack endpoints")
    parser.add_argument("--canvas-report", type=Path, help="cross-check the measured stock canvas endpoints")
    parser.add_argument("--state-report", type=Path, help="cross-check the measured stock session endpoints")
    args = parser.parse_args()
    dat = args.dat.read_bytes()
    main_image = load(dat)[0]
    data_endpoints = []
    if args.worker_stack_report:
        audit = json.loads(args.worker_stack_report.read_text(encoding="utf-8"))
        require(audit["stock_main_sha256"] == sha256(main_image).hexdigest(), "stack audit used another main image")
        stack = audit["cw_worker_stack"]
        start, end = int(stack["stack_base"], 16), int(stack["stack_limit"], 16)
        require(end-start == stack["stack_bytes"] == WORKER_STACK_REQUEST and 0x20400000 <= start < end <= 0x20500000,
                "unexpected measured stack range")
        data_endpoints.extend((start, end-4))
    if args.canvas_report:
        from tools.probe_705_canvas_heap import HEAP_FIRST, HEAP_LIMIT
        canvas = json.loads(args.canvas_report.read_text(encoding="utf-8"))
        start, end = int(canvas["canvas"], 16), int(canvas["canvas_end"], 16)
        require(HEAP_FIRST <= start < end <= HEAP_LIMIT and end-start == 2*SCOPE_W*SCOPE_H and
                canvas["heap_matches_control_at_both_home_frames"], "unexpected measured canvas range")
        data_endpoints.extend((start, end-4))
    if args.state_report:
        from tools.probe_705_canvas_heap import HEAP_FIRST, HEAP_LIMIT
        state = json.loads(args.state_report.read_text(encoding="utf-8"))
        start, end = int(state["stock_state"], 16), int(state["stock_state_end"], 16)
        require(HEAP_FIRST <= start < end <= HEAP_LIMIT and end-start == state["state_bytes"] == STATE_RESERVATION and
                not state["old_state_mapped"], "unexpected measured state range")
        data_endpoints.extend((start, end-4))
    result = probe(main_image, data_endpoints)
    with TemporaryDirectory() as tmp:
        code, _, _ = build(Path(tmp), rtx=True, stock_canvas=bool(args.state_report), stock_state=bool(args.state_report))
    # The state reservation includes the RX filter, spectrum history and thread descriptor.
    use = dict(arm_code_and_rodata=len(code), state_reservation=STATE_RESERVATION,
               rgb565_scratch=SCOPE_W*SCOPE_H*2, requested_task_stack=WORKER_STACK_REQUEST)
    result.update(test_only=True, stock_dat_sha256=sha256(dat).hexdigest(),
                  stock_main_sha256=sha256(main_image).hexdigest(), offline_cw_code_sha256=sha256(code).hexdigest(),
                  budget_bytes=use, code_and_data_plus_requested_stack=sum(use.values()),
                  page_rounded_reservations_including_requested_stack=
                  RTX_MEMORY+SCOPE_MEMORY+STATE_RESERVATION+WORKER_STACK_REQUEST)
    if args.state_report:
        result.update(code_variant="stock-state-and-canvas", still_requires_code_address_bytes=len(code),
                      verified_data_allocations_bytes=STATE_RESERVATION+SCOPE_W*SCOPE_H*2+WORKER_STACK_REQUEST)
    require(args.dat.read_bytes() == dat, "original firmware changed during test")
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    with args.evidence.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    print(f"J140 stock MMU: {len(result['stock_mmu_on'])} checks; {args.evidence}")


if __name__ == "__main__":
    main()
