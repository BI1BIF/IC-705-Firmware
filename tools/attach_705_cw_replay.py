"""Attach the CW lab to a running J140 ARM emulator, using its original RTX."""

from struct import pack, unpack

from tools.emulate_705 import arm, uc
from tools.probe_705_cw_pcm import TEST_STATE
from tools.probe_705_cw_session import INPUT, TOUCH_HIT, Lab, RTX_CODE, RTX_MEMORY, SCOPE_CANVAS, SCOPE_MEMORY
from tools.render_705_stock_row import require


CURRENT, UI_HANDLE = 0x20381E90, 0x20380CC4
FRAME_COMPOSED = 0x2013D4A8
CREATE_THREAD = 0x202D48C1
STATE_RESERVATION = 4096
WORKER_STACK_REQUEST = 4096
STOCK_CANVAS_OFFSET = 0x714  # Immediately after the 16-byte thread descriptor.
STOCK_CANVAS_ALLOCATION = 0x718


def allocate_heap(cpu, size, *, schedule_marker):
    """Reserve private memory from the original heap in the offline guest."""
    ctx = cpu.context_save()
    original, = unpack("<I", cpu.mem_read(CURRENT, 4))
    pending = schedule_marker()
    resume = cpu.reg_read(arm.UC_ARM_REG_PC)
    require(cpu.reg_read(arm.UC_ARM_REG_CPSR) & 0xBF == 0x1F and original and not pending,
            "stock allocator requires the interruptible main task")
    try:
        cpu.reg_write(arm.UC_ARM_REG_R0, size)
        # Return to the paused stock instruction; the flat-only STOP is not executable with the stock map.
        cpu.reg_write(arm.UC_ARM_REG_LR, resume)
        cpu.emu_start(0x20127A28, resume, count=200_000)
        ptr = cpu.reg_read(arm.UC_ARM_REG_R0)
        require(cpu.reg_read(arm.UC_ARM_REG_PC) == resume and ptr and not ptr & 7 and
                unpack("<I", cpu.mem_read(CURRENT, 4))[0] == original and schedule_marker() == pending,
                "stock heap allocation failed or unexpectedly switched tasks")
    finally:
        cpu.context_restore(ctx)
    return ptr


def allocate_state(cpu, *, schedule_marker):
    ptr = allocate_heap(cpu, STATE_RESERVATION, schedule_marker=schedule_marker)
    cpu.mem_write(ptr, bytes(STATE_RESERVATION))
    return ptr


def attach(cpu, extension, *, draw, schedule_marker, stock_canvas=False, state=TEST_STATE, code_base=None,
           code_request=0, hook_input=True):
    """Create only the test task; retain the booted main task and its stack."""
    code, bridges, symbols = extension

    def word(address):
        return unpack("<I", cpu.mem_read(address, 4))[0]

    main, ui = word(CURRENT), word(UI_HANDLE)
    status = cpu.reg_read(arm.UC_ARM_REG_CPSR)
    require(main and ui and main != ui and status & 0xBF == 0x1F and
            cpu.mem_read(main+2, 1) == b"\xf4" and cpu.mem_read(ui+2, 1) == b"\xee",
            "CW attachment requires the running, interruptible stock main task")
    require(len(code) <= RTX_MEMORY and bridges.keys() == Lab.stock.keys() and all(
        cpu.mem_read(site, 4).hex() == opcode for site, opcode in Lab.stock.items()),
        "unexpected J140 CW hook instructions or test section")
    if draw:
        require(word(FRAME_COMPOSED) == 0xE59F0330, "unexpected J140 composition instruction")
        bridges = {**bridges, FRAME_COMPOSED: symbols["cw_rtx_draw_bridge"]}

    anchor = symbols.get("cw_state_anchor")
    require(bool(anchor) == (state != TEST_STATE), "CW build and state layout differ")
    if not anchor:
        cpu.mem_map(TEST_STATE, STATE_RESERVATION)
    if code_base is None:
        base = RTX_CODE
        cpu.mem_map(base, RTX_MEMORY)
    else:
        base = code_base
        require(anchor and stock_canvas and base % 8 == 0 and len(code) <= code_request and
                word(base-4) == ((code_request+11) & ~7),
                "CW test code requires a block reserved by the original allocator")
    require(all(base <= p < base+len(code) for p in (*bridges.values(), symbols["cw_rtx_worker"])),
            "CW entry points are outside their linked block")
    cpu.mem_write(base, code)
    if anchor:
        require(base <= anchor <= base+len(code)-4 and not word(anchor), "invalid CW state anchor")
        cpu.mem_write(anchor, pack("<I", state))
    if code_base is None:
        cpu.mem_protect(base, RTX_MEMORY, uc.UC_PROT_READ | uc.UC_PROT_EXEC)
    if draw and not stock_canvas:
        cpu.mem_map(SCOPE_CANVAS, SCOPE_MEMORY)

    descriptor = state+0x704
    cpu.mem_write(descriptor, pack("<4I", symbols["cw_rtx_worker"], 0xE8, 1, WORKER_STACK_REQUEST))
    context = cpu.context_save()
    scheduling = schedule_marker()
    resume = cpu.reg_read(arm.UC_ARM_REG_PC)
    try:
        cpu.reg_write(arm.UC_ARM_REG_R0, descriptor)
        cpu.reg_write(arm.UC_ARM_REG_R1, 0)
        cpu.reg_write(arm.UC_ARM_REG_LR, resume)
        cpu.emu_start(CREATE_THREAD, resume, count=200_000)
        thread = cpu.reg_read(arm.UC_ARM_REG_R0)
        require(cpu.reg_read(arm.UC_ARM_REG_PC) == resume and word(CURRENT) == main and
                schedule_marker() == scheduling and thread not in (0, main, ui) and
                cpu.mem_read(thread+2, 1) == b"\xe9", "stock RTX did not create CW without rescheduling")
    finally:
        cpu.context_restore(context)

    cpu.mem_write(state+0x700, pack("<I", thread))
    for site, target in bridges.items():
        if not hook_input and site in (INPUT, TOUCH_HIT):
            continue  # The exact application supplies these two branches.
        cpu.hook_add(uc.UC_HOOK_CODE, lambda c, *_, dest=target: c.reg_write(arm.UC_ARM_REG_PC, dest),
                     begin=site, end=site)
    cpu.ctl_flush_tb()  # At cold boot the three stock blocks may already be translated.
    return thread
