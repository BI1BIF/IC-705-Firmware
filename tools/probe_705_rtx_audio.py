"""Replay the J140 stock scheduler, display wake and audio timer offline."""

import argparse
from hashlib import sha256
import json
from math import sin, tau
from pathlib import Path
from struct import pack, unpack
from tempfile import TemporaryDirectory

from tools.attach_705_cw_replay import CURRENT, FRAME_COMPOSED, UI_HANDLE, WORKER_STACK_REQUEST, attach
from tools.emulate_705 import BASE, PROFILES, SP, STOP, arm, call, machine, uc
from tools.make_cw_fixtures import RATE
from tools.probe_705_cw_break_in import MAILBOX, audio
from tools.probe_705_cw_filter import adjacent_fixture, drifting_fixture, mix, tracking_fixture
from tools.probe_705_cw_menu import MODE_UI_A, MODE_VFO_A
from tools.probe_705_cw_pcm import (
    BUILD_REQUEST, DECIMATED, DSP_STATUS, DSP_TX, FILTER_REQUEST, KEY_ACTIVITY, LAYOUT, MIRROR_DSP_STATUS, RAW_DSP_STATUS,
    TEST_CODE,
)
from tools.probe_705_cw_session import (
    FFT_H, FFT_W, FFT_X, HOLD_CLOCK, HOLD_TICKS_PER_SECOND, KEY_HALF_MS, KEY_SPEED_RAW, RTX_CODE,
    SCOPE_CANVAS, SCOPE_H, SCOPE_MEMORY, SCOPE_W, SCOPE_X, SCOPE_Y, WAVE_BINS, WAVE_LABEL, WAVE_W,
    build, check_waveform_marks, pcm_ranges, read_session, seed_key_speed, waveform_fixture,
)
from tools.probe_705_rx_audio import AUDIO_GATE, DMAC, samples
from tools.probe_705_rf_sweep import sweep_blocks
from tools.probe_705_tx_icon import ICON_FIELD, SPRITES, TX_GRAY_FLAGS
from tools.render_705_display import GRAPHICS_FLASH, PAGE, load
from tools.render_705_stock_row import make_surface, png, require
from tools.replay_705_ptt_tune import FLAGS, INIT_RANGES, PORT_MODE, PORT_PTT, STATUS_TASK
from tools.replay_705_settings import GRID_PAGE, KEY_SAMPLE, TOUCH_POLL, TOUCH_SAMPLE, UPDATE, attach_front_surface
from tools.replay_705_vfo_split import exchange_in_guest, seed_vfos


COUNT, FIRST, WAITER = 0x2038074A, 0x2038074B, 0x2038089C
MAIN_READY, SEM_WAIT, SEM_RESUME = 0x20098340, 0x2013D5C8, 0x2013D5CC
LOOP, AUDIO_READY, TIMERS_CLEARED = 0x200D4EC4, 0x200D4EDC, 0x200D4EF0
PCM_STEP, PCM_DONE = 0x200D4F74, 0x200D4F78
UI_UPDATE_CALL = 0x200D5114
IDLE = 0x201254B0
GICD, GICC = 0xE8201000, 0xE8202000
SGIR = GICD + 0xF00
TIMER, DMA_TIMER = 154, 159
TOUCH_UP = b"\x01\0\0\0\0"


class StackAudit:
    """Observe the original allocator and writes into the CW worker's stack."""

    def __init__(self, cpu):
        self.cpu = cpu
        self.pools, self.request, self.returned = {}, None, None
        self.hook(0x202D4E68, self.pool_init)
        self.write_count, self.lowest = 0, {}

    def hook(self, pc, fn):
        return self.cpu.hook_add(uc.UC_HOOK_CODE, fn, begin=pc, end=pc)

    def word(self, addr, width=4):
        return int.from_bytes(self.cpu.mem_read(addr, width), "little")

    def pool_init(self, cpu, *_):
        self.pools[cpu.reg_read(arm.UC_ARM_REG_R0)] = cpu.reg_read(arm.UC_ARM_REG_R1)

    def create(self, cpu, *_):
        self.request = (cpu.reg_read(arm.UC_ARM_REG_R0), cpu.reg_read(arm.UC_ARM_REG_R1))

    def allocated(self, cpu, *_):
        self.returned = cpu.reg_read(arm.UC_ARM_REG_R0)

    def attach(self, extension, schedule_marker):
        cpu = self.cpu
        hooks = self.hook(0x202D4B16, self.create), self.hook(0x202D6004, self.allocated)
        try:
            thread = attach(cpu, extension, draw=False, schedule_marker=schedule_marker)
        finally:
            for hook in hooks:
                cpu.hook_del(hook)
        require(self.request is not None and self.returned, "original stack allocator did not return a buffer")
        self.pool, requested = self.request
        self.base = self.word(thread+0x2C)
        self.size = self.word(thread+0x26, 2)
        self.top = self.base + self.size
        self.initial_sp = self.word(thread+0x28)
        self.initial_header = bytes(cpu.mem_read(self.base-8, 8))
        self.pool_size = self.pools.get(self.pool, 0)
        self.code_end = RTX_CODE + len(extension[0])
        require(self.base == self.returned and self.size == requested == WORKER_STACK_REQUEST and
                self.pool <= self.base-8 < self.top <= self.pool+self.pool_size-4 and
                self.word(self.base-4) == ((self.size+11) & ~3) and
                self.initial_sp == (self.top & ~7)-64 and self.word(self.base) == 0xE25A2EA5,
                "original pool, stack bounds, saved SP or bottom marker did not match")
        self.thread = thread
        cpu.hook_add(uc.UC_HOOK_MEM_WRITE, self.observe, begin=self.base-8, end=self.top-1)
        return thread

    def observe(self, cpu, _kind, addr, width, _data, _user):
        require(self.base+4 <= addr and addr+width <= self.top, "CW stack write hit a boundary")
        self.write_count += 1
        pc = cpu.reg_read(arm.UC_ARM_REG_PC)
        source = "cw_code" if RTX_CODE <= pc < self.code_end else "stock_code"
        previous = self.lowest.get(source)
        if previous is None or addr < previous[0]:
            self.lowest[source] = addr, dict(address=hex(addr), pc=hex(pc),
                                             sp=hex(cpu.reg_read(arm.UC_ARM_REG_SP)),
                                             arm_mode=hex(cpu.reg_read(arm.UC_ARM_REG_CPSR) & 31),
                                             current_task=hex(self.word(CURRENT)), bytes_from_top=self.top-addr)

    def evidence(self):
        saved_sp = self.word(self.thread+0x28)
        require(set(self.lowest) == {"stock_code", "cw_code"} and self.base+4 <= saved_sp < self.top and
                self.word(self.base) == 0xE25A2EA5 and self.cpu.mem_read(self.base-8, 8) == self.initial_header,
                "CW stack was not exercised by both paths or its metadata changed")
        lowest = min(row[0] for row in self.lowest.values())
        return dict(pool=hex(self.pool), pool_bytes=self.pool_size, stack_base=hex(self.base),
                    stack_limit=hex(self.top), stack_bytes=self.size, allocator_bytes=self.word(self.base-4),
                    initial_saved_sp=hex(self.initial_sp), final_saved_sp=hex(saved_sp),
                    lowest_writes={k: v[1] for k, v in self.lowest.items()}, observed_write_count=self.write_count,
                    used_bytes_by_lowest_write=self.top-lowest, untouched_bytes_above_marker=lowest-self.base-4,
                    original_header_and_bottom_marker_intact=True)


def probe(main, extension=None, *, graphics=None, render_output=None, screen=False, stress=None, adjust=False,
          measure_stack=False, live=False, rf_scope=False, field_rtx=None, audio_experiment=None):
    digest = sha256(main).hexdigest()
    require(digest in PROFILES and PROFILES[digest].name == "705J140", "expected stock Japanese 1.40")
    cpu = machine(main)
    for page in (GICD, GICC, 0xFCFEC000, 0xFCFE0000, 0x3FFFF000,
                 0xFCFE3000, 0xFCFE7000, 0xFCFEE000, 0xFCFEF000, 0xFCFF0000, DMAC, 0xE8005000):
        cpu.mem_map(page, 4096)
    cpu.mem_write(PORT_MODE, pack("<H", 0x40))
    cpu.mem_write(PORT_PTT, pack("<H", 0x2000))  # Active-low input; neutral is high.
    call(cpu, 0x200052ED, 0x20367B78, 0x20380000, 0x1F44)
    call(cpu, 0x200054DC)  # Original VFP setup, before the isolated RTX entry.
    if graphics:
        _, font, sprites, _, small_font = graphics
        _, surface = make_surface(main, font, small_font, cpu=cpu, initialize=False)
        cpu.mem_map(GRAPHICS_FLASH, len(sprites), uc.UC_PROT_READ)
        cpu.mem_write(GRAPHICS_FLASH, sprites)
        attach_front_surface(cpu, surface, double_buffered=True)
    stages, sgis, eois, faults = {}, [], [], []
    svc_count = 0
    stack_audit = StackAudit(cpu) if measure_stack else None

    def finish(report):
        if stack_audit:
            report["cw_worker_stack"] = stack_audit.evidence()
        return report

    def reg(name):
        return cpu.reg_read(getattr(arm, "UC_ARM_REG_" + name))

    def set_reg(name, value):
        cpu.reg_write(getattr(arm, "UC_ARM_REG_" + name), value)

    def value(addr, length=4):
        return int.from_bytes(cpu.mem_read(addr, length), "little")

    def enter(mode, spsr, lr, vector):
        set_reg("CPSR", (spsr & ~0x3F) | mode)
        set_reg("SPSR", spsr)
        set_reg("LR", lr)
        set_reg("PC", BASE + vector)

    def svc(_cpu, number, _data):
        nonlocal svc_count
        pc, status = reg("PC"), reg("CPSR")
        thumb = bool(status & 32)
        width, opcode = (2, 0xDF00) if thumb else (4, 0xEF000001)
        require(number == 2 and (status & 31) in (31, 16) and value(pc-width, width) == opcode,
                f"unexpected exception {number} at {pc:#x}")
        svc_count += 1
        enter(0x93, status, pc, 8)

    def observe(_cpu, _kind, address, _size, data, _user):
        if address == SGIR:
            sgis.append(data)
        else:
            eois.append(data)

    def advance_counter(c, _kind, address, _size, _value, _user):
        c.mem_write(address, pack("<I", value(address)+4096))

    def unmapped(_cpu, _kind, address, *_):
        faults.append(hex(address))
        return False

    cpu.hook_add(uc.UC_HOOK_INTR, svc)
    cpu.hook_add(uc.UC_HOOK_MEM_INVALID, unmapped)
    for address in (SGIR, GICC+0x10):
        cpu.hook_add(uc.UC_HOOK_MEM_WRITE, observe, begin=address, end=address)
    # The board delay polls OSTM1. Advance only on its counter read.
    cpu.hook_add(uc.UC_HOOK_MEM_READ, advance_counter, begin=0xFCFEC404, end=0xFCFEC404)
    # Keep the same virtual addresses as the guest; the rig has flat mappings.
    cpu.hook_add(uc.UC_HOOK_CODE, lambda *_: set_reg("R0", reg("R0") & ~1),
                 begin=0x20125560, end=0x20125560)
    for mode, stack in ((0x93, SP-0x1000), (0x92, SP-0x2000), (0x1F, SP)):
        set_reg("CPSR", mode)
        set_reg("SP", stack)

    def run(entry, target, *, limit=1_000_000):
        def stop(_c, _pc, *_):
            cpu.emu_stop()

        hook = None if target == STOP else cpu.hook_add(uc.UC_HOOK_CODE, stop, begin=target, end=target)
        try:
            cpu.emu_start(entry, STOP, count=limit)
        except uc.UcError as err:
            raise ValueError(f"run {entry:#x} failed at {reg('PC'):#x}, unmapped: {faults}") from err
        finally:
            if hook is not None:
                cpu.hook_del(hook)
        pc = reg("PC")
        require(pc == target, f"{entry:#x} reached {pc:#x}, expected {target:#x}")

    def sub(entry, *args):
        set_reg("LR", STOP)
        for i, arg in enumerate(args):
            set_reg(f"R{i}", arg)
        run(entry, STOP)
        return reg("R0")

    def snapshot(label):
        thread = value(CURRENT)
        stages[label] = dict(pc=hex(reg("PC")), thread=hex(thread), priority=value(thread+2, 1),
                             timer_count=value(COUNT, 1), first=value(FIRST, 1), waiter=value(WAITER, 1))
        return thread

    def irq(number, target):
        resume, status = reg("PC"), reg("CPSR")
        require(not status & 0x80, f"IRQ masked at {resume:#x}")
        for offset in (0xC, 0x18):
            cpu.mem_write(GICC+offset, pack("<I", number))
        cpu.mem_write(GICD+0x300, pack("<I", int(number == 0)))
        start = len(eois)
        enter(0x92, status, resume+4, 0x18)
        run(BASE+0x18, target)
        require(eois[start:] == [number], f"stock GIC did not EOI IRQ {number}: {eois[start:]}")
        if target == resume:
            require(reg("CPSR") == status, "IRQ did not restore the preempted CPU mode")

    run(0x200052A8, MAIN_READY)
    main_thread = snapshot("stock-main")
    require(value(main_thread+2, 1) == 0xF4 and value(0x203804BC) != 0,
            "original main thread startup did not register")
    if graphics:
        set_reg("LR", STOP)
        run(0x20145244, STOP, limit=8_000_000)

    sub(0x2013CD54)
    if graphics:
        sub(0x2013CD98)  # Stock framebuffer completion semaphore.
    run(0x2007B29C, 0x2007B2B0)
    ui_thread = value(UI_HANDLE)
    require(ui_thread != main_thread and value(ui_thread+2, 1) == 0xEE and value(CURRENT) == main_thread,
            "UI creation preempted the main thread or has the wrong priority")
    snapshot("ui-created-main-still-running")
    sub(0x2000621C)
    require(value(0x204BA014 + TIMER*4) == 0x200061E8, "stock application timer vector not registered")
    sub(0x20005D5C)
    require(value(0x204BA014 + DMA_TIMER*4) == 0x20005C48, "stock DMA polling vector not registered")

    if extension:
        _, bridges, names = extension
        worker_wait = names["cw_rtx_wait"]
        before_attach = tuple(reg(r) for r in ("PC", "SP", "LR", "CPSR", "R0", "R1"))
        require(value(CURRENT) == main_thread and value(UI_HANDLE) == ui_thread,
                "stock thread owners changed before CW attachment")
        def scheduling():
            return len(sgis)

        worker_thread = (stack_audit.attach(extension, scheduling) if stack_audit else
                         attach(cpu, extension, draw=live, schedule_marker=scheduling))
        require(tuple(reg(r) for r in ("PC", "SP", "LR", "CPSR", "R0", "R1")) == before_attach,
                "CW attachment changed the main task's registers")
        if screen and not live:
            require(value(FRAME_COMPOSED) == 0xE59F0330, "unexpected frame hook instruction")
            cpu.mem_map(SCOPE_CANVAS, SCOPE_MEMORY)
        seed_vfos(cpu, pair=(7_030_000, 7_035_000))
        if live:
            sub(INIT_RANGES)
        if graphics:
            cpu.mem_write(PROFILES[digest].language_bytes, b"\x01\x01")
            sub(0x2001DEA8)  # Publish the fixture VFO through the stock selector.
        for address in (MODE_UI_A, MODE_VFO_A):
            cpu.mem_write(address, b"\x20")
        cpu.mem_write(AUDIO_GATE, b"\x01")

        def key(bank, bit):
            for sample in ((1 << bit), 0):
                cpu.mem_write(KEY_SAMPLE+bank, bytes((sample,)))
                for _ in range(7):
                    sub(TOUCH_POLL)

        def touch(x, y):
            cpu.mem_write(TOUCH_SAMPLE, pack(">BHH", 0, x, y))
            sub(TOUCH_POLL)
            cpu.mem_write(TOUCH_SAMPLE, TOUCH_UP)
            sub(TOUCH_POLL)
            sub(TOUCH_POLL)

        def touch_cw():
            cpu.mem_write(TOUCH_SAMPLE, pack(">BHH", 0, 80, 247))
            for _ in range(3):
                sub(TOUCH_POLL)
            session = read_session(cpu)
            require(session["active"] and not session["menu_two"],
                    "stock MENU did not open CW on page one while the opening press was held")
            cpu.mem_write(TOUCH_SAMPLE, TOUCH_UP)
            for _ in range(2):
                sub(TOUCH_POLL)

        def open_cw():
            key(0, 3)
            # shortcut: for non-screen tests, seed the state the MENU draw consumes.
            cpu.mem_write(PAGE+1, b"\x02")
            cpu.mem_write(GRID_PAGE, b"\x01")
            touch_cw()

        cpu.mem_write(TOUCH_SAMPLE, TOUCH_UP)
        if not screen or stress is not None:
            open_cw()

    sub(0x20104888)
    set_reg("R6", 0)
    run(0x200D4E8C, AUDIO_READY)  # Load the original loop's locals.
    require(snapshot("initial-pass-without-interrupt") == main_thread and value(FIRST, 1) == 1,
            "original first-pass path did not bypass the wait")
    run(AUDIO_READY, TIMERS_CLEARED)
    require(value(COUNT, 2) == 0, "original loop did not clear first-pass and timer count")

    if audio_experiment:
        return audio_experiment(cpu, run, irq, sub, value)
    if field_rtx:
        from tools.probe_705_cw_field_rtx import exercise
        return exercise(field_rtx, cpu, run, irq, reg, value)

    run(LOOP, SEM_WAIT)
    require(snapshot("main-blocked-ui-waiting") == ui_thread and value(WAITER, 1) == 1,
            "audio wait did not schedule UI")
    if extension:
        run(SEM_WAIT, worker_wait)
        require(snapshot("worker-starts-on-own-thread") == worker_thread, "worker did not run as RTX thread")
        run(worker_wait, IDLE)
    else:
        run(SEM_WAIT, IDLE)
    idle_thread = snapshot("both-tasks-blocked")
    require(idle_thread not in (main_thread, ui_thread), "UI did not block on its semaphore")

    def timer_wake(count, background):
        before = len(sgis)
        irq(TIMER, background)
        require(value(COUNT, 1) == count and value(WAITER, 1) == 0 and sgis[before:] == [0x10000],
                f"timer did not signal the stock kernel on count {count}: {sgis[before:]}")
        irq(0, LOOP)

    if extension:
        waveform = audio("CQ TEST 123")
        rounds = 0
        observed = bytearray()
        queued_peak = detector_calls = 0
        fixed_calls = 0

        def observe_pcm(c, *_):
            require(value(CURRENT) == main_thread, "audio tap on wrong thread")
            observed.extend(c.mem_read(reg("SP")+8, 12))

        def observe_detector(_cpu, *_):
            nonlocal detector_calls
            status = reg("CPSR")
            require(value(CURRENT) == worker_thread and status & 0x9F == 0x1F,
                    "detector did not run in interruptible System mode on the CW task")
            detector_calls += 1

        def observe_fixed(c, *_):
            nonlocal fixed_calls
            observe_detector(c)
            fixed_calls += 1

        cpu.hook_add(uc.UC_HOOK_CODE, observe_pcm, begin=bridges[DECIMATED], end=bridges[DECIMATED])
        cpu.hook_add(uc.UC_HOOK_CODE, observe_detector, begin=names["cw_feed"], end=names["cw_feed"])
        if adjust:
            cpu.hook_add(uc.UC_HOOK_CODE, observe_fixed, begin=names["cw_feed_fixed"], end=names["cw_feed_fixed"])
        cpu.mem_write(0x20380874, b"\x01")
        for offset in (0x124, 0x424, 0x524):
            cpu.mem_write(DMAC + offset, pack("<I", 1))

        def dma_group(group, background, rf_block=None):
            nonlocal rounds
            bank = rounds % 2
            left = [x for x in unpack("<6h", group) for _ in range(6)]
            words = [word for sample in left for word in ((sample & 0xFFFF) << 16, 0)]
            cpu.mem_write(LAYOUT["rec_bank"] + bank*0x120, pack("<72I", *words))
            cpu.mem_write(DMAC+0xE4, pack("<I", 0x41 if bank else 0xC1))
            if rf_block is not None:
                cpu.mem_write(0x20400C80 + bank*0x120, pack("<72I", *(w for v in unpack("<36I", rf_block) for w in (0, v))))
                cpu.mem_write(DMAC+0x424, pack("<I", 0x41 if bank else 0xC1))
            irq(DMA_TIMER, background)
            if rf_block is not None:
                cpu.mem_write(DMAC+0x424, pack("<I", 1))  # Modeled DMA completion is acknowledged.
            rounds += 1

        def capture(part, background=IDLE, before_pcm=None, *, mailbox_key=None, rf_blocks=()):
            nonlocal queued_peak
            for offset in range(0, len(part), 12):
                index = offset//12
                dma_group(part[offset:offset+12], background, rf_blocks[index] if index < len(rf_blocks) else None)
            timer_wake(1, background)
            run(LOOP, background)
            timer_wake(2, background)
            if rf_scope:
                # shortcut: local RF pipeline only; the board-control queue is not modeled.
                run(LOOP, AUDIO_READY)
                run(AUDIO_READY+12, TIMERS_CLEARED)
            else:
                run(LOOP, TIMERS_CLEARED)
            if mailbox_key is not None:
                cpu.mem_write(MAILBOX, bytes((0x20 if mailbox_key else 0,)))
                cpu.mem_write(MAILBOX+0x40, b"\x01")
            # shortcut: the hardware mailbox is not modeled; the stock refresh
            # overwrites the touch fixture, which is restored for explicit input.
            run(TIMERS_CLEARED, PCM_STEP)
            if mailbox_key is not None:
                require(value(KEY_ACTIVITY, 1) == mailbox_key, "stock main loop did not parse the DSP key input")
            if before_pcm:
                before_pcm()
            run(PCM_STEP, PCM_DONE)
            state = read_session(cpu)
            queued_peak = max(queued_peak, state["queued"])
            return state

        checked_pcm = []
        frames = []

        def finish_frame(*, vline=False):
            # The screen is virtual. Signal the original ISR-side completion
            # interface, then let RTX wake and retire the original UI request.
            idle_status = reg("CPSR")
            set_reg("CPSR", 0x92)
            before = len(sgis)
            if vline:
                sub(0x2013CDD8)  # Stock LCD completion callback, including request retirement.
            else:
                require(sub(0x202D47BD, value(0x20380CD4)) == 0, "frame completion semaphore failed")
            require(sgis[before:] == [0x10000], "frame completion did not signal UI")
            set_reg("CPSR", idle_status)
            set_reg("PC", IDLE)
            irq(0, SEM_WAIT)
            require(value(CURRENT) == ui_thread, "stock UI did not finish its frame")
            run(SEM_WAIT, IDLE)

        def live_trial():
            # Seed only the power-on LCD conditions, as in stock_menu_navigation.
            # Thereafter only hardware samples, interrupts and LCD completion enter the guest.
            cpu.mem_write(0x2038049B, b"\x01")
            cpu.mem_write(0x204BD690, b"\x01")
            cpu.mem_map(0xFCFF7000, 4096)  # Display register model reports completed rendering.
            cpu.mem_map(0xE8009000, 4096)  # Unconnected serial port, empty RX FIFO.
            cpu.mem_write(0xE8009010, pack("<H", 0x60))
            # This fixture starts after board init; both receiver bookkeeping slots are idle.
            for n in range(2):
                slot = 0x209D0000 + n*0x1000
                cpu.mem_write(0x205E022C + n*16, pack("<I", slot))
                sub(0x202235A4, 0, n)
            set_reg("PC", IDLE)
            dial, dial_reads, scans, updates = 0, 0, 0, 0
            key0 = key1 = 0
            touch_sample = TOUCH_UP
            tick = 0
            last = None
            screen_writes = []
            tuning_writes = []
            panel_states = []
            wave_frames = set()
            wave_peak = 0

            def scope_lcd(pixels):
                stride = 480*4
                # Mini scope starts at LCD row 86 in the replay, followed by its waterfall.
                return dict(spectrum=sha256(pixels[86*stride:110*stride]).hexdigest(),
                            newest=sha256(pixels[110*stride:111*stride]).hexdigest(),
                            waterfall=sha256(pixels[110*stride:136*stride]).hexdigest())

            def panel(c, *_):
                nonlocal scans
                scans += 1
                c.mem_write(KEY_SAMPLE, bytes((key0, key1))+bytes(5))
                c.mem_write(TOUCH_SAMPLE, touch_sample)

            def encoder(c, *_):
                nonlocal dial_reads
                dial_reads += 1
                c.mem_write(0xFCFF0386, pack("<H", dial))  # MTU2 channel 1 TCNT.

            def trace_update(*_):
                nonlocal updates
                updates += 1

            def request(_c, _kind, addr, size, data, _user):
                screen_writes.append([tick, hex(reg("PC")), hex(addr), size, data])

            def tuning(_c, _kind, addr, size, data, _user):
                if len(tuning_writes) < 50:
                    tuning_writes.append([tick, hex(reg("PC")), hex(addr), size, data])

            cpu.hook_add(uc.UC_HOOK_CODE, panel, begin=TOUCH_POLL, end=TOUCH_POLL)
            cpu.hook_add(uc.UC_HOOK_MEM_READ, encoder, begin=0xFCFF0386, end=0xFCFF0386)
            cpu.hook_add(uc.UC_HOOK_CODE, trace_update, begin=UI_UPDATE_CALL, end=UI_UPDATE_CALL)
            for addr in (0x20380C8C, 0x20380C98):
                cpu.hook_add(uc.UC_HOOK_MEM_WRITE, request, begin=addr, end=addr)
            for addr in (0x20380714, 0x203EBC2F):
                cpu.hook_add(uc.UC_HOOK_MEM_WRITE, tuning, begin=addr, end=addr)

            def step(part=b"", rf_blocks=()):
                nonlocal tick, last, wave_peak
                tick += 1
                surface.events.clear()
                surface.pixel_writes.clear()
                surface.image_draws.clear()
                # Drive the original 1 ms RTX clock (hold timers, task timeouts).
                for _ in range(4):
                    irq(134, IDLE)
                capture(part or bytes(72), rf_blocks=rf_blocks)
                run(PCM_DONE, UI_UPDATE_CALL+4, limit=12_000_000)
                state = dict(cw=bool(read_session(cpu)["active"]), page=value(0x203807DD, 1),
                             scope_layout=value(PAGE+3, 1), popup=value(0x204BD0F4, 1), key=value(0x20380431, 1))
                if not panel_states or state != panel_states[-1]["state"]:
                    panel_states.append(dict(tick=tick, state=state))
                # shortcut: the stock loop tail's unrelated board/save housekeeping
                # needs more peripherals; resume at its actual loop-yield instruction.
                if rf_scope:
                    # shortcut: keep the two RF calls in stock order; the surrounding
                    # board update waits for serial/GPIO hardware absent from this rig.
                    sub(0x2011F53C)
                    sub(0x2012022C)
                    sub(0x2012038C)
                run(0x200D5230, IDLE, limit=12_000_000)
                if value(0x20380CBE, 1):
                    surface.select_target()
                    last = bytes(surface.pixels)
                    glyphs = ["".join(chr(g["key"]) for g in e["glyphs"]) for e in surface.events]
                    frames.append(dict(tick=tick, page=value(PAGE+1, 1), glyphs=glyphs,
                                       frequency=value(0x20380714), text=read_session(cpu)["shown_text"],
                                       blits=[w for w in surface.pixel_writes if w["target"] is None],
                                       rf_lcd=scope_lcd(last) if rf_scope else None,
                                       vfo_image=sha256(b"".join(last[(y*480+130)*4:(y*480+372)*4]
                                                                 for y in range(50, 110))).hexdigest()))
                    if part and "CW DECODE" in glyphs:
                        crop = b"".join(last[(y*480+SCOPE_X+3)*4:(y*480+SCOPE_X+WAVE_W-2)*4]
                                        for y in range(SCOPE_Y+6, SCOPE_Y+SCOPE_H-2))
                        width = (WAVE_W-5)*4
                        rows = [y for y in range(len(crop)//width) if
                                any(crop[i+1] > 140 and crop[i] < 60 and crop[i+2] < 120
                                    for i in range(y*width, (y+1)*width, 4))]
                        wave_frames.add(sha256(crop).hexdigest())
                        if rows and rows[-1]-rows[0] > wave_peak:
                            wave_peak = rows[-1]-rows[0]
                            save("07-receive-waveform")
                    finish_frame(vline=True)

            def wait_until(test, label, count=35):
                for _ in range(count):
                    step()
                    if test():
                        return
                raise ValueError(f"{label}: {scans=} {updates=} {dial_reads=} {frames[-3:]=} "
                                 f"{screen_writes[-10:]=} {panel_states[-15:]=}")

            def save(label):
                require(last is not None, f"no committed frame: {label}")
                path = render_output / f"{label}.png"
                path.write_bytes(png(surface.width, surface.height, last))
                frames[-1]["checkpoint"] = label

            def tap(x, y):
                nonlocal touch_sample
                touch_sample = pack(">BHH", 0, x, y)
                step()
                touch_sample = TOUCH_UP
                step()

            def turn_dial(direction):
                nonlocal dial
                start = tick
                before = frames[-1]["frequency"]
                for _ in range(8):
                    dial = (dial + direction*4) & 0xffff
                    step()
                for _ in range(8):
                    step()
                changed = []
                for frame in frames:
                    if frame["tick"] > start and frame["frequency"] != (changed[-1]["frequency"] if changed else before):
                        changed.append(frame)
                require(changed and all(7_000_000 <= f["frequency"] <= 7_100_000 and
                                        any(w["source_target"] == 15 for w in f["blits"]) and
                                        any(w["source_target"] == 16 for w in f["blits"]) for f in changed),
                        "tuning did not repaint the original mini scope and VFO")
                return dict(before=before, after=changed[-1]["frequency"],
                            updates=[f["tick"]-start for f in changed],
                            frequencies=[f["frequency"] for f in changed])

            wait_until(lambda: bool(frames) and frames[-1]["page"] == 1, "stock HOME")
            save("01-home")
            key1 = 1  # M.SCOPE on the stock panel scanner.
            for _ in range(8):
                step()
            key1 = 0
            wait_until(lambda: "-2.5k" in frames[-1]["glyphs"], "stock mini scope grid")
            save("01b-mini-scope")
            if rf_scope:
                sub(0x2011F87C)  # Original spectrum receiver setup after board init.
                sub(0x200EBCD8)  # Original local scope subscription.
                cpu.mem_write(0x203E1BA8, b"\x01")  # Fixture: scope acquisition requested after board init.
                cpu.mem_write(0x203EAEB1, b"\x01")  # Fixture: stock Waterfall display setting is ON.
                set_reg("PC", IDLE)
                period = 12

                def feed_sweep(index, pcm=b""):
                    blocks = ()
                    sweep, phase = divmod(index, period)
                    if phase < 2:
                        center = 48 + (sweep*43) % 376
                        levels = [52 + (i*23+sweep*7)%16 + max(0, 130-6*abs(i-center)) for i in range(476)]
                        # Echo the tag from the stock center/range configuration.
                        blocks = sweep_blocks(levels, value(0x204994CE, 1) & 15)[phase*6:phase*6+6]
                    step(pcm, rf_blocks=blocks)

                def sweeps(label):
                    for _ in range(16):
                        step()
                    # Fill the original history before measuring either arm.
                    for index in range(-period*36, 0):
                        feed_sweep(index)
                    start, initial, pcm_start = tick, len(frames), len(observed)
                    audio_fixture = audio("CQ") + bytes(3840)
                    audio_fixture += bytes(-len(audio_fixture) % (72*period*4))
                    input_frames = len(audio_fixture)//(72*period)
                    publications = []
                    history_ticks = []
                    render_ticks = {}

                    def publication(_c, _kind, _addr, _size, data, _user):
                        if data:
                            publications.append([tick-start, sha256(cpu.mem_read(0x203E1BB8, 475)).hexdigest()])

                    def trace(_c, addr, _size, _user):
                        t = tick-start
                        if addr == 0x200EAA98:
                            history_ticks.append(t)
                        else:
                            render_ticks[t] = render_ticks.get(t, 0) + 1

                    hooks = [cpu.hook_add(uc.UC_HOOK_MEM_WRITE, publication, begin=0x203E1D93, end=0x203E1D93)]
                    for addr in (0x200EAA98, 0x2014A8F8):
                        hooks.append(cpu.hook_add(uc.UC_HOOK_CODE, trace, begin=addr, end=addr))
                    try:
                        for index in range(len(audio_fixture)//72):
                            feed_sweep(index, audio_fixture[index*72:(index+1)*72])
                    finally:
                        for hook in hooks:
                            cpu.hook_del(hook)
                    save(label)
                    previous = frames[initial-1]["rf_lcd"]
                    changed = {key: [] for key in previous}
                    for frame in frames[initial:]:
                        t = frame["tick"]-start
                        for key, digest in frame["rf_lcd"].items():
                            if digest != previous[key]:
                                changed[key].append([t, digest])
                        previous = frame["rf_lcd"]
                    def cadence(updates):
                        gaps = [b[0]-a[0] for a, b in zip(updates, updates[1:])]
                        return dict(count=len(updates), gap_ticks=sorted(set(gaps)),
                                    longest_gap_ticks=max(gaps, default=0))

                    return dict(input_frames=input_frames, published=publications, lcd_changed=changed,
                                cadence={k: cadence(v) for k, v in changed.items()},
                                native_history_ticks=history_ticks, native_colored_rows_rendered=render_ticks,
                                lcd_total=len(frames)-initial, scope_layout=value(0x204BAB61, 1),
                                frequency=value(0x20380714),
                                transcript=read_session(cpu)["shown_text"],
                                audio_ordered=observed[pcm_start:]==audio_fixture,
                                decoder_drops=read_session(cpu)["drops"])

                off = sweeps("01-rf-cw-off")
                key0 = 8
                wait_until(lambda: frames[-1]["page"] == 2, "stock MENU")
                key0 = 0
                save("02-menu")
                tap(80, 247)
                wait_until(lambda: "CW DECODE" in frames[-1]["glyphs"] and frames[-1]["page"] == 1, "CW frame")
                save("03-cw")
                on = sweeps("04-rf-cw-on")
                require(off["published"] == on["published"], "CW changed RF publication timing or bytes")
                require(off["frequency"] == on["frequency"], "CW changed the RF test frequency")
                require(on["transcript"] == "CQ" and not off["transcript"] and "CQ" in frames[-1]["glyphs"],
                        "the waveform fixture did not decode and display CQ only when enabled")
                for arm in (off, on):
                    count = arm["input_frames"]
                    spectrum = arm["lcd_changed"]["spectrum"]
                    newest = arm["lcd_changed"]["newest"]
                    require(arm["audio_ordered"] and not arm["decoder_drops"], "RF replay lost or reordered PCM")
                    require(len(arm["published"]) == len(spectrum) == count and arm["scope_layout"] == 2,
                            "a sweep did not reach the original mini spectrum")
                    require(arm["native_history_ticks"] == [t for t, _ in spectrum] and
                            not set(arm["native_history_ticks"])-arm["native_colored_rows_rendered"].keys(),
                            "LCD RF updates did not come from native history and rendering")
                    require([t for t, _ in newest] == [t for t, _ in arm["lcd_changed"]["waterfall"]] and
                            len(newest) == count//4 and len({digest for _, digest in newest}) == len(newest),
                            "the newest waterfall line did not visibly advance")
                    require(arm["cadence"]["spectrum"]["gap_ticks"] == [period] and
                            arm["cadence"]["newest"]["gap_ticks"] == [period*4], "uneven original RF scheduling")
                return dict(stages=stages, verdict="same RF cadence with and without CW in this virtual replay",
                            cw_off=off, cw_on=on, frames=frames)
            scope_off = turn_dial(1)
            require(turn_dial(-1)["after"] == scope_off["before"], "stock dial did not return to initial frequency")
            key0 = 8
            wait_until(lambda: frames[-1]["page"] == 2, "stock MENU")
            key0 = 0
            save("02-menu")
            touch_sample = pack(">BHH", 0, 80, 247)
            wait_until(lambda: read_session(cpu)["active"], "touch CW")
            touch_sample = TOUCH_UP
            wait_until(lambda: "CW DECODE" in frames[-1]["glyphs"] and frames[-1]["page"] == 1, "CW frame")
            save("03-cw")
            tap(430, 254)
            require(read_session(cpu)["color_open"], "SET did not reach the CW handler")
            wait_until(lambda: "CW DECODE SET" in frames[-1]["glyphs"], "SET visible")
            save("04-set")
            tap(430, 254)
            wait_until(lambda: "CW DECODE" in frames[-1]["glyphs"], "SET closed")
            tap(430, 157)
            wait_until(lambda: "SPEED" in frames[-1]["glyphs"] and "LOCK" in frames[-1]["glyphs"], "SPEED visible")
            save("05-speed")
            tap(58, 226)
            wait_until(lambda: "AUTO" in frames[-1]["glyphs"] and "SPEED" not in frames[-1]["glyphs"], "SPEED closed")
            before = frames[-1]["vfo_image"]
            scope_on = turn_dial(1)
            require(scope_on == scope_off and frames[-1]["vfo_image"] != before,
                    f"dial with CW did not match original tuning: {scope_off=} {scope_on=}")
            save("06-dial")
            fixture = audio("CQ") + bytes(3840)
            pcm_offset = len(observed)
            for i in range(0, len(fixture), 72):
                step(fixture[i:i+72])
            wait_until(lambda: frames[-1]["text"] == "CQ" and "CQ" in frames[-1]["glyphs"], "CQ visible")
            pcm = observed[pcm_offset:pcm_offset+len(fixture)]
            require(pcm == fixture and not read_session(cpu)["drops"], "PCM differed or queue dropped audio")
            require(len(wave_frames) > 1 and wave_peak > 4, f"CW waveform did not move: {wave_peak}")
            save("08-cq")
            require(frames[-1]["vfo_image"] == next(f["vfo_image"] for f in frames if f.get("checkpoint") == "06-dial"),
                    "CW audio update replaced the VFO display")
            speed = read_session(cpu)["speed_wpm"]
            tap(430, 157)
            wait_until(lambda: "SPEED" in frames[-1]["glyphs"], "speed picker after receive")
            tap(140, 226)
            wait_until(lambda: "LOCK" in frames[-1]["glyphs"] and "SPEED" not in frames[-1]["glyphs"], "LOCK visible")
            require(read_session(cpu)["speed_locked"] and read_session(cpu)["speed_wpm"] == speed,
                    "LOCK did not preserve the measured speed")
            save("08b-speed-lock")
            key1 = 4
            wait_until(lambda: not read_session(cpu)["active"], "stock physical EXIT")
            key1 = 0
            wait_until(lambda: "CW DECODE" not in frames[-1]["glyphs"] and frames[-1]["page"] == 1, "clean HOME")
            save("09-exit")
            key0 = 8
            wait_until(lambda: frames[-1]["page"] == 2, "reopen MENU")
            key0 = 0
            tap(80, 247)
            wait_until(lambda: "CW DECODE" in frames[-1]["glyphs"] and frames[-1]["page"] == 1, "reopen CW")
            key1 = 2
            wait_until(lambda: "クイックメニュー" in frames[-1]["glyphs"], "stock QUICK over mini scope")
            require(not read_session(cpu)["active"] and "CW DECODE" not in frames[-1]["glyphs"], "CW overlaid QUICK")
            save("10-stock-quick")
            return dict(stages=stages, frames=frames, guest_screen_writes=screen_writes, tuning_writes=tuning_writes,
                        guest_panel_states=panel_states,
                        scans=scans, updates=updates, dial_reads=dial_reads,
                        dial_and_scope=dict(cw_off=scope_off, cw_on=scope_on, compares="VFO and stock mini-scope grid",
                                           has_rf_samples=False),
                        receive=dict(dma_groups=len(pcm)//12, pcm_sha256=sha256(pcm).hexdigest(), wave_peak_pixels=wave_peak,
                                     unique_wave_frames=len(wave_frames), transcript="CQ", speed_wpm=speed,
                                     detector_calls=detector_calls))

        def stock_menu_navigation():
            # LCD-on conditions for this isolated RTX rig, before either page exists.
            # PAGE+1 and the MENU grid index must be set by the guest itself.
            cpu.mem_write(0x2038049B, b"\x01")
            cpu.mem_write(0x204BD690, b"\x01")
            pages = []
            for label, mode in (("home", 1), ("menu", 2)):
                capture(b"")
                cpu.mem_write(TOUCH_SAMPLE, TOUCH_UP)
                if mode == 2:
                    key(0, 3)
                writes = []

                def record(_cpu, _kind, address, _size, data, _user):
                    writes.append([hex(reg("PC")), hex(address), data])

                hooks = [cpu.hook_add(uc.UC_HOOK_MEM_WRITE, record, begin=a, end=a) for a in (PAGE+1, GRID_PAGE)]
                try:
                    require(value(CURRENT) == main_thread, "page update did not start on the original main thread")
                    # Run the original call site in the receive loop. The other
                    # iterations of that loop are outside this isolated fixture.
                    run(UI_UPDATE_CALL, UI_UPDATE_CALL+4)
                finally:
                    for hook in hooks:
                        cpu.hook_del(hook)
                slot = value(GRID_PAGE, 1)
                require(value(PAGE+1, 1) == mode and value(0x20380C8C) == 2 and
                        ["0x20095f78", hex(PAGE+1), 1] in writes and
                        (mode == 1 or slot == 1 and ["0x200927d0", hex(GRID_PAGE), 1] in writes),
                        f"original main task did not request {label}: {writes}")
                run(LOOP, SEM_RESUME)
                require(value(CURRENT) == ui_thread, "page did not switch to the original UI thread")
                surface.events.clear()
                surface.pixel_writes.clear()
                run(SEM_RESUME, FRAME_COMPOSED, limit=10_000_000)
                glyphs = ["".join(chr(g["key"]) for g in e["glyphs"]) for e in surface.events]
                target = 11 if mode == 1 else 18
                require(("CW" in glyphs if mode == 1 else glyphs == ["MENU"]) and
                        any(w["target"] is None and w["source_target"] == target for w in surface.pixel_writes),
                        f"original UI did not compose {label}: {glyphs}")
                surface.select_target()
                original = bytes(surface.pixels)
                stock_image = png(surface.width, surface.height, original)
                (render_output / f"stock-before-cw-{label}.png").write_bytes(stock_image)
                surface.events.clear()
                run(names["cw_rtx_draw_bridge"], FRAME_COMPOSED+4)
                surface.select_target()
                extension_glyphs = ["".join(chr(g["key"]) for g in e["glyphs"]) for e in surface.events]
                rendered = bytes(surface.pixels)
                if mode == 2:
                    require(extension_glyphs == ["CW DECODE"], "ARM UI did not draw the CW shortcut")
                    width = surface.width*4
                    changed_rows = []
                    for y in range(surface.height):
                        start = y*width
                        before, after = original[start:start+width], rendered[start:start+width]
                        if before != after:
                            require(229 <= y < 266 and before[:36] == after[:36] and before[600:] == after[600:],
                                    f"ARM shortcut painted outside the MENU tile at row {y}")
                            changed_rows.append(y)
                    require(changed_rows == list(range(229, 266)), "ARM shortcut did not fill its tile")
                    (render_output / "arm-cw-menu.png").write_bytes(png(surface.width, surface.height, rendered))
                else:
                    require(not extension_glyphs and original == rendered, f"ARM extension altered {label}")
                run(FRAME_COMPOSED+4, IDLE)
                finish_frame()
                require(value(0x20380C8C) == 0, f"original UI did not retire {label}")
                pages.append(dict(label=label, page=mode, grid=slot, writes=writes, glyphs=glyphs,
                                  extension_glyphs=extension_glyphs, rgba_sha256=sha256(original).hexdigest(),
                                  with_extension_sha256=sha256(rendered).hexdigest(),
                                  png_sha256=sha256(stock_image).hexdigest()))
            capture(b"", before_pcm=touch_cw)
            run(LOOP, IDLE)
            require(read_session(cpu)["active"] and not rounds, "CW did not open from the stock MENU before PCM")
            return pages

        def draw_with_audio(wav, offset, *, control=False, overlay_stops=()):
            # Both the CW and UI tasks are runnable after capture.
            # Prepare the stock HOME backing frame while the offline CW test is active.
            prior = value(0x203807DD, 1)
            cpu.mem_write(0x203807DD, b"\x00")
            sub(UPDATE)
            cpu.mem_write(0x203807DD, bytes((prior,)))
            require(value(PAGE+1, 1) == 1, "stock update did not produce HOME")
            cpu.mem_write(PAGE, b"\x01")
            cpu.mem_write(0x204BD690, b"\x01")
            cpu.mem_write(0x20380C98, b"\x01")  # Request a full HOME render, not cached tiles.
            want_worker = bool(read_session(cpu)["queued"])
            run(LOOP, SEM_RESUME)
            require(value(CURRENT) == ui_thread and (screen or want_worker), "UI did not run as expected")
            surface.events.clear()
            surface.image_draws.clear()
            surface.pixel_writes.clear()
            surface.clears.clear()
            # Stop inside HOME after the original TX icon renderer.
            checkpoints = () if control else tuple(range(0x201637A4, 0x201637E5, 8))
            pc = SEM_RESUME
            for target in checkpoints:
                run(pc, target, limit=10_000_000)
                require(value(CURRENT) == ui_thread, "HOME checkpoint outside UI")
                part = wav[offset:offset+72]
                require(len(part) == 72, "not enough PCM for UI fixture")
                before = read_session(cpu)["queued"]
                state = capture(part, target)
                require(state["queued"] == before+6 and not state["drops"], "audio lost during stock draw")
                run(LOOP, target)
                require(value(CURRENT) == ui_thread, "UI did not resume after PCM")
                offset += len(part)
                pc = target
            end = FRAME_COMPOSED + (4 if screen else 0)
            run(pc, FRAME_COMPOSED, limit=10_000_000)
            overlay_instructions = 0
            irq_masked_run = irq_masked_peak = 0
            interrupts = []
            if screen:
                surface.select_target()
                stock_frame = bytes(surface.pixels)
                require(value(CURRENT) == ui_thread, "CW render did not start on the original UI thread")
                resume = names["cw_rtx_draw_bridge"]
                for stop_at in (*overlay_stops, None):
                    def count(c, address, *_):
                        nonlocal overlay_instructions, irq_masked_run, irq_masked_peak
                        psr = reg("CPSR")
                        if address == end or (stop_at is not None and overlay_instructions >= stop_at
                                              and not psr & 0xA0):
                            c.emu_stop()
                        else:
                            overlay_instructions += 1
                            if psr & 0x80:
                                irq_masked_run += 1
                                irq_masked_peak = max(irq_masked_peak, irq_masked_run)
                            else:
                                irq_masked_run = 0

                    hook = cpu.hook_add(uc.UC_HOOK_CODE, count)
                    try:
                        cpu.emu_start(resume, STOP, count=2_000_000)
                    finally:
                        cpu.hook_del(hook)
                    stopped = reg("PC")
                    if stop_at is None:
                        require(stopped == end, f"CW redraw did not finish: {stopped:#x}")
                        break
                    require(stopped != end and value(CURRENT) == ui_thread,
                            f"missed redraw checkpoint {stop_at}")
                    resume = stopped
                    part = wav[offset:offset+72]
                    require(len(part) == 72, "not enough PCM for interrupted CW frame")
                    before = read_session(cpu)
                    state = capture(part, stopped)
                    require(state["queued"] == before["queued"]+6 and not state["drops"],
                            "audio lost during CW redraw")
                    run(LOOP, stopped)
                    require(value(CURRENT) == ui_thread, "CW redraw did not resume after PCM")
                    interrupts.append(dict(pc=hex(stopped), instructions=overlay_instructions,
                                           queue=state["queued"], irq_enabled=True))
                    offset += len(part)
                top = 4*480*149
                require(stock_frame[:top] == surface.pixels[:top], "CW altered the original HOME header")
                if not read_session(cpu)["active"]:
                    require(stock_frame == surface.pixels, "closed CW changed stock HOME")
            require(any(w["target"] is None and w["source_target"] == 11
                                               for w in surface.pixel_writes),
                    f"stock HOME frame {len(frames)+1} not composed: {len(surface.image_draws)=}, "
                    f"writes={surface.pixel_writes}")
            surface.select_target()
            glyphs = ["".join(chr(g["key"]) for g in e["glyphs"]) for e in surface.events]
            require("CW" in glyphs and surface.image_draws, "stock HOME graphics or glyphs were skipped")
            rendered = png(surface.width, surface.height, surface.pixels)
            peak = read_session(cpu)["queued"]
            run(end, names["cw_lab_work"] if want_worker else IDLE, limit=10_000_000)
            require(value(0x20380CBE, 1) == 1, "UI did not wait for framebuffer completion")
            if want_worker:
                run(names["cw_lab_work"], IDLE)
            require(read_session(cpu)["queued"] == 0, "CW did not catch up after frame")
            finish_frame()
            record = dict(pcm_groups_during_draw=6*len(checkpoints), queue_at_completion=peak,
                          images=len(surface.image_draws), writes=len(surface.pixel_writes),
                          glyphs=glyphs, png_sha256=sha256(rendered).hexdigest())
            if screen:
                record.update(overlay_instructions=overlay_instructions, overlay_interrupts=interrupts,
                              max_consecutive_irq_masked=irq_masked_peak,
                              pcm_groups_during_draw=6*(len(checkpoints)+len(interrupts)))
            return offset, rendered, record

        def render_trial(wav, output):
            offset = 0
            control = None
            while offset < len(wav):
                part = wav[offset:offset+72]
                state = capture(part)
                require(state["queued"] == len(part)//12 and not state["drops"], "unexpected queue backlog")
                offset += len(part)
                if control is None:
                    offset, rendered, control = draw_with_audio(wav, offset, control=True)
                    (output / "stock-home-control.png").write_bytes(rendered)
                elif len(frames) < 3 and offset >= (2*72, 200*72, 800*72)[len(frames)]:
                    offset, rendered, record = draw_with_audio(wav, offset)
                    frames.append(record)
                    (output / f"stock-home-{len(frames)}.png").write_bytes(rendered)
                else:
                    run(LOOP, IDLE)
            final = read_session(cpu)
            require(len(frames) == 3 and observed == wav and final["text"] == "CQ TEST 123"
                    and final["fed"] == len(wav)//160 and not final["drops"] and queued_peak == 60
                    and all(frame["png_sha256"] == control["png_sha256"] for frame in frames)
                    and final["scope"] == pcm_ranges(wav), "draw contention changed CW reception")
            return dict(stock_main_sha256=digest, transcript=final["text"],
                        pcm_sha256=sha256(observed).hexdigest(), dma_groups=rounds,
                        queued_peak=queued_peak, dropped=final["drops"], frames=frames, control=control,
                        detector_calls=detector_calls, irq_eoi_count=len(eois), stages=stages)

        def overlay_trial(wav):
            checkpoints = (256, 2500, 6000, 11000, 18000, 22000, 27000, 56000, 74000)
            start_frames = range(26, len(wav)//72-10, 40)
            offset = 0
            while offset < len(wav):
                batch = offset//72
                part = wav[offset:offset+72]
                state = capture(part)
                require(state["queued"] == len(part)//12 and not state["drops"], "unexpected queue backlog")
                offset += len(part)
                if batch not in start_frames:
                    run(LOOP, IDLE)
                    continue
                offset, rendered, record = draw_with_audio(
                    wav, offset, control=True, overlay_stops=checkpoints if stress else ())
                require("CW DECODE" in record["glyphs"], "CW panel was not drawn")
                record.update(sample_offset=batch*36, text_at_redraw=state["text"])
                (render_output / f"{'stress' if stress else 'control'}-{len(frames)+1:02d}.png").write_bytes(rendered)
                frames.append(record)
                if not stress:
                    # Same audio arrives after the frame rather than preempting it.
                    for _ in checkpoints:
                        capture(wav[offset:offset+72])
                        run(LOOP, IDLE)
                        offset += 72
            final = read_session(cpu)
            require(len(frames) == len(start_frames) and observed == wav and final["text"] == "CQ TEST 123"
                    and final["fed"] == len(wav)//160 and not final["drops"]
                    and final["scope"] == pcm_ranges(wav), "CW redraw changed continuous reception")
            require(queued_peak == (60 if stress else 6), "CW redraw did not exercise the expected backlog")
            return dict(stock_main_sha256=digest, transcript=final["text"],
                        pcm_sha256=sha256(observed).hexdigest(), dma_groups=rounds, queued_peak=queued_peak,
                        dropped=final["drops"], frames=frames, detector_calls=detector_calls,
                        irq_eoi_count=len(eois), batches_between_redraws=start_frames.step, stages=stages)

        def replay(wav, expected, *, check_ui=False, before_pcm=None, fresh_wave=True):
            start = len(observed)
            for offset in range(0, len(wav), 72):
                part = wav[offset:offset+72]
                state = capture(part, before_pcm=before_pcm if offset == 0 else None)
                require(state["queued"] == len(part)//12 and not state["drops"],
                        f"main/worker handoff at {offset}: {state['queued']=}, {state['blocked']=}")
                if check_ui and offset == 0:
                    sub(0x2008F700)
                    run(LOOP, SEM_RESUME)
                    require(snapshot("ui-ahead-of-ready-cw") == ui_thread and read_session(cpu)["queued"] == 6,
                            "CW took precedence over UI")
                    # Exercise the stock UI wait path with the LCD closed. The
                    # stock-only scenario separately checks the draw dispatch.
                    cpu.mem_write(PAGE, b"\x00")
                    cpu.mem_write(0x204BD690, b"\x00")
                    run(SEM_RESUME, names["cw_lab_work"])
                    require(snapshot("cw-runs-when-ui-waits") == worker_thread, "CW did not follow UI wait")
                    run(names["cw_lab_work"], IDLE)
                else:
                    run(LOOP, IDLE)
            state = read_session(cpu)
            require(state["text"] == expected and observed[start:] == wav and not state["queued"]
                    and not state["drops"] and (not fresh_wave or state["scope"] == pcm_ranges(wav)),
                    f"scheduled decode failed: {state['text']!r}, taps={len(observed)}, groups={rounds}")
            checked_pcm.append(sha256(wav).hexdigest())
            return state

        def request(down):
            reply, _ = exchange_in_guest(cpu, bytes((0x1C, 0, down)), invoke=sub)
            require(reply[2:-1] == b"\xfb" and bool(value(FLAGS, 1) & 0x20) == down,
                    "stock TX request did not change")

        def adjust_trial():
            mixed, expected = adjacent_fixture()
            source_hash = sha256(mixed).hexdigest()
            mixed += bytes((-len(mixed)) % 480)
            def stock():
                pc = reg("PC")
                reply, _ = exchange_in_guest(cpu, b"\x03", invoke=sub)
                set_reg("PC", pc)
                return reply.hex(), value(KEY_SPEED_RAW, 1), value(KEY_HALF_MS, 2)
            idle = cpu.context_save()
            seed_key_speed(cpu, 85, invoke=sub)
            cpu.context_restore(idle)
            initial_settings = stock()
            require(initial_settings[1:] == (85, 120), "could not verify stock KEYER at 20 WPM")
            evidence = {}

            def choose(x, y):
                pc = reg("PC")
                cpu.mem_write(TOUCH_SAMPLE, TOUCH_UP)
                sub(TOUCH_POLL)
                touch(x, y)
                set_reg("PC", pc)

            def clear_text(now):
                pc = reg("PC")
                cpu.mem_write(HOLD_CLOCK, pack("<I", now))
                cpu.mem_write(TOUCH_SAMPLE, pack(">BHH", 0, 145, 253))
                sub(TOUCH_POLL)
                cpu.mem_write(HOLD_CLOCK, pack("<I", now+1000))
                sub(TOUCH_POLL)
                cpu.mem_write(TOUCH_SAMPLE, TOUCH_UP)
                sub(TOUCH_POLL)
                set_reg("PC", pc)
                require(not read_session(cpu)["text"], "clear did not reset transcript")

            def snapshot_frame(label, labels, marker=None, transcript=None):
                capture(b"")
                _, image, record = draw_with_audio(b"", 0, control=True)
                require(all(any(label == item.strip() for item in record["glyphs"]) for label in labels),
                        f"wrong LCD text for {label}: {record['glyphs']}")
                if transcript is not None:
                    glyphs = record["glyphs"]
                    rows = glyphs[glyphs.index("CW DECODE")+1:glyphs.index(WAVE_LABEL)]
                    require(" ".join(row.strip() for row in rows) == transcript,
                            f"wrong wrapped CW text for {label}: {rows}")
                if marker is not None:
                    p = surface.pixels
                    marker_rgba = b"\xff\xff\xff\xff"
                    x = FFT_X + ((marker-300)*(FFT_W-1)+475)//950
                    require(all(p[4*(480*y+x):4*(480*y+x)+4] == marker_rgba
                                for y in range(SCOPE_Y+30, SCOPE_Y+SCOPE_H, 4)),
                            f"missing native marker at {marker} Hz")
                (render_output / f"{label}.png").write_bytes(image)
                evidence[label] = record

            def play(pcm=mixed, track=None):
                pcm += bytes((-len(pcm)) % 480)
                start = len(observed)
                before = read_session(cpu)["fed"]
                for offset in range(0, len(pcm), 72):
                    group = pcm[offset:offset+72]
                    got = capture(group)
                    require(got["queued"] == len(group)//12, "ADJ test did not queue PCM")
                    run(LOOP, IDLE)
                    if track is not None and offset % 4752 == 0:
                        hz = read_session(cpu)["tracked_hz"]
                        if hz and (not track or hz != track[-1][1]):
                            track.append([(offset+len(group))//16, hz])
                state = read_session(cpu)
                require(observed[start:] == pcm and state["fed"]-before == len(pcm)//160 and
                        not state["queued"] and not state["drops"], "ADJ altered the PCM stream")
                return state["text"]

            wide = play()
            require(wide and wide != expected, "wide control did not reproduce interference")
            snapshot_frame("01-wide", [wide])
            clear_text(1000)
            choose(48, 253)
            choose(336, 253)
            snapshot_frame("02-adj", ["THRESH", "FILTER", "SPEED", "ADJ"])
            choose(138, 253)
            choose(138, 227)
            require(read_session(cpu)["fixed_hz"] == 600, "FIX did not select default 600 Hz")
            snapshot_frame("03-filter", ["FILTER FIX  600 HZ", "AUTO", "WIDE", "FIX"], marker=600)
            choose(428, 205)
            shifted = read_session(cpu)["fixed_hz"]
            require(shifted == 750, f"wrong scope tuning: {shifted}")
            snapshot_frame("04-filter-moved", ["FILTER FIX  750 HZ"], marker=750)
            choose(414, 205)
            require(read_session(cpu)["fixed_hz"] == 600, "could not return marker to 600 Hz")
            choose(50, 253)
            choose(52, 227)
            choose(235, 227)
            state = read_session(cpu)
            require(state["threshold"] == 600 and state["manual_threshold"], "manual threshold did not adjust")
            snapshot_frame("05-threshold", ["THRESH  600", "MANUAL", "-", "+"], marker=600)
            manual = play()
            require(manual != expected, "manual threshold control did not change the detector")
            choose(52, 227)
            choose(147, 227)
            require(not read_session(cpu)["manual_threshold"] and read_session(cpu)["threshold"] == 350,
                    "automatic threshold setting was not restored")
            choose(336, 253)
            choose(48, 253)
            clear_text(3000)
            fixed = play()
            require(fixed == expected, f"FIX failed to copy the weaker station: {fixed!r}")
            require(detector_calls == 3*len(mixed)//160 and fixed_calls == 2*len(mixed)//160,
                    "detector path or RTX counts did not match each mode")
            snapshot_frame("06-fixed-decoded", [expected], marker=600)
            clear_text(5000)
            choose(48, 253)
            choose(336, 253)
            choose(138, 253)
            choose(52, 227)
            require(read_session(cpu)["filter_mode"] == "AUTO", "AUTO did not enable the tracker")
            snapshot_frame("07-auto-idle", ["FILTER AUTO"])
            noise = mix([0]*(RATE//2), noise=850)
            require(not play(noise) and not read_session(cpu)["tracked_hz"], "AUTO chose a channel in noise")
            steady = []
            for hz, message, pcm in tracking_fixture():
                actual = play(pcm)
                expected_so_far = " ".join([r["message"] for r in steady] + [message])
                tracked = read_session(cpu)["tracked_hz"]
                require(actual == expected_so_far and tracked == hz,
                        f"AUTO did not follow {hz} Hz: {actual!r}, {tracked} Hz")
                snapshot_frame(f"08-auto-{hz}", [f"FILTER AUTO {hz} HZ", expected_so_far], marker=hz)
                steady.append(dict(message=message, transcript=actual, tracked_hz=tracked, pcm_sha256=sha256(pcm).hexdigest()))
            choose(336, 253)
            choose(48, 253)
            clear_text(7000)
            strongest = play()
            tracked = read_session(cpu)["tracked_hz"]
            require(strongest == "W9XYZ NR 51 CQ DE K8JZZ" and tracked == 700,
                    f"AUTO did not pick the stronger station on the FIX control: {strongest!r}, {tracked} Hz")
            snapshot_frame("09-auto-stronger", [strongest, "HOLD/CLR"], marker=700)

            drift, drift_expected, start_hz, end_hz = drifting_fixture()
            choose(48, 253)
            choose(336, 253)
            choose(138, 253)
            choose(138, 227)
            require(read_session(cpu)["fixed_hz"] == start_hz, "drift control was not tuned to its start")
            choose(336, 253)
            choose(48, 253)
            clear_text(9000)
            drift_fixed = play(drift)
            require(drift_fixed and drift_fixed != drift_expected, "FIX failed to reproduce drift losses")
            choose(48, 253)
            choose(336, 253)
            choose(138, 253)
            choose(52, 227)
            choose(336, 253)
            choose(48, 253)
            clear_text(11000)
            trace = []
            drift_auto = play(drift, track=trace)
            pitches = [hz for _, hz in trace]
            require(drift_auto == drift_expected and len(pitches) >= 5 and pitches == sorted(pitches)
                    and any((hz-300) % 50 for hz in pitches)
                    and abs(pitches[0]-start_hz) <= 10 and abs(pitches[-1]-end_hz) <= 10
                    and max(b-a for a,b in zip(pitches, pitches[1:])) <= 50,
                    f"AUTO did not follow smooth drift: {drift_auto!r}, {trace}")
            snapshot_frame("09a-auto-drift", ["HOLD/CLR"], marker=pitches[-1], transcript=drift_expected)
            require(stock() == initial_settings, "adjustment changed stock VFO or KEYER")
            key(1, 2)
            set_reg("PC", IDLE)
            state = read_session(cpu)
            require(not state["active"] and state["filter_mode"] == "WIDE" and not state["tracked_hz"] and
                    not state["fixed_hz"] and not state["adjust"] and not any(state["scope"]),
                    "machine EXIT did not discard adjustment state")
            snapshot_frame("10-exit", ["CW"])
            return dict(stages=stages, stock_main_sha256=digest, dma_groups=rounds, detector_calls=detector_calls,
                        fixed_detector_calls=fixed_calls, source_pcm_sha256=source_hash,
                        pcm_sha256=sha256(mixed).hexdigest(), stock_settings=initial_settings,
                        expected=expected, wide=wide, manual=manual, fixed=fixed, auto=steady,
                        auto_noise_output="", auto_strongest=dict(text=strongest, tracked_hz=tracked),
                        drift=dict(pcm_sha256=sha256(drift).hexdigest(), expected=drift_expected,
                                   fix=drift_fixed, auto=drift_auto, tracked_ms_hz=trace), frames=evidence)

        def screen_trial():
            tone = audio("T", trim_leading=True)[:72]
            receive_tone = audio("T", trim_leading=True)[:360]
            require(any(tone), "need nonzero side tone")

            def frame(label, icon, ci_v, *, blocked, text, before_pcm=None, stock=False, mailbox_key=None,
                      pcm=tone, flat=False, picker=False, speed_mode="AUTO", frozen=None):
                state = capture(pcm, before_pcm=before_pcm, mailbox_key=mailbox_key)
                blocked_before_draw = bool(state["blocked"])
                reply, _ = exchange_in_guest(cpu, b"\x1c\0", invoke=sub)
                require(reply[2:] == bytes((0x1C, 0, ci_v, 0xFD)), f"wrong original TX readback: {label}")
                _, image, record = draw_with_audio(b"", 0, control=True)
                finished = read_session(cpu)
                # No worker can consume new PCM in these frames; drawing itself
                # must reconcile TX feedback that arrives between audio batches.
                if not pcm:
                    require(not state["queued"] and finished["fed"] == state["fed"],
                            f"unexpected audio processing during frame: {label}")
                    state = finished
                require(bool(state["blocked"]) == blocked and state["text"] == text
                        and bool(state["active"]) != stock,
                        f"wrong CW state: {label} {state['active']=} {state['blocked']=} {state['text']=}")
                require(value(ICON_FIELD, 1) == icon and any(
                    entry["source"] == SPRITES[icon] and entry["matrix"][2] == 2
                    for entry in surface.image_draws), f"wrong original TX icon: {label}")
                copies = [w for w in surface.pixel_writes if w["source_target"] == 18 and w["target"] is None]
                require(len(copies) == int(not stock) and ("CW DECODE" in record["glyphs"]) != stock,
                        f"wrong CW composition: {label}")
                shown = text if frozen is None else frozen
                require(state["held"] == (frozen is not None) and state["shown_text"] == shown and
                        (("HOLD" in record["glyphs"]) == state["held"]), f"wrong HOLD state: {label}")
                if shown:
                    require(shown in record["glyphs"], f"stock font did not render CW text: {label}")
                if not stock:
                    borders = [entry for entry in surface.image_draws
                               if entry["source"] == "0x188a2a80" and entry["matrix"][3] == 31]
                    require([b["matrix"][2] for b in borders] == [2, 98, 194, 290, 386],
                            f"original softkey edges absent: {label}")
                    digits = str(state["speed_wpm"] or "--")
                    speed = [digits+" WPM", state["speed_mode"]]
                    chooser = ["SPEED", "AUTO", "LOCK", "MANUAL"] if picker else []
                    require(state["speed_picker"] == picker and state["speed_mode"] == speed_mode and
                            record["glyphs"][-len(speed+chooser):] == speed+chooser,
                            f"stock font did not render current CW speed: {label}, {state['speed_picker']=}, {record['glyphs']=}")
                pixels = surface.pixels
                rows = set()
                trace = []
                for x in range(SCOPE_X, SCOPE_X+WAVE_W):
                    base = 2*((x-SCOPE_X)*WAVE_BINS//WAVE_W)
                    low, high = state["scope"][base:base+2]
                    start = SCOPE_Y + 27 - int(high*26/32768)
                    end = SCOPE_Y + 27 - int(low*26/32768)
                    observed_y = [y for y in range(SCOPE_Y, SCOPE_Y+SCOPE_H)
                                  if pixels[4*(480*y+x):4*(480*y+x)+4] == b"\0\xff\0\xff"]
                    if not stock:
                        require(observed_y == list(range(start, end+1)), f"wrong PCM trace at {label}:{x}")
                    trace.append(len(observed_y) >= 3)
                    rows.update(observed_y)
                if stock:
                    require(not rows, "CW trace remained after EXIT")
                else:
                    require((len(rows) == 1) == (blocked or flat), f"wrong scope activity: {label}")
                record.update(label=label, tx_icon=icon, ci_v_tx=ci_v, rx_blocked=blocked, text=text,
                              shown_text=shown, held=state["held"],
                              fed=finished["fed"], wave_rows=len(rows), dma_groups_before_frame=len(pcm)//12,
                              blocked_before_draw=blocked_before_draw,
                              key_activity=value(KEY_ACTIVITY, 1), dsp_tx=bool(value(DSP_STATUS, 1) & DSP_TX),
                              tx_request=bool(value(FLAGS, 1) & 0x20),
                              stock_menu=value(0x203807dd, 1))
                if label == "05l-scope-dash-dot":
                    record["waveform_timing"] = check_waveform_marks(trace)
                (render_output / f"{label}.png").write_bytes(image)
                frames.append(record)
                return record

            def publish():
                for routine in (BUILD_REQUEST, FILTER_REQUEST, STATUS_TASK):
                    sub(routine)

            def dsp(active):
                cpu.mem_write(RAW_DSP_STATUS, pack("<I", (value(RAW_DSP_STATUS) & ~DSP_TX) |
                                                  (DSP_TX if active else 0)))
                sub(MIRROR_DSP_STATUS)

            replay(waveform, "CQ TEST 123")
            for offset in range(0, len(receive_tone), 72):
                capture(receive_tone[offset:offset+72])
                run(LOOP, IDLE)
            initial = frame("01-receiving", 1, 0, blocked=False, text="CQ TEST 123")
            # The isolated mailbox fixture can leave a pressed zero-coordinate
            # sample. Supply a release before a new intentional touch gesture.
            def choose(x, y):
                pc = reg("PC")
                cpu.mem_write(TOUCH_SAMPLE, TOUCH_UP)
                sub(TOUCH_POLL)
                touch(x, y)
                set_reg("PC", pc)

            frame("01-speed-chooser", 1, 0, blocked=False, text="CQ TEST 123", pcm=b"", picker=True,
                  before_pcm=lambda: choose(430, 158))
            def manual():
                seed_key_speed(cpu, 85, invoke=sub)
                choose(226, 227)

            manual_frame = frame("01-speed-manual", 1, 0, blocked=False, text="CQ TEST 123", pcm=b"",
                                 speed_mode="MANUAL", before_pcm=manual)
            require(value(KEY_SPEED_RAW, 1) == 85 and value(KEY_HALF_MS, 2) == 120 and
                    manual_frame["glyphs"][-2:] == ["20 WPM", "MANUAL"], "native MANUAL changed KEYER timing")

            def select_auto():
                choose(48, 254)
                require(read_session(cpu)["menu_two"], "native bottom menu did not page")
                choose(336, 253)
                choose(240, 253)
                choose(55, 227)
                choose(336, 253)
                choose(48, 254)

            chosen = frame("01-speed-auto", 1, 0, blocked=False, text="CQ TEST 123", pcm=b"",
                           before_pcm=select_auto)
            require(chosen["fed"] == initial["fed"], "SPEED touch changed the audio stream")

            language_address = PROFILES[digest].language_bytes
            languages = bytes(cpu.mem_read(language_address, 2))
            for x, y in ((430, 254), (160, 172), (44, 254), (269, 220),
                         (160, 186), (44, 254), (269, 220), (160, 203), (44, 254), (142, 220)):
                choose(x, y)
            state = read_session(cpu)
            require(state["color_open"] and state["colors"] == (0xffe7ffff, 0xffff00ff, 0x80dc00ff),
                    f"SET edited the wrong receive color: {state['colors']!r}")

            def color_frame(label):
                capture(b"")
                _, image, record = draw_with_audio(b"", 0, control=True)
                (render_output / f"{label}.png").write_bytes(image)
                frames.append(dict(label=label, **record))
                return record["glyphs"]

            requires = {"CW DECODE SET", "FFT Scope Color", "Signal Wave Color", "RX Font Color",
                        "R255 G231 B255", "R255 G255 B000", "R128 G220 B000"}
            require(requires <= set(color_frame("01-set-rx-colors")), "wrong SET glyphs")
            # Receive audio while the color page is open, using the original DMA task.
            for offset in range(0, len(receive_tone), 72):
                capture(receive_tone[offset:offset+72])
                run(LOOP, IDLE)
            after = read_session(cpu)
            require(after["fed"] > state["fed"] and after["text"] == state["text"],
                    "SET disrupted the live receiver")
            choose(430, 254)
            require("CQ TEST 123" in color_frame("01-set-applied"), "SET did not restore the transcript")
            original_colors = [e["rgba"] for e in surface.events
                               if "".join(chr(g["key"]) for g in e["glyphs"]) == "CQ TEST 123"]
            require(original_colors == ["80dc00ff"], "stock glyph painter did not apply the new RX color")
            def palette_has(x1, x2, y1, y2, rgba):
                p = surface.pixels
                return any(p[4*(480*y+x):4*(480*y+x)+4] == rgba for x in range(x1, x2) for y in range(y1, y2))
            require(palette_has(291, 379, 181, 235, bytes((255, 255, 0, 255))) and
                    palette_has(387, 474, 179, 203, bytes((255, 231, 255, 255))),
                    "original drawing task did not apply both trace colors")
            for x, y in ((430, 254), (160, 172), (336, 254), (160, 186), (336, 254),
                         (160, 203), (336, 254), (430, 254)):
                choose(x, y)
            require(not read_session(cpu)["color_open"] and not any(read_session(cpu)["colors"]),
                    "DEF did not reset all tested channels")
            chosen = frame("01-set-restored", 1, 0, blocked=False, text="CQ TEST 123", pcm=b"")
            keyed = frame("01a-key-down-with-outline", 1, 0, blocked=True, text="CQ TEST 123", mailbox_key=True)
            require(keyed["fed"] == chosen["fed"] and keyed["key_activity"] == 1 and not value(FLAGS, 1) & 0x20,
                    "decoder accepted local audio before any TX request")
            for offset in range(0, len(receive_tone), 72):
                capture(receive_tone[offset:offset+72], mailbox_key=False if offset == 0 else None)
                run(LOOP, IDLE)
            unkeyed = frame("01b-key-up-with-outline", 1, 0, blocked=False, text="CQ TEST 123")
            require(unkeyed["fed"] > keyed["fed"] and not unkeyed["key_activity"],
                    "decoder did not resume after the stock key-up input")
            feedback = frame("01c-feedback-only", 2, 0, blocked=True, text="CQ TEST 123",
                             before_pcm=lambda: dsp(True))
            require(feedback["dsp_tx"] and not feedback["tx_request"] and not feedback["key_activity"]
                    and feedback["fed"] == unkeyed["fed"], "DSP feedback alone did not stop decoding")
            for offset in range(0, len(receive_tone), 72):
                capture(receive_tone[offset:offset+72], before_pcm=(lambda: dsp(False)) if offset == 0 else None)
                run(LOOP, IDLE)
            cleared = frame("01d-feedback-cleared", 1, 0, blocked=False, text="CQ TEST 123")
            require(not cleared["dsp_tx"] and cleared["fed"] > feedback["fed"],
                    "decoder did not resume after DSP feedback cleared")
            requested = frame("02-request-before-solid-icon", 1, 0, blocked=True, text="CQ TEST 123",
                              before_pcm=lambda: request(True))
            transmitting = frame("03-solid-tx", 2, 1, blocked=True, text="CQ TEST 123",
                                 before_pcm=lambda: (publish(), dsp(True)))
            released = frame("04-rx-with-tx-feedback", 2, 0, blocked=True, text="CQ TEST 123",
                             before_pcm=lambda: (request(False), publish(), dsp(True)))
            require(cleared["fed"] == requested["fed"] == transmitting["fed"] == released["fed"],
                    "decoder accepted audio during transmit or either transition")
            require(initial["stock_menu"] == transmitting["stock_menu"] == 0,
                    "the stock menu was left open behind the CW overlay")
            replay(audio("DE IC705"), "CQ TEST 123 DE IC705", before_pcm=lambda: dsp(False))
            for offset in range(0, len(receive_tone), 72):
                capture(receive_tone[offset:offset+72])
                run(LOOP, IDLE)
            frame("05-receiving-again", 1, 0, blocked=False, text="CQ TEST 123 DE IC705")

            # A brief TX can begin and end without any HOME redraw. Check real
            # gate transitions even though the last rendered icon stays outlined.
            before = read_session(cpu)
            draws_before = len(surface.image_draws)
            short_tx = []
            for label, change, key_down, expected_ci_v in (
                ("key_down", None, True, 0),
                ("tx_confirmed", lambda: (request(True), publish(), dsp(True)), None, 1),
                ("key_up_feedback_still_on", lambda: (request(False), publish()), False, 0),
            ):
                capture(tone, before_pcm=change, mailbox_key=key_down)
                reply, _ = exchange_in_guest(cpu, b"\x1c\0", invoke=sub)
                run(LOOP, IDLE)
                state = read_session(cpu)
                require(reply[2:] == bytes((0x1C, 0, expected_ci_v, 0xFD))
                        and value(ICON_FIELD, 1) == 1 and state["blocked"]
                        and state["fed"] == before["fed"] and state["text"] == before["text"]
                        and not state["queued"] and not any(state["scope"]),
                        f"short TX escaped the audio gate: {label}")
                short_tx.append(dict(stage=label, displayed_icon=1, ci_v_tx=expected_ci_v,
                                     dsp_tx=bool(value(DSP_STATUS, 1) & DSP_TX), accepted_blocks=0))
            # The first incoming sample is already part of the dot for E.
            # Allow the decoder's 400 ms silence window for an isolated letter.
            recovered = replay(audio("E", trim_leading=True)+bytes(2400), before["text"]+" E",
                               before_pcm=lambda: dsp(False))
            require(value(ICON_FIELD, 1) == 1 and len(surface.image_draws) == draws_before,
                    "short TX did not occur entirely between redraws")
            for offset in range(0, len(receive_tone), 72):
                capture(receive_tone[offset:offset+72])
                run(LOOP, IDLE)
            after_short_tx = frame("05a-first-letter-after-unseen-tx", 1, 0, blocked=False, text=recovered["text"])

            # A flat receiving trace can be valid silence; it isn't a TX signal.
            for _ in range(143):  # 643.5 ms of silence replaces the 640 ms trace.
                capture(bytes(72))
                run(LOOP, IDLE)
            # The visual preview tone now has time to finish as another dot.
            silent_text = recovered["text"]+" E"
            silent = frame("05b-rx-silence", 1, 0, blocked=False, text=silent_text, pcm=b"", flat=True)
            require(silent["fed"] > after_short_tx["fed"], "silent RX did not reach the decoder")

            saved_gray = value(TX_GRAY_FLAGS, 1)
            for offset in range(0, len(receive_tone), 72):
                capture(receive_tone[offset:offset+72])
                run(LOOP, IDLE)
            gray_rx = frame("05c-gray-receiving", 3, 0, blocked=False, text=silent_text,
                            before_pcm=lambda: cpu.mem_write(TX_GRAY_FLAGS, bytes((saved_gray | 0x08,))))
            gray_tx = frame("05d-gray-feedback-no-pcm", 3, 0, blocked=True, text=silent_text,
                            pcm=b"", before_pcm=lambda: dsp(True))
            gray_side = frame("05e-gray-side-tone", 3, 0, blocked=True, text=silent_text)
            gray_clear = frame("05f-gray-cleared-no-pcm", 3, 0, blocked=False, text=silent_text,
                               pcm=b"", flat=True, before_pcm=lambda: dsp(False))
            require(gray_rx["fed"] == gray_tx["fed"] == gray_side["fed"] == gray_clear["fed"]
                    and not gray_tx["blocked_before_draw"] and gray_clear["blocked_before_draw"]
                    and gray_tx["png_sha256"] == gray_side["png_sha256"] == gray_clear["png_sha256"],
                    "gray icon drew stale samples or let side tone through")
            gray_recovered = replay(audio("E", trim_leading=True)+bytes(2400), silent_text+" E")
            for offset in range(0, len(receive_tone), 72):
                capture(receive_tone[offset:offset+72])
                run(LOOP, IDLE)
            resumed_gray = frame("05g-gray-resumed", 3, 0, blocked=False, text=gray_recovered["text"])
            require(resumed_gray["fed"] > gray_clear["fed"], "gray RX did not resume")
            cpu.mem_write(TX_GRAY_FLAGS, bytes((saved_gray,)))

            previous = gray_recovered["text"]
            frozen = frame("05h-hold", 1, 0, blocked=False, text=previous, frozen=previous,
                           before_pcm=lambda: choose(144, 254))
            live = previous + " E"
            replay(audio("E", trim_leading=True)+bytes(2400), live, fresh_wave=False)
            for offset in range(0, len(receive_tone), 72):
                capture(receive_tone[offset:offset+72])
                run(LOOP, IDLE)
            held_frame = frame("05i-hold-while-receiving", 1, 0, blocked=False, text=live, frozen=previous)
            require(held_frame["fed"] > frozen["fed"], "HOLD blocked original DMA")

            def hold_for_one_second():
                cpu.mem_write(TOUCH_SAMPLE, TOUCH_UP)
                sub(TOUCH_POLL)
                cpu.mem_write(TOUCH_SAMPLE, pack(">BHH", 0, 144, 254))
                sub(TOUCH_POLL)
                tick = value(HOLD_CLOCK)
                require(value(0x204BA014 + 134*4) == 0x20005994, "stock RTX tick IRQ not registered")
                for _ in range(HOLD_TICKS_PER_SECOND - 1):
                    irq(134, STOP)
                sub(TOUCH_POLL)
                require(value(HOLD_CLOCK) - tick == HOLD_TICKS_PER_SECOND - 1 and read_session(cpu)["held"],
                        "HOLD cleared before one second of stock RTX ticks")
                irq(134, STOP)
                sub(TOUCH_POLL)
                require(value(HOLD_CLOCK) - tick == HOLD_TICKS_PER_SECOND and not read_session(cpu)["text"],
                        "HOLD did not clear after one second of stock RTX ticks")
                cpu.mem_write(TOUCH_SAMPLE, TOUCH_UP)
                sub(TOUCH_POLL)

            clear_frame = frame("05j-hold-cleared", 1, 0, blocked=False, text="", pcm=b"",
                                before_pcm=hold_for_one_second)
            require(clear_frame["fed"] == held_frame["fed"], "long HOLD perturbed audio capture")

            def scope_tone(hz):
                # 0.6 seconds fills part of the history but leaves the previous tone below it.
                count = RATE*3//5
                pcm = pack(f"<{count}h", *(round(16000*sin(tau*hz*n/RATE)) for n in range(count)))
                for offset in range(0, len(pcm), 72):
                    capture(pcm[offset:offset+72])
                    run(LOOP, IDLE)
                state = read_session(cpu)
                frame(f"05k-scope-{hz}hz", 1, 0, blocked=False, text=state["text"], pcm=b"")

            def waterfall_peak(row):
                start = 4*(480*(SCOPE_Y+FFT_H+row)+FFT_X)
                colors = [sum(surface.pixels[i:i+3]) for i in range(start, start+4*FFT_W, 4)]
                require(max(colors) > 0, f"missing waterfall trace in native LCD row {row}")
                return FFT_X+colors.index(max(colors))

            scope_tone(600)
            first_peak = waterfall_peak(0)
            scope_tone(900)
            latest_peak, previous_peak = waterfall_peak(0), waterfall_peak(20)
            require(abs(first_peak-414) <= 3 and abs(latest_peak-441) <= 3 and previous_peak == first_peak,
                    f"native LCD did not retain the tones in order: {first_peak}, {latest_peak}, {previous_peak}")

            pattern = waveform_fixture()
            for offset in range(0, len(pattern), 72):
                capture(pattern[offset:offset+72])
                run(LOOP, IDLE)
            pattern_frame = frame("05l-scope-dash-dot", 1, 0, blocked=False, text=read_session(cpu)["text"], pcm=b"")

            def close():
                choose(430, 254)
                choose(269, 220)
                require(read_session(cpu)["color_open"] and any(read_session(cpu)["colors"]), "SET not active at exit")
                cpu.mem_write(TOUCH_SAMPLE, TOUCH_UP)
                key(1, 2)

            frame("06-exit", 1, 0, blocked=False, text="", stock=True, before_pcm=close)
            require(value(FRAME_COMPOSED) == 0xE59F0330, "stock frame instruction changed")
            require(not read_session(cpu)["color_open"] and not any(read_session(cpu)["colors"]),
                    "EXIT did not clear CW settings")
            require(bytes(cpu.mem_read(language_address, 2)) == languages and
                    value(KEY_SPEED_RAW, 1) == 85 and value(KEY_HALF_MS, 2) == 120, "SET changed stock settings")
            return dict(stock_main_sha256=digest, dma_groups=rounds, detector_calls=detector_calls,
                        stages=stages, frames=frames,
                        receive_color_set=dict(fft="ffe7ffff", wave="ffff00ff", glyph_rgba=original_colors[0],
                                               receive_continued=True, restored_by_def=True, cleared_on_exit=True),
                        right_scopes=dict(peak_600=first_peak, peak_900=latest_peak, older_600=previous_peak,
                                          waveform_timing=pattern_frame["waveform_timing"]),
                        between_redraws=dict(stages=short_tx, rendered_frames=0,
                                             first_received_letter="E", text=recovered["text"]))

        def preempt(action, label):
            # Queue enough audio to enter the detector, then drive preemption through the stock vectors.
            capture(audio("T", trim_leading=True)[:72])
            for _ in range(2):
                run(LOOP, IDLE)
                capture(audio("T", trim_leading=True)[:72])
            compute = names["cw_feed"] + 4
            run(LOOP, compute)
            require(value(CURRENT) == worker_thread and not reg("CPSR") & 0x80,
                    "did not reach an interruptible CW computation")
            before = read_session(cpu)["fed"]
            timer_wake(1, compute)
            run(LOOP, compute)
            timer_wake(2, compute)
            require(snapshot(f"{label}-preempted-worker") == main_thread, "interrupt did not switch to main")
            run(LOOP, TIMERS_CLEARED)
            action()
            run(LOOP, compute)
            require(snapshot(f"{label}-worker-resumes") == worker_thread, "worker context was not restored")
            run(compute, IDLE)
            return before

        if live:
            return live_trial()
        if stress is not None:
            return finish(overlay_trial(waveform))
        if screen:
            navigation = stock_menu_navigation()
            return finish(dict(adjust_trial() if adjust else screen_trial(), menu_before_audio=navigation))
        if graphics:
            return finish(render_trial(waveform, render_output))
        initial = replay(waveform, "CQ TEST 123", check_ui=True)
        require(initial["fed"] == len(waveform)//160, "worker lost a block on first replay")
        fed_before_tx = preempt(lambda: request(True), "tx")
        stopped = read_session(cpu)
        require(stopped["text"] == initial["text"] and stopped["blocked"] and not stopped["queued"]
                and stopped["fed"] == fed_before_tx and not any(stopped["scope"]),
                "TX let preempted work publish")
        stopped = capture(audio("VVV", trim_leading=True)[:72])
        require(stopped["blocked"] and not stopped["queued"] and stopped["text"] == initial["text"],
                "TX side tone reached worker")
        request(False)
        run(LOOP, IDLE)
        second = audio("DE IC705")
        resumed = replay(second, "CQ TEST 123 DE IC705")
        require(resumed["fed"] - fed_before_tx == len(second)//160,
                "worker lost or combined a block on return to reception")

        def close_reopen():
            cpu.mem_write(TOUCH_SAMPLE, TOUCH_UP)
            key(1, 2)
            require(not read_session(cpu)["active"], "original EXIT did not close CW")
            open_cw()

        preempt(close_reopen, "exit")
        reopened = read_session(cpu)
        require(reopened["active"] and not reopened["text"] and not reopened["fed"]
                and not any(reopened["scope"]), "old work reached the reopened session")
        state = replay(waveform, "CQ TEST 123")
        require(state["fed"] == len(waveform)//160, "worker lost a block on reopened replay")
        return finish(dict(stock_main_sha256=digest, svc_calls=svc_count, irq_eoi_count=len(eois),
                           stages=stages, dma_groups=rounds, queued_peak=queued_peak, detector_calls=detector_calls,
                           replay_pcm_sha256=checked_pcm, initial_text=initial["text"],
                           text_after_tx=resumed["text"], text_after_reopen=state["text"],
                           tx_and_exit_preempted_worker=True,
                           cw_thread=hex(worker_thread), cw_priority=value(worker_thread+2, 1)))

    for count in (1, 2):
        timer_wake(count, IDLE)
        require(snapshot(f"sgi-main-wake-{count}") == main_thread, "stock SGI did not schedule main")
        if count == 1:
            run(LOOP, IDLE)
            require(snapshot("main-waits-after-first-timer") == idle_thread and value(WAITER, 1) == 1,
                    "audio loop ran before it had two timer counts")
    run(LOOP, AUDIO_READY)
    require(snapshot("audio-ready-after-two-timers") == main_thread, "audio path did not run on main")
    run(AUDIO_READY, TIMERS_CLEARED)

    sub(0x2008F700)
    require(snapshot("ui-signaled-main-still-running") == main_thread, "UI preempted higher-priority main")
    run(LOOP, SEM_RESUME)
    require(snapshot("ui-runs-after-main-blocks") == ui_thread, "stock display semaphore did not wake UI")

    # Fixture: LCD HOME already open, so no display allocation or panel startup.
    cpu.mem_write(PAGE, b"\x01\x01")
    cpu.mem_write(0x204BD690, b"\x01")
    # A completed DMA buffer is a peripheral fixture, not a write into the stock ring.
    left, right = samples(0)
    words = [(sample & 0xFFFF) << 16 for pair in zip(left, right) for sample in pair]
    cpu.mem_write(LAYOUT["rec_bank"], pack("<72I", *words))
    cpu.mem_write(DMAC + 0xE4, pack("<I", 0xC1))
    for offset in (0x124, 0x424, 0x524):  # Other polled channels are running, with no completion.
        cpu.mem_write(DMAC + offset, pack("<I", 1))
    cpu.mem_write(AUDIO_GATE, b"\x01")
    cpu.mem_write(0x20380874, b"\x01")  # The board audio setup enables DMA polling.
    irq(DMA_TIMER, SEM_RESUME)
    require(snapshot("stock-dma-irq-during-ui") == ui_thread
            and value(LAYOUT["rec_ring"] + 0x240, 2) == 1, "stock DMA IRQ did not populate ring")
    # Deliver the interrupt during the UI's post-semaphore work, before touching the LCD.
    run(SEM_RESUME, 0x2013D5D0)
    ui_pc = reg("PC")
    for count in (1, 2):
        timer_wake(count, ui_pc)
        require(snapshot(f"ui-preempted-timer-{count}") == main_thread, "audio timer did not preempt UI")
        if count == 1:
            run(LOOP, ui_pc)
            require(snapshot("ui-resumed-without-pcm") == ui_thread
                    and value(LAYOUT["rec_ring"] + 0x240, 2) == 1, "first timer did not leave PCM for the second")
    run(LOOP, TIMERS_CLEARED)
    run(TIMERS_CLEARED, PCM_STEP)
    captured = []
    cpu.hook_add(uc.UC_HOOK_CODE, lambda c, *_: captured.append(unpack("<6h", c.mem_read(reg("SP")+8, 12))),
                 begin=DECIMATED, end=DECIMATED)
    run(PCM_STEP, PCM_DONE)
    require(snapshot("stock-pcm-after-ui-preemption") == main_thread and captured == [left[::6]],
            f"wrong decimated PCM after the context switch: {captured}")
    require(value(LAYOUT["rec_ring"] + 0x240, 2) == 0x0101, "stock ring did not drain")

    run(LOOP, ui_pc)
    require(snapshot("ui-resumes-after-pcm") == ui_thread, "UI did not resume after PCM")
    run(ui_pc, 0x2013D424)
    require(snapshot("ui-enters-stock-render-dispatch") == ui_thread, "stock drawing ran on the wrong thread")

    return dict(stock_main_sha256=digest, svc_calls=svc_count, sgis=sgis, irq_eois=eois,
                stock_pcm=captured, stages=stages)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("evidence", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--cw", action="store_true", help="also exercise an offline RTX decoder thread")
    mode.add_argument("--render", action="store_true", help="exercise stock rendering with the RTX decoder")
    mode.add_argument("--screen", action="store_true", help="render ARM CW text and scope over stock HOME")
    mode.add_argument("--live", action="store_true", help="exercise original UI requests with timed panel inputs")
    mode.add_argument("--rf-scope", action="store_true", help="compare original RF waterfall with CW off and on")
    mode.add_argument("--stress-screen", action="store_true", help="compare interrupted CW redraws with a control")
    mode.add_argument("--adjust-screen", action="store_true", help="check WIDE, FIX and AUTO with mixed PCM")
    parser.add_argument("--measure-worker-stack", action="store_true", help="observe original RTX stack allocation and writes")
    args = parser.parse_args()
    screen = args.screen or args.stress_screen or args.adjust_screen or args.live or args.rf_scope
    if args.measure_worker_stack and not (args.cw or args.render or screen):
        parser.error("--measure-worker-stack requires a CW replay mode")
    original = args.dat.read_bytes()
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as folder:
        images = load(original)
        extension = build(Path(folder), rtx=True) if args.cw or args.render or screen else None
        graphics = images if args.render or screen else None
        def run_trial(stress=None):
            return probe(images[0], extension, graphics=graphics, render_output=args.evidence.parent,
                         screen=screen, stress=stress, adjust=args.adjust_screen, measure_stack=args.measure_worker_stack,
                         live=args.live or args.rf_scope, rf_scope=args.rf_scope)

        if args.stress_screen:
            control, result = run_trial(False), run_trial(True)
            require(all(result[k] == control[k] for k in ("pcm_sha256", "transcript", "dma_groups", "detector_calls")),
                    "redraw contention changed PCM or CW text")
            for stopped, plain in zip(result["frames"], control["frames"], strict=True):
                require(all(stopped[k] == plain[k] for k in ("png_sha256", "sample_offset", "overlay_instructions")),
                        f"interrupted screen did not match its control: {stopped['sample_offset']}")
            result["control"] = control
            result["scope_scratch_bytes"] = 2*SCOPE_W*SCOPE_H
        else:
            result = run_trial()
    require(args.dat.read_bytes() == original, "original DAT changed")
    args.evidence.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(f"J140 stock scheduler: {len(result['stages'])} checkpoints; {args.evidence}")


if __name__ == "__main__":
    main()
