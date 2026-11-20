"""Replay stock J140 update checks in ARM without using flash hardware."""

import argparse
from hashlib import md5, sha256
import json
from pathlib import Path
from struct import pack, unpack

from tools.decode_705_main import BOOT_SIZE, J140_DAT_SHA, J140_MAIN_SHA, checked_group_a, decode_a_range, decode_main
from tools.emulate_705 import BASE, BOOT, SCRATCH, arm, call, machine, uc


WORKER, READ, WAIT_READ, DECODE_STATE = 0x20069B88, 0x201F2914, 0x201EF558, 0x203803D8
COMPARE_RESULT, SETUP_CALL = 0x20069C78, 0x20069C80
HEADER_CHECK, DIGEST_CHECK, WRITE_STAGE = 0x2006C7A0, 0x2006CDD0, 0x2006DB48
STATUS_SETUP, STATUS_RETURN = 0x2006DA9C, 0x2006DFDC
OPEN, CLOSE, SEEK, PATH_BUFFER = 0x201F2864, 0x201F28BC, 0x201F29C4, 0x203D8824
STOCK_PATH = b"C:\\705J140.dat\0"
BUILDS, PRIOR_BUILD = 0x203E1B30, b"4.51-J00"
MD5_INIT, MD5_FINAL = 0x20099A84, 0x2009A67C
BUFFER, HANDLE, REQUEST = 0x203BD000, 0x705, 0x111
CONTEXT, CHANGED = SCRATCH + 0x200, SCRATCH
FLASH_BOUNDARIES = (SETUP_CALL, 0x20069390, 0x20069304, 0x200691A0)
ARG_REGS = (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def bind_reads(cpu, reads):
    pending, completed = [], []

    def feed(c, *_):
        handle, buf, length, out_count = (c.reg_read(reg) for reg in ARG_REGS)
        require(handle == HANDLE and not pending, "unexpected or overlapping stock SD request")
        try:
            expected_buffer, data = next(reads)
        except StopIteration as err:
            raise ValueError("unplanned stock SD read") from err
        require((buf, length) == (expected_buffer, len(data)), "unexpected stock SD buffer or length")
        pending.append(length)
        c.mem_write(buf, data)
        c.mem_write(out_count, pack("<I", length))
        c.reg_write(ARG_REGS[0], REQUEST)
        c.reg_write(arm.UC_ARM_REG_PC, c.reg_read(arm.UC_ARM_REG_LR))

    def complete(c, *_):
        require((c.reg_read(ARG_REGS[0]), c.reg_read(ARG_REGS[1])) == (REQUEST, 1)
                and len(pending) == 1, "unexpected SD completion request")
        completed.append(pending.pop())
        c.reg_write(ARG_REGS[0], 0)
        c.reg_write(arm.UC_ARM_REG_PC, c.reg_read(arm.UC_ARM_REG_LR))

    cpu.hook_add(uc.UC_HOOK_CODE, feed, begin=READ, end=READ)
    cpu.hook_add(uc.UC_HOOK_CODE, complete, begin=WAIT_READ, end=WAIT_READ)
    return completed


def bind_stock_file(cpu, package, *, rom=lambda pc: pc, path=STOCK_PATH):
    cpu.mem_write(PATH_BUFFER, path)
    pending, positions = [], []
    opened, pos = False, 0

    def sd(c, address, *_):
        nonlocal opened, pos
        address = original[address]
        r0, r1, r2, r3 = (c.reg_read(reg) for reg in ARG_REGS)
        if address == WAIT_READ:
            require(bool(pending) and (r0, r1) == (REQUEST, 1), "unexpected stock SD completion")
            action, *args = pending.pop()
            if action == OPEN:
                opened, pos = True, 0
                handle_out, length_out = args
                c.mem_write(handle_out, pack("<I", HANDLE))
                c.mem_write(length_out, pack("<I", len(package)))
            elif action == CLOSE:
                opened = False
            elif action == SEEK:
                pos, out = args
                c.mem_write(out, pack("<I", pos))
            elif action == READ:
                dest, length, out = args
                c.mem_write(dest, package[pos:pos+length])
                c.mem_write(out, pack("<I", length))
                positions.append((pos, length))
                pos += length
            result = 0
        else:
            require(not pending, "overlapping stock SD request")
            if address == OPEN:
                require(not opened and r0 == PATH_BUFFER and r1 == 0
                        and bytes(c.mem_read(r0, len(path))) == path, "unexpected stock file open")
                args = (r2, r3)
            else:
                require(opened and r0 == HANDLE, "unexpected stock SD handle")
                if address == CLOSE:
                    require(r1 == 0, "unexpected stock file close mode")
                    args = ()
                elif address == SEEK:
                    require(r2 <= 2, "unknown stock seek mode")
                    rel, = unpack("<i", pack("<I", r1))
                    dest = (0, pos, len(package))[r2] + rel
                    require(0 <= dest <= len(package), "stock seek left the original package")
                    args = (dest, r3)
                else:
                    require(0 < r2 <= len(package)-pos, "stock read left the original package")
                    args = (r1, r2, r3)
            pending.append((address, *args))
            result = REQUEST
        c.reg_write(ARG_REGS[0], result)
        c.reg_write(arm.UC_ARM_REG_PC, c.reg_read(arm.UC_ARM_REG_LR))

    original = {rom(pc): pc for pc in (OPEN, CLOSE, SEEK, READ, WAIT_READ)}
    for address in original:
        cpu.hook_add(uc.UC_HOOK_CODE, sd, begin=address, end=address)
    return positions, pending, lambda: opened


def full_preflight(main, package, groups):
    """Run the two stock checking workers against an immutable in-memory SD file."""
    cpu = machine(main)
    cpu.mem_write(BUILDS, PRIOR_BUILD)  # Older build in this fixture; no target device state.
    positions, pending, is_open = bind_stock_file(cpu, package)
    checks, digests = {}, {}

    def header_result(c, address, *_):
        checks[address] = c.reg_read(ARG_REGS[0])

    compare = {0x2006D2D0: "A", 0x2006D500: "B", 0x2006D6C4: "C", 0x2006D890: "D"}

    def digest_result(c, address, *_):
        name = compare[address]
        sp = c.reg_read(arm.UC_ARM_REG_SP)
        calculated = bytes(c.mem_read(sp+124, 16)).hex()
        stored = bytes(c.mem_read(sp+20, 16)).hex()
        require(name not in digests and c.reg_read(ARG_REGS[0]) == 0, f"unexpected stock {name} comparison")
        digests[name] = dict(stock_calculated_md5=calculated, stock_stored_md5=stored,
                             comparison_return=f"0x{address:08X}")

    def halt(_c, address, *_):
        raise ValueError(f"unexpected flash entry in preflight at 0x{address:08X}")

    for address in (0x2006C824, 0x2006CCC4, 0x2006CD98):
        cpu.hook_add(uc.UC_HOOK_CODE, header_result, begin=address, end=address)
    for address in compare:
        cpu.hook_add(uc.UC_HOOK_CODE, digest_result, begin=address, end=address)
    for address in (WRITE_STAGE, STATUS_SETUP, *FLASH_BOUNDARIES):
        cpu.hook_add(uc.UC_HOOK_CODE, halt, begin=address, end=address)

    header = call(cpu, HEADER_CHECK, timeout_us=0, instruction_limit=5_000_000)
    header_reads = positions.copy()
    require(header == 0 and not is_open() and not pending, "stock header checker did not return success")
    require(checks == {0x2006C824: 0, 0x2006CCC4: 1, 0x2006CD98: 0},
            "stock magic/inspection/EOF checks did not match")
    require(header_reads[-1] == (len(package)-2, 2), "stock header worker did not read the EOF marker")
    positions.clear()
    result = call(cpu, DIGEST_CHECK, timeout_us=0, instruction_limit=330_000_000)
    require(result == 0 and not is_open() and not pending and list(digests) == ["A", "C", "D"],
            "stock digest checker did not return success for A/C/D")
    for group in groups:
        name, start, end = group["name"], group["offset"], group["end_exclusive"]
        if name == "B":
            require(group["bytes"] == 0 and not any(offset < start+16 and start < offset+length
                                                   for offset, length in positions),
                    "stock digest stage unexpectedly read the group B record")
            continue
        digest = digests[name]
        expected = [(offset, min(0x8000, end-offset)) for offset in range(start, end, 0x8000)] + [(end, 16)]
        observed = [(offset, length) for offset, length in positions if start <= offset <= end]
        require(observed == expected and digest["stock_calculated_md5"] == digest["stock_stored_md5"]
                == group["stored_md5"], f"stock {name} preflight read or digest mismatched")
        digest.update(group_bytes=end-start, stock_read_chunk_count=len(expected)-1, digest_offset=end)
    return {
        "fixture_prior_build": PRIOR_BUILD.decode("ascii"),
        "header_worker_return": header,
        "header_magic_check": checks[0x2006C824],
        "decoded_inspection_result": checks[0x2006CCC4],
        "stock_tail_marker": package[-2:].hex(),
        "header_worker_sd_reads": header_reads,
        "digest_worker_return": result,
        "group_digests": digests,
        "empty_group_b_record_read_by_digest_worker": False,
        "write_stage_entered": False,
    }


def compare_pc_image(main, stock, pc_image):
    """Compare file contents at the original header checker, without running SD menus or update writers."""
    require(pc_image.startswith(b"PK\x03\x04"), "expected the existing PC-only archive")
    result = {}

    def forbid(_cpu, address, *_):
        raise ValueError(f"unexpected digest or write path during header test: {address:#x}")

    for name, data in (("official_dat", stock), ("pc_only_image", pc_image)):
        cpu = machine(main)
        # The same virtual version record is used for both inputs.
        cpu.mem_write(BUILDS, stock[4:12])
        reads, pending, is_open = bind_stock_file(cpu, data)
        for address in (DIGEST_CHECK, WRITE_STAGE, STATUS_SETUP, *FLASH_BOUNDARIES):
            cpu.hook_add(uc.UC_HOOK_CODE, forbid, begin=address, end=address)
        returned = call(cpu, HEADER_CHECK, timeout_us=0, instruction_limit=5_000_000)
        require(not pending and not is_open(), "stock header check did not close its fixture file")
        if name == "official_dat":
            require(returned == 0 and reads[-1] == (len(data)-2, 2), "official J140 header control did not pass")
        else:
            require(returned == 0xFFFFFFF2 and reads == [(0, 4)], "PC archive was not rejected at the format check")
        result[name] = dict(sha256=sha256(data).hexdigest(), header_result=hex(returned),
                            read_ranges=reads, file_closed=True)
    return dict(stock_main_sha256=sha256(main).hexdigest(), virtual_build=stock[4:12].decode("ascii"),
                cases=result, nor_mapped=False,
                scope="Original header checker with a virtual file handle; no filename selection, digest stage or writes.")


def dispatcher_boundary(main, package):
    """Enter the isolated stock dispatcher; stop before it tries to configure NOR."""
    cpu = machine(main)  # RAM only: no NOR, controller MMIO, or real device I/O.
    positions, pending, is_open = bind_stock_file(cpu, package)
    stops = []

    def halt(c, address, *_):
        stops.append((address, c.reg_read(arm.UC_ARM_REG_LR)))
        c.emu_stop()

    for address in (STATUS_SETUP, 0x20069AEC, 0x20069D10, *FLASH_BOUNDARIES):
        cpu.hook_add(uc.UC_HOOK_CODE, halt, begin=address, end=address)
    try:
        call(cpu, WRITE_STAGE, timeout_us=0, instruction_limit=10_000_000)
    except ValueError:
        if stops != [(STATUS_SETUP, STATUS_RETURN)] or cpu.reg_read(arm.UC_ARM_REG_PC) != STATUS_SETUP:
            raise
    else:
        raise ValueError("stock dispatcher returned without stopping before NOR configuration")
    expected_reads = [(offset, 4) for offset in range(0x38, 0x64, 4)] + [(0x9C0064, 16), (0x64, 0x4F10)]
    require(is_open() and not pending and positions == expected_reads,
            "stock dispatcher SD reads differed from the offline fixture")
    return {
        "stock_package_sha256": J140_DAT_SHA,
        "stock_main_sha256": J140_MAIN_SHA,
        "stock_dispatcher": f"0x{WRITE_STAGE:08X}",
        "stock_sd_reads": [{"offset": f"0x{pos:X}", "length": length} for pos, length in positions],
        "stop_before_instruction_at": f"0x{STATUS_SETUP:08X}",
        "caller_return_address": f"0x{STATUS_RETURN:08X}",
        "nor_and_controller_mapped": False,
        "limit": "Isolated dispatcher only. No menu, NOR configuration, writes, boot or device access.",
    }


def first_write_intent(main, package, bootstrap, group_a):
    """Observe the original A-group dispatcher with immutable input and read-only NOR."""
    initial, tail = 0x600000, 0xC00000
    selector, marker = 0xBF0000, bootstrap[0x47E8:0x47F8]
    layout_flag, read_marker, flag_stored = 0x2038089D, 0x2010495C, 0x20104984
    incoming_boot_id, marker_worker, digest_compared = BUFFER+0x4F00, 0x20069AEC, 0x2006E150
    start = group_a["offset"] + BOOT_SIZE
    data = bootstrap + bytes(decode_a_range(package, start, group_a["end_exclusive"]-start, bootstrap[-1]))
    require(len(data) == 0x9C0000 and marker == bootstrap[0x4F00:0x4F10] ==
            main[0x2006E2FC-BASE:0x2006E30C-BASE], "stock A length or boot identifier differs")
    cases = (
        ("first-copy-selected", False, None, None),
        ("second-copy-selected", True, None, None),
        ("different-bootstrap", True, 0, 0),
        ("different-first-copy", True, BOOT_SIZE, BOOT_SIZE),
        ("different-second-copy", False, initial, initial),
        ("different-shared-tail", True, tail, tail),
        ("different-active-first-copy", False, BOOT_SIZE, None),
        ("different-active-second-copy", True, initial, None),
    )
    results = []
    for name, marked, difference, expected in cases:
        stock = bytearray(b"\xff" * 0x1000000)
        stock[:initial] = data[:initial]
        stock[initial:selector] = data[BOOT_SIZE:initial]
        stock[tail:tail+len(data)-initial] = data[initial:]
        if marked:
            stock[selector:selector+len(marker)] = marker
        if difference is not None:
            stock[difference] ^= 1
        cpu = machine(main)
        cpu.mem_map(BOOT, len(stock), uc.UC_PROT_READ)
        cpu.mem_write(BOOT, bytes(stock))
        cpu.mem_write(incoming_boot_id, b"\xff"*16)  # Prove the identifier is supplied by the package read.
        cpu.mem_write(DECODE_STATE+2, bytes((sum(package[4:12]) & 255,)))  # Same SD preflight state.
        # Run the stock comparison that reads NOR and stores its update layout flag.
        cpu.reg_write(arm.UC_ARM_REG_CPSR, 0x1F)
        cpu.reg_write(arm.UC_ARM_REG_SP, SCRATCH-0x200)
        cpu.reg_write(arm.UC_ARM_REG_R4, layout_flag-1)
        cpu.emu_start(read_marker, flag_stored, count=1000)
        require(cpu.reg_read(arm.UC_ARM_REG_PC) == flag_stored and
                cpu.mem_read(layout_flag, 1)[0] == int(not marked), "stock layout flag disagreed with NOR marker")

        reads, pending, _ = bind_stock_file(cpu, package)
        stops, comparisons, workers, status_calls, ids = [], [], [], [], []

        def observe(c, address, *_):
            lr = c.reg_read(arm.UC_ARM_REG_LR)
            if address == STATUS_SETUP:
                require(lr == STATUS_RETURN and not status_calls, "unexpected flash status setup")
                status_calls.append(hex(lr-4))
                c.reg_write(arm.UC_ARM_REG_PC, lr)  # Model no SPI bus activity; no controller exists.
            elif address == WORKER:
                workers.append(dict(nor_offset=hex(c.reg_read(ARG_REGS[1])), bytes=c.reg_read(ARG_REGS[2])))
            elif address == COMPARE_RESULT:
                comparisons.append((c.reg_read(arm.UC_ARM_REG_R7), c.reg_read(ARG_REGS[0]) == 0))
            elif address == 0x2006DFEC:
                ids.append((bytes(c.mem_read(incoming_boot_id, 16)), c.reg_read(ARG_REGS[0])))
            else:
                stops.append((address, c.reg_read(ARG_REGS[0]), lr))
                c.emu_stop()

        def reject_write(*_):
            raise ValueError("unexpected NOR write in a read-only replay")

        cpu.hook_add(uc.UC_HOOK_MEM_WRITE_PROT, reject_write, begin=BOOT, end=BOOT+len(stock)-1)
        for address in (STATUS_SETUP, 0x2006DFEC, WORKER, COMPARE_RESULT, marker_worker, digest_compared,
                        0x20069D10, *FLASH_BOUNDARIES):
            cpu.hook_add(uc.UC_HOOK_CODE, observe, begin=address, end=address)
        try:
            call(cpu, WRITE_STAGE, timeout_us=0, instruction_limit=500_000_000)
        except ValueError:
            pc = cpu.reg_read(arm.UC_ARM_REG_PC)
            require(len(stops) == 1 and pc == stops[0][0],
                    f"{name}: unexpected stop at {pc:#x} after {len(comparisons)} comparisons; {stops}")
        else:
            raise ValueError(f"{name}: dispatcher unexpectedly returned")
        pc, r0, _ = stops[0]
        failed = [offset for offset, equal in comparisons if not equal]
        expected_workers = [0, BOOT_SIZE if marked else initial, tail]
        require([int(worker["nor_offset"], 16) for worker in workers] ==
                expected_workers[:len(workers)], f"{name}: stock worker order changed")
        if expected is None:
            require(pc == digest_compared and r0 == 0 and len(comparisons) == len(data)//BOOT_SIZE and not failed,
                    f"{name}: identical A group did not reach verified digest: {stops}, {len(comparisons)}")
            intent = None
        else:
            require(pc == SETUP_CALL and failed == [expected],
                    f"{name}: first different NOR sector was {failed}, stop was {stops}")
            intent = {0: "bootstrap", tail: "shared-A-tail"}.get(expected, "main-copy")
        require(len(status_calls) == 1 and ids == [(marker, 0)] and not pending and
                bytes(cpu.mem_read(BOOT, len(stock))) == stock,
                f"{name}: controller boundary not observed or NOR was modified")
        results.append(dict(case=name, marker_matches=marked, incoming_boot_id_matches=True,
                            initial_status_configuration_requested=True,
                            workers=workers, nor_sectors_compared=len(comparisons), sd_reads=len(reads),
                            fixture_different_nor_offset=None if difference is None else hex(difference),
                            first_array_write_intent=intent, nor_offset=None if expected is None else hex(expected),
                            stop_pc=hex(pc), group_a_digest_compared=pc == digest_compared, nor_unchanged=True))
    return dict(stock_package_sha256=J140_DAT_SHA, stock_main_sha256=J140_MAIN_SHA, cases=results,
                limit="Only the A-group dispatcher and simulated read-only NOR. The initial status call was "
                      "observed but did not execute. Stops precede array mutation; this models no write or recovery.")


def trial(main, encoded, original, flash, *, expect_match):
    cpu = machine(main)
    cpu.mem_map(BOOT, BOOT_SIZE, uc.UC_PROT_READ)
    cpu.mem_write(BOOT, flash)
    # Caller state for file offset 0x64. The previous byte is independently inferred
    # from the first identified stock byte; the timer byte comes from 0x2006DFCC.
    seed = ((encoded[0] ^ original[0]) - 0x4B) & 0xFF
    cpu.mem_write(DECODE_STATE, bytes((seed, 0x4B)))
    cpu.mem_write(CHANGED, b"\x00")
    completed = bind_reads(cpu, iter([(BUFFER, encoded)]))
    compares, stopped = [], []

    def compare(c, *_):
        compares.append(c.reg_read(arm.UC_ARM_REG_R0))

    def block(c, address, *_):
        stopped.append(address)
        c.emu_stop()

    cpu.hook_add(uc.UC_HOOK_CODE, compare, begin=COMPARE_RESULT, end=COMPARE_RESULT)
    for address in FLASH_BOUNDARIES:
        cpu.hook_add(uc.UC_HOOK_CODE, block, begin=address, end=address)
    call(cpu, MD5_INIT, CONTEXT)
    try:
        returned = call(cpu, WORKER, HANDLE, 0, BOOT_SIZE, CONTEXT, CHANGED,
                        instruction_limit=15_000_000, timeout_us=0)
    except ValueError:
        if stopped != [SETUP_CALL] or cpu.reg_read(arm.UC_ARM_REG_PC) != SETUP_CALL or expect_match:
            raise
        returned = None
    require(completed == [BOOT_SIZE], "stock updater did not exactly read the first sector")
    require(len(compares) == 1 and (compares[0] == 0) == expect_match,
            f"stock comparison unexpected: comparisons={compares}, returned={returned}, stopped={stopped}")
    require(stopped == ([] if expect_match else [SETUP_CALL]), "unexpected flash boundary")
    if expect_match:
        require(returned == 0 and bytes(cpu.mem_read(CHANGED, 1)) == b"\x00",
                "identical stock sector did not return success and leave changed flag clear")
    require(bytes(cpu.mem_read(BUFFER, BOOT_SIZE)) == original, "stock update decoder disagreed with bootstrap")
    require(bytes(cpu.mem_read(BOOT, BOOT_SIZE)) == flash, "read-only NOR fixture changed")
    call(cpu, MD5_FINAL, CONTEXT)
    digest = bytes(cpu.mem_read(CONTEXT+88, 16))
    require(digest == md5(encoded, usedforsecurity=False).digest(), "stock update MD5 data differed from encoded input")
    return {
        "fixture_nor_sha256": sha256(flash).hexdigest(),
        "stock_read_bytes": completed[0],
        "decoded_sector_sha256": sha256(original).hexdigest(),
        "stock_partial_md5": digest.hex(),
        "stock_compare_equal": compares[0] == 0,
        "stock_worker_return": returned,
        "stopped_before_flash_setup": f"0x{stopped[0]:08X}" if stopped else None,
        "nor_unchanged": True,
    }


def probe(path, *, stop_before_status_setup=False, observe_first_write=False, pc_image=None):
    package = path.read_bytes()
    require(sha256(package).hexdigest() == J140_DAT_SHA, "only the unchanged stock Japanese 1.40 DAT is supported")
    bootstrap, main, manifest = decode_main(package)
    require(sha256(main).hexdigest() == J140_MAIN_SHA, "unexpected decoded main")
    bootstrap, main = bytes(bootstrap), bytes(main)
    if pc_image is not None:
        require(pc_image.suffix == ".ic705sim", "expected a PC-only .ic705sim image")
        return compare_pc_image(main, package, pc_image.read_bytes())
    if stop_before_status_setup:
        return dispatcher_boundary(main, package)
    offset = manifest["bootstrap"]["file_offset"]
    layout, group_a = checked_group_a(package)
    if observe_first_write:
        return first_write_intent(main, package, bootstrap, group_a)
    encoded = package[offset:offset+BOOT_SIZE]
    return {
        "stock_package_sha256": J140_DAT_SHA,
        "stock_main_sha256": J140_MAIN_SHA,
        "stock_sector_file_offset": offset,
        "stock_preflight": full_preflight(main, package, layout["groups"]),
        "unchanged_nor": trial(main, encoded, bootstrap, bootstrap, expect_match=True),
        "erased_nor_control": trial(main, encoded, bootstrap, b"\xff"*BOOT_SIZE, expect_match=False),
        "limit": "Only the original header and component digest workers and one isolated sector worker ran in a "
                 "CPU model. SD and prior build state were simulated. No menu handoff, flash setup, programming, "
                 "authenticity conclusion, boot recovery, or device access.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock_dat", type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dispatcher-boundary", action="store_true",
                       help="replay the isolated stock dispatcher up to (but excluding) NOR configuration")
    modes.add_argument("--first-write-intent", action="store_true",
                       help="trace stock A-group update decisions with a read-only NOR fixture")
    modes.add_argument("--compare-pc-image", type=Path,
                       help="compare the original read-only header check on the official DAT and the PC-only image")
    args = parser.parse_args()
    print(json.dumps(probe(args.stock_dat, stop_before_status_setup=args.dispatcher_boundary,
                           observe_first_write=args.first_write_intent, pc_image=args.compare_pc_image), indent=2))


if __name__ == "__main__":
    main()
