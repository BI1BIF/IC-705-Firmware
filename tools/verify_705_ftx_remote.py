"""Replay the Passport scope-on and reconnect sequence on both FT builds."""
import json
from hashlib import sha256
from unittest.mock import patch

from tools import render_705_stock_row as renderer
from tools.verify_705_ftx_rx import (
    BASE, INIT_RANGES, MODE_UI_A, MODE_VFO_A, OUT, ROOT, SELECT_VFO, SettingsGuest,
    call, compose, decode_main, load, map_atlas, menu_init, seed_vfos, symbols, tick, val,
)
from tools.replay_705_vfo_split import exchange_in_guest


def trial(folder, before):
    dat = (folder / "bench-rx.dat").read_bytes()
    main = bytes(decode_main(dat)[1])
    sy = symbols(folder / "rx.elf")
    with patch.object(renderer, "HEAP_START", 0x20700000):
        p = SettingsGuest(load((ROOT / "firmware/705J140.dat").read_bytes()), front_panel=True)
    c = p.cpu
    c.mem_write(BASE, main)
    c.ctl_remove_cache(BASE, BASE + len(main))
    map_atlas(c, dat)
    menu_init(c, main)
    seed_vfos(c, (14074000, 14080000))
    call(c, INIT_RANGES)
    call(c, SELECT_VFO[0])
    for a in (MODE_VFO_A, MODE_UI_A):
        c.mem_write(a, bytes([0x20]))
    worker = p.surface.alloc(5120)
    c.mem_write(worker,bytes(5120))
    c.mem_write(worker+0x700,(1).to_bytes(4,'little'))
    c.mem_write(sy['cw_state_anchor'],worker.to_bytes(4,'little'))
    from tools.emulate_705 import uc, arm
    def wake(cpu,*_):
        cpu.reg_write(arm.UC_ARM_REG_R0,0)
        cpu.reg_write(arm.UC_ARM_REG_PC,cpu.reg_read(arm.UC_ARM_REG_LR))
    c.hook_add(uc.UC_HOOK_CODE,wake,begin=0x202d4850,end=0x202d4850)
    p.render()

    def cmd(hex_string):
        return exchange_in_guest(c, bytes.fromhex(hex_string))[0][2:-1]

    def subscribe():
        assert cmd("27 10 01") == b"\xfb"
        call(c, sy["ftx_input"])
        assert cmd("27 11 01") == b"\xfb"

    if before:
        subscribe()
    for x,y in ((37,32), (431,192), (120,79)):
        p.click(x,y)
        tick(p)
        compose(p)
    assert val(c, sy["state"]) == 1, (before,val(c,sy["state"]),val(c,0x203e84c9,1))
    call(c, sy["ftx_step"], instruction_limit=0)
    assert val(c, sy["state"]) == 2
    entered = {"screen":cmd("27 10").hex(), "output":cmd("27 11").hex()}
    if before:
        assert cmd("27 11") == bytes.fromhex("27 11 01")
    subscribe()
    state = val(c, sy["state"])
    page = val(c, 0x203e84c9, 1)
    assert page == 9
    if folder==OUT:
        assert state==2
        labels, image = compose(p)
        assert "FT8" in labels
        image.save(OUT / "esp32-scope-on.png")
        p.click(440,249)
        assert val(c, sy["ft_page"]) != 0
        p.click(440,249)
        p.press_exit()
        tick(p)
        assert val(c, sy["state"]) == 3
    else:
        assert state==3
    return dict(dat_sha256=sha256(dat).hexdigest(), entered=entered,
                after_scope_on=dict(factory_page=page, ft_state=state))


if __name__ == "__main__":
    data={"tx2h":trial(OUT.parent/"j140-ftx-tx2h",False),
          "subscribe_after":trial(OUT,False), "subscribe_before":trial(OUT,True)}
    data["dat_sha256"]=data["subscribe_after"]["dat_sha256"]
    (OUT/"remote.json").write_text(json.dumps(data,indent=2))
    print(data)
