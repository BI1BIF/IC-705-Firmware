"""Replay a retained FT session, factory RAM initialization and the original boot LCD."""

import json
from hashlib import sha256
from struct import pack

from tools.emulate_705 import arm, machine
from tools.replay_705_cw_upgrade import boot
from tools.verify_705_ftx_install import A_PREFIX, BOOT_SIZE, NOR_BYTES, SELECTOR, SHARED, unpack
from tools.verify_705_ftx_rx import BASE, OUT, ROOT, SettingsGuest, call, load, symbols, val


def retained_session(stock, main, sy):
    panel = SettingsGuest(stock, front_panel=True)
    cpu = panel.cpu
    cpu.mem_write(BASE, main)
    cpu.ctl_remove_cache(BASE, BASE + len(main))
    for name, value in (("state", 2), ("ft_page", 1), ("stage", 1), ("painted_outputs", 3)):
        cpu.mem_write(sy[name], pack("<I", value))
    cpu.mem_write(0x203E1F23, bytes.fromhex("00 01 95 00 69"))  # pressed at 405,105
    for scene in (0, 4, 0x3D):
        cpu.mem_write(0x204BAB5D, bytes([scene]))
        panel.surface.events.clear()
        panel.surface.pixel_writes.clear()
        call(cpu, sy["ftx_frame"])
        assert not panel.surface.events and not panel.surface.pixel_writes
        assert not call(cpu, sy["ftx_touch"])
    for index in range(2):
        cpu.mem_write(0x20380CBC, bytes([index]))
        cpu.mem_write(0x20380C98, b"\0")
        call(cpu, sy["ftx_prepare_frame"])
        assert val(cpu, 0x20380C98, 1) & 1
    assert not val(cpu, sy["painted_outputs"])
    call(cpu, sy["ftx_input"])
    assert not val(cpu, sy["state"]) and not val(cpu, sy["stage"])

    cpu = machine(main)
    reset_fields = ("state", "ft_page", "stage", "painted_outputs", "ftx_memory", "ft_auto_armed", "thread", "display_suspended")
    for name in reset_fields:
        cpu.mem_write(sy[name], b"\xa5" * 4)
    cpu.emu_start(0x200052C9, 0x200052A8, count=12000000)
    assert cpu.reg_read(arm.UC_ARM_REG_PC) == 0x200052A8
    assert all(not val(cpu, sy[name]) for name in reset_fields)
    return dict(factory_scenes=[0, 4, 0x3D], invalidated_outputs=[0, 1],
                session_closed=True, reset_fields=reset_fields)


def display_lifecycle(stock, main, sy, preserve):
    outcomes=[]
    for latch in (0x20380721,0x2038072a):
        p=SettingsGuest(stock,front_panel=True)
        c=p.cpu
        c.mem_write(BASE,main)
        c.ctl_remove_cache(BASE,BASE+len(main))
        for name,value in (("state",2),("ft_page",2),("first",7),("ft_selected",9)):
            c.mem_write(sy[name],pack("<I",value))
        c.mem_write(latch,b"\1")
        c.mem_write(0x204BAB5D,b"\4")
        call(c,sy["ftx_input"])
        asleep=val(c,sy["state"])
        c.mem_write(latch,b"\0")
        call(c,sy["ftx_input"])  # latch clears before HOME is visible
        c.mem_write(0x204BAB5D,b"\1")
        call(c,sy["ftx_input"])  # hardware-key wake, no touch
        after=val(c,sy["state"])
        assert (asleep,after)==((2,2) if preserve else (0,0))
        if preserve:
            assert [val(c,sy[n]) for n in ("ft_page","first","ft_selected")]==[2,7,9]
            c.mem_write(0x20380431,b"\x09")
            call(c,sy["ftx_input"])
            assert not val(c,sy["state"])
        outcomes.append(dict(latch=hex(latch),asleep=asleep,awake=after))
    return outcomes


def main():
    dat = (OUT / "bench-rx.dat").read_bytes()
    stock_dat = (ROOT / "firmware/705J140.dat").read_bytes()
    stock = load(stock_dat)
    main, target = unpack(dat)
    retained = retained_session(stock, main, symbols(OUT / "rx.elf"))
    previous=OUT.parent/"j140-ftx-tx2f"
    old,_=unpack((previous/"bench-rx.dat").read_bytes())
    sleep_comparison={"TX2f":display_lifecycle(stock,old,symbols(previous/"rx.elf"),False),
                      "candidate":display_lifecycle(stock,main,symbols(OUT/"rx.elf"),True)}
    _, original = unpack(stock_dat)
    nor = bytearray(b"\xff" * NOR_BYTES)
    nor[:A_PREFIX] = target[:A_PREFIX]
    nor[A_PREFIX:SELECTOR] = original[BOOT_SIZE:A_PREFIX]
    nor[SHARED:SHARED + len(original) - A_PREFIX] = original[A_PREFIX:]
    image = (main, stock[1], stock[2], sha256(main).hexdigest(), stock[4])
    result, frames = boot(bytes(nor), image)
    assert result["nor_boot"]["application_sha256"] == image[3]
    baseline = ROOT / ".analysis/cw-packaged-boot-1115/stock-control"
    names = ("boot-first-lcd", "boot-progress-mask", "boot-progress-lcd", "boot-full-lcd")
    for name, frame in zip(names, frames):
        assert frame == (baseline / (name + ".png")).read_bytes(), name
    report = dict(dat_sha256=sha256(dat).hexdigest(), retained=retained, display_wake=sleep_comparison,
                  startup_frames_matching_stock=names, home_menu_exit=result["panel"]["exit_committed"])
    (OUT / "restart.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
