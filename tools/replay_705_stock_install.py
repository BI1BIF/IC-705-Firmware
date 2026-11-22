"""Replay a stock J140 main-NOR update and cold boot its resulting bytes in Unicorn."""

import argparse
from collections import Counter
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

from tools.decode_705_main import BOOT_SIZE, J140_DAT_SHA, J140_MAIN_SHA, checked_group_a, decode_a_range, decode_main
from tools.emulate_705 import BASE, BOOT, SCRATCH, arm, call, machine, uc
from tools.probe_705_boot_selection import MARKER, NOR_BYTES, SECOND
from tools.probe_705_stock_update import (BUILDS, DECODE_STATE, DIGEST_CHECK, HEADER_CHECK, STOCK_PATH, WRITE_STAGE,
                                          bind_stock_file, require)
from tools.render_705_display import load
from tools.replay_705_nor_boot import boot_from_nor


SPIBSC, A_VERIFIED = 0x3FEFA000, 0x2006E160
A_PREFIX, SHARED = SECOND-BOOT, 0xC00000
SELECTOR = MARKER-BOOT
J132_DAT_SHA = "43903a2046978d7559bc60f0c834c864d5d6ac1531f29c785c0a66003b8796f0"
TASK, STAGE, UI = 0x203802BC, 0x20380738, 0x203807F0
VERSION_BANK = (0x203E1B67, 0x203E1B40, 0x203E1B5A, 0x203E1B4D)


def load_a(package, expected_main):
    boot, main, _ = decode_main(package)
    _, group = checked_group_a(package)
    start = group["offset"]+BOOT_SIZE
    data = bytes(boot)+bytes(decode_a_range(package, start, group["end_exclusive"]-start, boot[-1]))
    require(len(data) == 0x9C0000 and sha256(main).hexdigest() == expected_main, "unexpected stock source")
    return bytes(main), data


def european_update_rom(japan, europe):
    @lru_cache(maxsize=None)
    def rom(pc):
        at = (pc & ~1)-BASE
        reference = japan[at-56:at+72]
        scores = sorted((sum(a == b for a, b in zip(reference, europe[at-56+d:at+72+d])), d)
                        for d in (-244, -240, -152, 0, 192, 224, 228))
        score, delta = scores[-1]
        require(score >= 74 and score > scores[-2][0], f"ambiguous E140 service {pc:#x}: {scores}")
        return pc+delta

    return rom


def observed_preflight(cpu, package, prior, reads, pending, opened, *, mismatch=None, rom=lambda pc: pc):
    # Reported component versions from the prior package header are a board-state fixture.
    # BUILDS is the board-reported version compared to the optional B record.
    # E140 supplies that record, whereas J140 leaves the eight bytes blank.
    board_version = prior[20:28] if any(prior[20:28]) else prior[4:12]
    cpu.mem_write(BUILDS, board_version)
    for i, at in enumerate(VERSION_BANK):
        field = prior[0x1c+4*i:0x20+4*i]
        cpu.mem_write(at, b"0"+field[1:] if mismatch == "C" and i == 0 else field)
    wlan = prior[0x2c:0x38]
    cpu.mem_write(0x20498680, b"\x01"+wlan[1:] if mismatch == "D" else wlan)
    require(call(cpu, rom(HEADER_CHECK), timeout_us=0, instruction_limit=5_000_000) == 0 and not opened() and not pending,
            "original header checker did not accept the official DAT")
    selection = bytes(cpu.mem_read(TASK+27, 4))
    require(reads[-1] == (len(package)-2, 2), "original header did not read its end marker")
    reads.clear()
    groups, _ = checked_group_a(package)
    digests = []
    def compare(c, pc, *_):
        require(c.reg_read(arm.UC_ARM_REG_R0) == 0, "original digest comparison failed")
        digests.append(checks[pc])

    checks = dict(zip(map(rom, (0x2006D2D0, 0x2006D500, 0x2006D6C4, 0x2006D890)), "ABCD"))
    hooks = [cpu.hook_add(uc.UC_HOOK_CODE, compare, begin=at, end=at) for at in checks]
    try:
        require(call(cpu, rom(DIGEST_CHECK), timeout_us=0, instruction_limit=330_000_000) == 0 and not opened() and not pending,
                "original digest worker did not accept the official DAT")
    finally:
        for hook in hooks:
            cpu.hook_del(hook)
    for group in groups["groups"]:
        start, end = group["offset"], group["end_exclusive"]
        observed = [(at, n) for at, n in reads if start <= at <= end]
        expected = [(at, min(0x8000, end-at)) for at in range(start, end, 0x8000)]+[(end, 16)]
        require(observed == (expected if group["name"] in digests else []), f"unexpected read plan for {group['name']}")
    reads.clear()
    return dict(selection_bytes=selection.hex(), digests=digests, fixture_prior_build=prior[4:12].decode(),
                fixture_board_version=board_version.decode())


def finish_stock_task(cpu, completed, pending, opened, *, rom=lambda pc: pc, path=STOCK_PATH):
    mailbox = TASK+0x60
    event = 0x7050
    ui_poll, task_dispatch, task_idle = map(rom, (0x200F6610, 0x20071C8C, 0x20071C80))
    signal, wait, dialog = map(rom, (0x202D47B4, 0x202D4804, 0x20047B28))
    events, dialogs, branch_hits = [], [], []
    byte = lambda address: cpu.mem_read(address, 1)[0]

    def leave(c):
        lr = c.reg_read(arm.UC_ARM_REG_LR)
        c.reg_write(arm.UC_ARM_REG_CPSR, c.reg_read(arm.UC_ARM_REG_CPSR) & ~0x20)
        c.reg_write(arm.UC_ARM_REG_PC, lr)

    def boundary(c, pc, *_):
        args = tuple(c.reg_read(r) for r in (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2))
        if pc == dialog:
            dialogs.append(args)
        else:
            require(args[0] == event, "unexpected stock RTOS event")
            events.append(dict(pc=hex(pc), phase=byte(STAGE)))
            if pc == wait:
                require(args[1] == 0xFFFFFFFF and byte(STAGE) == 5 and completed == [rom(A_VERIFIED)],
                        "unexpected stock wait")
                # shortcut: model the other task's mode-5 acknowledgement, until board coordination is replayed.
                c.mem_write(STAGE, b"\x01")
            c.reg_write(arm.UC_ARM_REG_R0, 0)
        leave(c)

    cpu.mem_write(TASK+0x5C, event.to_bytes(4, "little"))
    cpu.mem_write(UI, b"\x41")  # Original UI state just after the confirmation, before scheduling writes.
    cpu.mem_write(0x203FFA4D, path)  # The selected virtual file; stock UI copies it to the file task.
    cpu.mem_write(STAGE, b"\x01")
    for address in (signal, wait, dialog):
        cpu.hook_add(uc.UC_HOOK_CODE, boundary, begin=address, end=address)
    for address in map(rom, (0x2006E174, 0x2006E358, 0x2006E558)):
        cpu.hook_add(uc.UC_HOOK_CODE, lambda _c, pc, *_: branch_hits.append(hex(pc)), begin=address, end=address)
    call(cpu, ui_poll)
    require(byte(UI) == 0x42 and byte(mailbox) == 11 and dialogs == [(0xA0, 0, 0)],
            f"original UI did not dispatch the stock writer: {events=} {dialogs=}")

    cpu.reg_write(arm.UC_ARM_REG_R4, TASK)
    cpu.reg_write(arm.UC_ARM_REG_R5, 0)
    cpu.emu_start(task_dispatch, task_idle, count=950_000_000)
    require(cpu.reg_read(arm.UC_ARM_REG_PC) == task_idle and completed == [rom(A_VERIFIED)] and not opened() and
            not pending and not branch_hits and byte(mailbox) == 0 and byte(TASK+0x6c) == 255 and
            cpu.reg_read(arm.UC_ARM_REG_R0) == 0,
            f"stock write request did not return success at file task: {events=} {branch_hits=}")
    call(cpu, ui_poll)
    require(byte(UI) == 0x44, "original update UI did not acknowledge file task completion")
    call(cpu, ui_poll)
    require(byte(UI) == 0x45 and dialogs == [(0xA0, 0, 0), (0xA6, 0, 0)] and byte(0x203808D2) == 20,
            "original update UI did not request completion dialog and timer")
    delay = byte(0x203808D2)
    call(cpu, ui_poll)
    require(byte(UI) == 0x45 and byte(0x203808D2) == delay, "UI left the completion state before timer expiry")
    # shortcut: deliver timer expiry without running the board scheduler, until the latter is modeled.
    cpu.mem_write(0x203808D2, b"\0")
    call(cpu, ui_poll)
    require(byte(UI) == 0 and byte(0x20380736) == byte(0x20380737) == 1,
            "stock UI did not exit with the main update restart pending")
    restart = observe_restart_tail(cpu, rom=rom)
    return dict(write_task_return=0, non_a_writer_branches=branch_hits, progress=255, dialogs=[hex(d[0]) for d in dialogs],
                completion_delay=delay, ui_state_after_expiry=byte(UI), event_boundaries=events, file_closed=True,
                restart_tail=restart)


def observe_restart_tail(cpu, *, rom=lambda pc: pc):
    """Run the original power-off tail with the update's retained restart flag."""
    wdt, cpg, pfc, clock = 0xFCFE0000, 0xFCFE0400, 0xFCFE3000, 0xFCFEC000
    accessed, stored = [], {}
    expected_watchdog = [(wdt+4, 2, 0x5A5F), (wdt+2, 2, 0x5AFE), (wdt, 2, 0xA55F), (wdt, 2, 0xA57F)]

    def read(_c, off, width, base):
        address = base+off
        if (address, width) == (clock+0x404, 4):
            return 0xFFFFFFFF  # Elapsed guest delay, no cycle timing model.
        require(width == 1 and address in (cpg+8, pfc+0x408), f"unexpected power-tail read {address:#x}/{width}")
        return stored.get(address, 0)

    def write(_c, off, width, value, base):
        address = base+off
        require((address, width) in ((pfc+0x128, 4), (pfc+0x408, 1), (pfc+0x828, 4),
                                    (cpg+8, 1), (clock+0x414, 1), (clock+0x418, 1)) or
                (address, width, value) in expected_watchdog, f"unexpected power-tail write {address:#x}/{width}/{value:#x}")
        stored[address] = value
        accessed.append((address, width, value))

    for page in (wdt, pfc, clock):
        cpu.mmio_map(page, 4096, read, page, write, page)
    cpu.reg_write(arm.UC_ARM_REG_C1_C0_2, 0xF00000)
    cpu.reg_write(arm.UC_ARM_REG_FPEXC, 0x40000000)
    cpu.reg_write(arm.UC_ARM_REG_R5, 0x20380737)
    cpu.reg_write(arm.UC_ARM_REG_R6, 0x2038041F)
    cpu.emu_start(rom(0x200788E0), rom(0x20078188), count=20000)
    require(cpu.reg_read(arm.UC_ARM_REG_PC) == rom(0x20078188) and
            [record for record in accessed if record[0] < cpg] == expected_watchdog,
            f"no original watchdog reset request: pc={cpu.reg_read(arm.UC_ARM_REG_PC):#x} {accessed=}")
    return dict(entry=hex(rom(0x200788e0)), watchdog_request_pc=hex(rom(0x20078178)),
                watchdog_writes=[dict(address=hex(address), value=hex(value)) for address, _, value in expected_watchdog],
                scope="isolated original final shutdown branch with retained update state; simulated peripheral bus")


class SpiNor:
    """The subset of SPIBSC and NOR transactions used by the stock A writer."""

    def __init__(self, cpu, snapshot, cuts=None):
        self.regs = {}
        self.cpu = cpu
        self.cuts = cuts
        self.write_enabled = False
        self.status = 0
        self.page_address = None
        self.payload = bytearray()
        self.erases = []
        self.programmed = Counter()
        self.commands = Counter()
        self.status_writes = []
        self.first_transactions = []
        cpu.mem_map(BOOT, NOR_BYTES, uc.UC_PROT_READ)
        cpu.mem_write(BOOT, snapshot)
        cpu.mmio_map(SPIBSC, 4096, self.read, None, self.write, None)

    def read(self, _cpu, offset, width, _data):
        require(offset <= 0x60 and offset % 4 == 0 and width in (1, 4), f"unknown SPIBSC read {offset:#x}/{width}")
        return 1 if offset == 0x48 else self.regs.get(offset, 0)  # TEND: no bus latency model.

    def write(self, cpu, offset, width, value, _data):
        require(offset <= 0x60 and offset % 4 == 0 and (width == 4 or width == 1 and offset == 0x40),
                f"unknown SPIBSC write {offset:#x}/{width}")
        self.regs[offset] = value
        if offset != 0x20 or not value & 1:
            return
        mode = self.regs[0x30]
        opcode = self.regs[0x24] >> 16 & 255
        address = self.regs.get(0x28, 0)
        if len(self.first_transactions) < 24:
            self.first_transactions.append([hex(cpu.reg_read(arm.UC_ARM_REG_PC)), hex(opcode), hex(mode), hex(value)])
        if mode & 0x4000:
            self.commands[opcode] += 1
            require(self.page_address is None, "new command before end of page programming")
            if (opcode, mode, value) == (0x06, 0x4000, 1):
                self.write_enabled = True
            elif (opcode, mode, value) == (0x05, 0x4000, 0x101):
                pass  # The next transfer reads status before releasing chip select.
            elif (opcode, mode, value) == (0x01, 0x4000, 0x101):
                require(self.write_enabled, "status write without WREN")
            elif (opcode, mode, value) == (0xD8, 0x4700, 1):
                require(self.write_enabled and address % BOOT_SIZE == 0 and 0 <= address <= NOR_BYTES-BOOT_SIZE,
                        "invalid erase address or missing WREN")
                self.cpu.mem_write(BOOT+address, b"\xff"*BOOT_SIZE)
                self.erases.append(address)
                self.write_enabled = False
                if self.cuts is not None and (len(self.erases) == 1 or address == SELECTOR):
                    name = "selector_erased" if address == SELECTOR else "first_sector_erased"
                    self.cuts[name] = bytes(self.cpu.mem_read(BOOT, NOR_BYTES))
            elif (opcode, mode, value) == (0x02, 0x4700, 0x101):
                require(self.write_enabled and address % 4 == 0 and 0 <= address <= NOR_BYTES-4,
                        "invalid program address or missing WREN")
                self.page_address = address
            else:
                raise ValueError(f"unexpected NOR command {opcode:#x}/{mode:#x}/{value:#x}")
        elif (opcode, mode, value) == (0x05, 8, 5):
            self.regs[0x38] = self.status | (2 if self.write_enabled else 0)
        elif (opcode, mode, value) == (0x01, 8, 3):
            self.status_writes.append(self.regs[0x40])
            self.status = self.regs[0x40] & ~3
            self.write_enabled = False
        elif opcode == 0x02 and mode == 0xF and value in (3, 0x103) and self.page_address is not None:
            self.payload.extend(self.regs[0x40].to_bytes(4, "little"))
            at = self.page_address
            require(at % 256+len(self.payload) <= 256, "stock program crossed a page boundary")
            if value == 3:
                current = self.cpu.mem_read(BOOT+at, len(self.payload))
                require(all(old & new == new for old, new in zip(current, self.payload)), "programming set an erased-only bit")
                self.cpu.mem_write(BOOT+at, bytes(self.payload))
                self.programmed[at & ~(BOOT_SIZE-1)] += len(self.payload)
                self.payload.clear()
                self.page_address = None
                self.write_enabled = False
        else:
            raise ValueError(f"unexpected NOR transfer {opcode:#x}/{mode:#x}/{value:#x}")


def update_a(main, package, initial, *, prior=None, cuts=None, active_second=False, rom=lambda pc: pc, path=STOCK_PATH):
    cpu = machine(main)
    nor = SpiNor(cpu, initial, cuts)

    def cache_read(_c, offset, width, _):
        require(width == 4 and offset in (0x104, 0x730, 0x7FC), f"unknown cache read {offset:#x}/{width}")
        return 0  # No data cache is simulated; maintenance completes immediately.

    def cache_write(_c, offset, width, value, _):
        require(width == 4 and (offset, value) in ((0x730, 0), (0x7FC, 0xFF)),
                f"unknown cache write {offset:#x}/{width}/{value:#x}")

    cpu.mmio_map(0x3FFFF000, 4096, cache_read, None, cache_write, None)
    reads, pending, opened = bind_stock_file(cpu, package, rom=rom, path=path)
    if prior is None:
        cpu.mem_write(DECODE_STATE+2, bytes((sum(package[4:12]) & 255,)))
    else:
        preflight = observed_preflight(cpu, package, prior, reads, pending, opened, rom=rom)
        require(preflight["digests"] == ["A"] and preflight["selection_bytes"] == "00000001",
                f"original preflight did not select only A: {preflight}")
    # Calculate the layout flag with the original NOR comparison instead of supplying its value.
    flag, store = 0x2038089D, rom(0x20104984)
    cpu.reg_write(arm.UC_ARM_REG_CPSR, 0x1F)
    cpu.reg_write(arm.UC_ARM_REG_SP, SCRATCH-0x200)
    cpu.reg_write(arm.UC_ARM_REG_R4, flag-1)
    cpu.emu_start(rom(0x2010495C), store, count=1000)
    require(cpu.reg_read(arm.UC_ARM_REG_PC) == store and cpu.mem_read(flag, 1)[0] == int(not active_second),
            "original layout flag disagrees with the initial boot slot")

    faults, completed = [], []
    cpu.hook_add(uc.UC_HOOK_MEM_INVALID,
                 lambda c, _kind, addr, width, *_: faults.append((hex(c.reg_read(arm.UC_ARM_REG_PC)), hex(addr), width)) or False)

    def verified(c, pc, *_):
        completed.append(pc)
        if prior is None:
            c.emu_stop()

    cpu.hook_add(uc.UC_HOOK_CODE, verified, begin=rom(A_VERIFIED), end=rom(A_VERIFIED))
    if prior is not None:
        ui_result = finish_stock_task(cpu, completed, pending, opened, rom=rom, path=path)
    else:
        try:
            call(cpu, rom(WRITE_STAGE), timeout_us=0, instruction_limit=950_000_000)
        except (uc.UcError, ValueError) as exc:
            if completed != [rom(A_VERIFIED)] or cpu.reg_read(arm.UC_ARM_REG_PC) != rom(A_VERIFIED):
                raise ValueError(f"A update stopped at {cpu.reg_read(arm.UC_ARM_REG_PC):#x}: "
                                 f"{faults}; SPI start={nor.first_transactions!r}") from exc
        else:
            raise ValueError("A did not reach the stock verification boundary")
    require(not faults and not pending and nor.status_writes == [0x42] and not nor.write_enabled and
            nor.page_address is None and nor.erases and nor.erases[-1] == SELECTOR,
            "stock A did not finish updating the virtual NOR and selector")
    written = bytes(cpu.mem_read(BOOT, NOR_BYTES))
    result = dict(verified_at=hex(rom(A_VERIFIED)), bytes_read=sum(length for _, length in reads), reads=len(reads),
                  erased_sectors=[hex(n) for n in nor.erases], programmed_bytes=sum(nor.programmed.values()),
                  programmed_by_sector={hex(n): size for n, size in sorted(nor.programmed.items())},
                  command_counts={hex(n): count for n, count in sorted(nor.commands.items())},
                  nor_sha256_before=sha256(initial).hexdigest(), nor_sha256_after=sha256(written).hexdigest(),
                  status_writes=nor.status_writes, default_instant_transfer_and_completion=True)
    if prior is not None:
        result.update(preflight=preflight, completion=ui_result)
    return written, result


def verify_power_cuts(main, initial, written, writer, cuts, *, active_second):
    first, second = BOOT_SIZE, A_PREFIX
    active, target = (second, first) if active_second else (first, second)
    require(int(writer["erased_sectors"][0], 16) == target, "stock update did not erase the inactive slot first")
    erased = b"\xff"*BOOT_SIZE
    require(cuts["first_sector_erased"] == initial[:target] + erased + initial[target+BOOT_SIZE:],
            "the first checkpoint differs beyond the erased inactive sector")
    require(cuts["selector_erased"] == written[:SELECTOR] + erased + written[SELECTOR+BOOT_SIZE:],
            "the next slot or shared data was still incomplete at the selector erase")
    require(written[active:active+A_PREFIX-BOOT_SIZE] == initial[active:active+A_PREFIX-BOOT_SIZE],
            "stock update changed the active application slot")
    cases = {}
    for name, image, slot in (("first_sector_erased", cuts["first_sector_erased"], active),
                              ("selector_erased", cuts["selector_erased"], first),
                              ("update_complete", written, target)):
        boot = boot_from_nor(machine(), b"", main, snapshot=image)
        require(boot["source_slot"] == hex(BOOT+slot), f"{name}: cold reset selected the wrong slot")
        cases[name] = dict(nor_sha256=sha256(image).hexdigest(), selected_slot="first" if slot == first else "second",
                           application_sha256=boot["application_sha256"], reached_application_vector=True)
    erase_offsets = {int(at, 16) for at in writer["erased_sectors"]}
    program = {int(at, 16): size for at, size in writer["programmed_by_sector"].items()}
    boundaries = (0, first, second, SELECTOR, SHARED, NOR_BYTES)
    regions = dict(zip(("bootstrap", "slot_a", "slot_b", "selector", "shared"), zip(boundaries, boundaries[1:])))
    regions = {name: dict(erased_sectors=sum(start <= at < end for at in erase_offsets),
                          programmed_bytes=sum(size for at, size in program.items() if start <= at < end))
               for name, (start, end) in regions.items()}
    target_name = "slot_a" if active_second else "slot_b"
    require(sum(r["erased_sectors"] for r in regions.values()) == len(writer["erased_sectors"]) and
            sum(r["programmed_bytes"] for r in regions.values()) == writer["programmed_bytes"] and
            all(result["erased_sectors"] == result["programmed_bytes"] == 0
                for name, result in regions.items() if name not in (target_name, "selector")),
            "stock update had an erase or page program outside the inactive slot and selector")
    cases["observed_write_scope"] = dict(regions=regions, status_register_writes=writer["status_writes"],
                                        verified_groups=writer["preflight"]["digests"],
                                        original_write_return=writer["completion"]["write_task_return"])
    return cases


def run(package, before, *, complete=False, power_cuts=False):
    require(sha256(package).hexdigest() == J140_DAT_SHA, "only unmodified stock Japanese 1.40 DAT is accepted")
    require(sha256(before).hexdigest() == J132_DAT_SHA, "only unmodified stock Japanese 1.32 can seed the inactive slot")
    main, target_a = load_a(package, J140_MAIN_SHA)
    _, older_a = load_a(before, "e2367bf67ec7969ef42cf74a4d0da22d3b75b825377c223ccc131f1ba217617f")
    initial = bytearray(b"\xff"*NOR_BYTES)
    initial[:A_PREFIX] = target_a[:A_PREFIX]
    initial[A_PREFIX:SELECTOR] = older_a[BOOT_SIZE:A_PREFIX]
    initial[SHARED:SHARED+len(older_a)-A_PREFIX] = older_a[A_PREFIX:]
    cuts = {} if power_cuts else None
    written, evidence = update_a(main, package, bytes(initial), prior=before if complete or power_cuts else None,
                                 cuts=cuts)
    expected = initial.copy()
    expected[A_PREFIX:SELECTOR] = target_a[BOOT_SIZE:A_PREFIX]
    expected[SHARED:SHARED+len(target_a)-A_PREFIX] = target_a[A_PREFIX:]
    marker = target_a[0x4F00:0x4F10]
    expected[SELECTOR:SELECTOR+len(marker)] = marker
    require(written == expected, "updated array differs from the independently extracted stock bytes")
    result = dict(stock_dat_sha256=J140_DAT_SHA, prior_inactive_dat_sha256=sha256(before).hexdigest(),
                  stock_updater_main_sha256=J140_MAIN_SHA, verified_entire_array=True, update_a=evidence,
                  scope="A only; stock file API and SPIBSC modeled; no hardware or UI invocation")
    if complete:
        layout, _ = checked_group_a(package)
        old_layout, _ = checked_group_a(before)
        for group, old in zip(layout["groups"][1:], old_layout["groups"][1:]):
            require(package[group["offset"]:group["end_exclusive"]] == before[old["offset"]:old["end_exclusive"]],
                    f"stock {group['name']} differs between files")
        result["scope"] = "A selected; stock file API, NOR, task handoffs and display boundary; no physical media"
        result["version_controls"] = {}
        for name in ("C", "D"):
            cpu = machine(main)
            reads, pending, opened = bind_stock_file(cpu, package)
            report = observed_preflight(cpu, package, before, reads, pending, opened, mismatch=name)
            require(report["digests"] == ["A", name], f"changing the virtual {name} version did not select it")
            result["version_controls"][name] = report
    if power_cuts:
        reverse = initial.copy()
        reverse[BOOT_SIZE:A_PREFIX] = older_a[BOOT_SIZE:A_PREFIX]
        reverse[A_PREFIX:SELECTOR] = target_a[BOOT_SIZE:A_PREFIX]
        reverse[SELECTOR:SELECTOR+len(marker)] = marker
        reverse_expected = expected.copy()
        reverse_expected[SELECTOR:SELECTOR+len(marker)] = b"\xff"*len(marker)
        reverse_cuts = {}
        reverse_written, reverse_writer = update_a(main, package, bytes(reverse), prior=before, cuts=reverse_cuts,
                                                   active_second=True)
        require(reverse_written == reverse_expected, "reverse update differed from the independent flash layout")
        result["power_cuts"] = {
            "scope": "Cold reset on guest-written stock NOR snapshots; completed erase boundaries, no timing model",
            "first_to_second": verify_power_cuts(main, bytes(initial), written, evidence, cuts, active_second=False),
            "second_to_first": verify_power_cuts(main, bytes(reverse), reverse_written, reverse_writer, reverse_cuts,
                                                 active_second=True),
        }
    return written, result


def boot_updated_snapshot(written, package):
    from tools.replay_705_font_boot import replay_resource_task
    main, large, graphics, _, small = load(package)
    previews = []
    control = replay_resource_task(main, large, small, fixture_return=False,
                                   loader=graphics[0x4000:0x49BC], adc_sample=0x180, scif_wait="board_power",
                                   vbus_high=True, power_key_released=False, riic0_idle=True, riic0_finish="stop",
                                   eeprom=b"\xff"*16, startup_dma="format-current", scene_preview=previews,
                                   startup_home_probe=True, no_power_on_check=True, startup_input="close-cw",
                                   startup_flash=graphics, stock_mmu=True, startup_from_nor=True, nor_snapshot=written)
    ui = control["eeprom"]["format_record"]["handoff"]["ui"]
    surfaces = ui["display"]["openvg"]["surfaces"]
    panel = surfaces["startup_resume"]["main_loop_resume"]["startup_input"]
    require(panel["menu_committed"] and panel["exit_committed"] and panel["persistent_writes"] == 0 and
            (panel["frequency_hz"], panel["mode"], panel["stock_menu"]) == (7_030_000, "CW", "KEYER"),
            "updated NOR did not reach original HOME, MENU/KEYER and return")
    require(len(previews) == 8 and previews[5] != previews[6] and previews[5] == previews[7],
            "unexpected original HOME / MENU / HOME frames")
    frames = dict(home=previews[5], menu=previews[6], home_after_exit=previews[7])
    return dict(snapshot_sha256=sha256(written).hexdigest(), nor_boot=control["nor_boot"], panel=panel,
                frame_sha256={name: sha256(data).hexdigest() for name, data in frames.items()}), frames


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock_dat", type=Path)
    parser.add_argument("prior_dat", type=Path, help="official J132 used to seed the inactive virtual slot")
    parser.add_argument("output", type=Path, help="path for JSON evidence and neighboring LCD PNGs")
    parser.add_argument("--complete", action="store_true", help="run original task handoffs through completion")
    parser.add_argument("--power-cuts", action="store_true", help="also cold reset at completed virtual erase boundaries")
    args = parser.parse_args()
    package, before = args.stock_dat.read_bytes(), args.prior_dat.read_bytes()
    frame_paths = {name: args.output.with_name(f"{args.output.stem}-{name}.png")
                   for name in ("home", "menu", "home_after_exit")}
    require(not any(path.exists() for path in (args.output, *frame_paths.values())), "evidence output already exists")
    written, evidence = run(package, before, complete=args.complete, power_cuts=args.power_cuts)
    print("Stock A verified in virtual NOR; cold booting that snapshot.", flush=True)
    evidence["cold_boot"], frames = boot_updated_snapshot(written, package)
    require(evidence["cold_boot"]["snapshot_sha256"] == evidence["update_a"]["nor_sha256_after"],
            "cold boot did not get the unchanged snapshot from the writer")
    require(args.stock_dat.read_bytes() == package and args.prior_dat.read_bytes() == before, "input changed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for name, image in frames.items():
        with frame_paths[name].open("xb") as file:
            file.write(image)
    with args.output.open("x", encoding="utf-8") as report:
        report.write(json.dumps(evidence, indent=2)+"\n")
    print(f"Stock A verified in virtual NOR and cold booted to HOME: {args.output}")


if __name__ == "__main__":
    main()
