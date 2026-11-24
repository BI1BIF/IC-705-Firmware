"""Exercise DMR UI through the regional v1.4.0 touch poll, panel update and composition."""
from argparse import ArgumentParser
from hashlib import sha256
import json
from struct import pack, unpack_from

from tools.build_705_dmr_ui import BASE, ROOT, apply_hooks, link_ui
from tools.decode_705_main import decode_main
from tools.emulate_705 import call
from tools.probe_705_sstv_picture import tick
from tools.replay_705_aprs_fm import load_aprs_panel, original_fm
from tools.replay_705_aprs_task import e140_rom
from tools.replay_705_stock_install import A_PREFIX, load_a
from tools.verify_705_ftx_rx import compose

LAB=0x21200000
STATUS=LAB+0x2400


def run(region):
    source=ROOT/f".analysis/aprs-hop/smart-final/{region}/705{region}140.dat"
    out=ROOT/".analysis/digital-rx9/ui-fixture"/region
    program,work,sy=link_ui(out,region,LAB,LAB+0x1000,dict(
        dmr_rx_set_enabled=LAB+0x2001,dmr_ui_get_status=LAB+0x2021))
    dat=source.read_bytes()
    _,flash=load_a(dat,sha256(decode_main(dat)[1]).hexdigest())
    main=bytearray(decode_main(dat)[1])
    apply_hooks(main,region,sy)
    images,e=load_aprs_panel((ROOT/"firmware"/source.name).read_bytes())
    guest=original_fm(images,out,rom=e140_rom if e else None)
    c=guest.cpu
    c.mem_map(LAB,0x3000)
    c.mem_write(LAB,program)
    # Model only the backend ABI: set_enabled writes the enabled word and get_status returns its address.
    normal_enable=bytes.fromhex("01490860704700bf")+pack("<I",STATUS)
    c.mem_write(LAB+0x2000,normal_enable)
    c.mem_write(LAB+0x2020,bytes.fromhex("00487047")+pack("<I",STATUS))
    c.mem_write(STATUS,pack("<5I",0,0,*([0xffffffff]*3)))
    c.mem_write(BASE,bytes(main)); c.ctl_remove_cache(BASE,BASE+len(main))
    c.mem_write(0x185f0000,flash[:A_PREFIX])
    end=unpack_from("<I",main,0x2e8)[0]
    for pos in (end-32,end-16):
        src,dst,size,method=unpack_from("<4I",main,pos-BASE)
        call(c,method|1,src,dst,size)

    def screen(name,*labels):
        tick(guest)
        strings,picture=compose(guest)
        assert set(labels)<=set(strings),(name,labels,strings)
        picture.save(out/(name+".png"))
        return strings

    def tap(x,y):
        return guest.click(x,y,instruction_limit=2_000_000)

    def menu():
        tap(37,32)
        screen("mode","MODE","DV","FT8/4")

    def from_fm():
        menu(); tap(130,242); screen("stock-dv","DV")
        menu(); tap(130,242)

    def enabled():
        return int.from_bytes(c.mem_read(STATUS,4),"little")

    menu(); tap(130,242); screen("stock-dv","DV")
    assert not enabled() and c.mem_read(0x203e2128,1)[0]>>4==9
    menu(); tap(130,242)
    assert "FM" not in screen("search","DMR")
    assert enabled()==1 and c.mem_read(0x203e2128,1)[0]>>4==7
    row="GRP CC 7 ID 1234567 TG 3100"
    c.mem_write(STATUS+36,row.encode()+bytes(1))
    screen("group",row)
    guest._press_key(1,0)
    screen("mini-scope",row)
    guest.press_menu()
    screen("scope-menu","MENU")
    tap(52,80); screen("full-scope",row)
    assert c.mem_read(0x203e84c9,1)==bytes([9])
    tap(438,254); screen("expanded-scope",row)
    assert c.mem_read(0x204bab61,1)!=bytes(1)
    # A live spectrum usually refreshes without requesting a full HOME repaint.
    # Drive the stock caller model comparison after changing only the destination.
    from tools.emulate_705 import uc
    previous=unpack_from("<I",c.mem_read(guest.rom(0x201636f4),4))[0]
    drawn=[]
    callback=sy["digital_row_draw"]&~1
    h=c.hook_add(uc.UC_HOOK_CODE,lambda *_:drawn.append(True),begin=callback,end=callback)
    try:
        for message in (row[:-1]+"1","",row):
            c.mem_write(previous,bytes(c.mem_read(0x204bac6c,43)))
            c.mem_write(STATUS+36,message.encode()+bytes(1))
            call(c,sy["digital_row_prepare"],0)
            assert c.mem_read(previous,43)!=c.mem_read(0x204bac6c,43)
            call(c,guest.rom(0x20163518),0,instruction_limit=2000000)
        assert len(drawn)==3
    finally: c.hook_del(h)
    screen("incremental-restored",row)
    tap(438,254); screen("contracted-scope",row)
    guest.press_exit()
    screen("scope-exit",row)
    if call(c,guest.rom(0x200f1e48)): guest._press_key(1,0)
    screen("home-again",row)
    tap(319,191)
    assert enabled()==1
    guest.press_exit(); screen("physical-exit","DMR",row)
    assert enabled()==1
    menu(); tap(51,242); screen("explicit-fm","FM")
    assert not enabled()
    c.mem_write(STATUS+36,bytes(48))
    from_fm(); screen("repeat-start","DMR")
    menu(); tap(130,242); screen("fusion","YSF")
    guest.press_exit(); screen("exit-fusion","YSF")
    assert enabled()==2
    menu(); tap(130,242); screen("p25","P25")
    guest.press_exit(); screen("exit-p25","P25")
    assert enabled()==3
    menu(); tap(130,242); screen("switch-dv","DV")
    assert not enabled()
    c.mem_write(LAB+0x2000,bytes.fromhex("00207047"))
    c.ctl_remove_cache(LAB+0x2000,LAB+0x2020)
    for phase,title,action in ((4,"Check SD card","touch"),(5,"Start failed","physical"),
                               (4,"Check SD card","timeout")):
        c.mem_write(STATUS,pack("<5I",0,phase,*([0xffffffff]*3)))
        if c.mem_read(0x203e2128,1)[0]>>4==9:
            menu(); tap(130,242)
        else: from_fm()
        screen(f"error-{action}",title)
        assert not enabled()
        if action=="physical": guest.press_exit()
        elif action=="touch": tap(200,99)
        else:
            start=int.from_bytes(c.mem_read(0x20381e08,4),"little")
            c.mem_write(0x20381e08,pack("<I",(start+6000)&0xffffffff))
            tap(0,0)
        assert title not in screen(f"error-{action}-closed","FM")
    c.mem_write(LAB+0x2000,normal_enable)
    c.ctl_remove_cache(LAB+0x2000,LAB+0x2020)
    c.mem_write(STATUS+4,bytes(4))
    from_fm(); screen("retry","DMR")
    assert enabled()
    guest.press_exit()
    menu(); tap(431,192); screen("ft-selector","Digital","FT8","FT4")
    assert enabled()==1
    guest.press_exit(); screen("selector-cancel","DMR")
    menu(); tap(48,192); screen("selected-mode")
    call(c,sy["dmr_ui_input"])
    assert not enabled() and c.mem_read(0x203e2128,1)[0]>>4!=7
    result={"region":region,"baseline":sha256(dat).hexdigest(),"ui_bytes":len(program),
            "zero_initialized_bytes":work,"backend":"isolated fixture status ABI",
            "paths":["DV > DMR > group fields > EXIT","physical EXIT keeps digital RX","YSF and P25 active mode cycle",
                     "DMR > original DV","cancel FT8/4 selector, select analog mode","missing payload > touch EXIT",
                     "resource error > physical EXIT","six-second timeout","successful retry"]}
    (out/"ui-results.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(result,flush=True)


if __name__=="__main__":
    p=ArgumentParser(description=__doc__)
    p.add_argument("regions",nargs="*",default=["J","E"],choices=["J","E"])
    for region in p.parse_args().regions:
        run(region)
