"""Capture FUNCTION and HOME via the installed regional firmware and physical input path."""
from struct import pack
from tools.emulate_705 import call
from tools.emulate_705 import uc
from tools.render_705_display import PAGE
from tools.verify_705_aprs_overlay import LINK
from tools.verify_705_ftx_rx import symbols


def exercise(g,folder,manager,gps,*,scope_test=None):
    out=folder/"screens"
    out.mkdir(exist_ok=True)
    cpu=g.cpu
    def word(addr): return int.from_bytes(cpu.mem_read(addr,4),"little")
    def settle():
        size=0x204bd690-PAGE
        cpu.mem_write(0x204bd690,bytes(cpu.mem_read(PAGE,size)))
        cpu.mem_write(0x20380c98,bytes(2))
    def prepare(): call(cpu,manager["aprs_overlay_prepare"],instruction_limit=4000000)
    def screen(name,*labels):
        words,image=g.render()
        (out/(name+".png")).write_bytes(image)
        assert set(labels)<=set(words),(name,words)
        return words
    def enter():
        g._press_key(0,7);g.render()
        if not cpu.mem_read(0x203e8500,1)[0]: g.click(275,251)
    def select(row):
        g.click(334,62,instruction_limit=4_000_000);screen("mode-picker","APRS Mode","OFF","RX Only","RX & TX")
        g.click(150,55+row*61);prepare()
    enter()
    screen("01-function-off","FUNCTION","APRS","AUTO BCN","OFF")
    g.click(429,64)
    assert not word(manager["bound_hz"])
    select(1);screen("02-receive-only","RX Only","AUTO BCN")
    g.click(429,64)
    base=word(manager["loaded"])
    sy=symbols(folder/"aprs-task.elf")
    def addr(name): return base+sy[name]-LINK
    assert not cpu.mem_read(addr("aprs_auto_beacon"),1)[0]
    select(2)
    screen("03-auto-off","RX & TX","OFF")
    g.press_exit()
    words=screen("04-home-auto-off","APRS","FM")
    assert "BCN" not in words
    gps();g.press_exit();g.render()
    g.click(145,174);screen("settings","Beacon Interval  10 min")
    g.click(150,239);screen("interval","1 min")
    g.click(150,55);screen("interval-selected","Beacon Interval  1 min")
    for _ in range(4):
        g.press_exit();g.render()
        if cpu.mem_read(0x204bab5d,1)==b"\x01" and not cpu.mem_read(0x203e1a28,2).strip(b"\0"):break
    enter();g.render();settle();before=g.render()[1];settle();g.click(429,64)
    screen("05-function-armed","APRS","AUTO BCN","ON  1 min","RX & TX")
    assert (out/"05-function-armed.png").read_bytes()!=before
    if not scope_test and "motion" in sy:
        cpu.mem_write(addr("aprs_beacon_interval"),b"\x05")
        screen("05b-function-smart","AUTO BCN","ON  SMART")
        cpu.mem_write(addr("aprs_beacon_interval"),b"\x00")
    g.press_exit();screen("06-home-armed","APRS","BCN","FM")
    now=word(0x20381e08);due=(now+60999)//1000*1000
    cpu.mem_write(0x2038026c,b"\x01")
    def tick(clock):
        cpu.mem_write(0x20381e08,pack("<I",clock))
        call(cpu,manager["aprs_slot_update"])
    if scope_test:
        from PIL import Image,ImageChops
        # Compare actual LCD pixels with the radio on and off its bound frequency.
        g._press_key(1,0)  # Physical M.SCOPE from ordinary FM HOME.
        hz=word(manager["bound_hz"])
        display_binding=hz
        def scope_status(c,*_):
            c.mem_write(manager["bound_hz"],pack("<I",display_binding))
            for offset,value in ((47,3),(55,4),(56,1),(58,1)):
                c.mem_write(PAGE+offset,bytes([value]))
        draw=g.rom(0x201636f8)
        hook=cpu.hook_add(uc.UC_HOOK_CODE,scope_status,begin=draw,end=draw)
        try:
            labels=screen("scope-armed","FM")
            style=cpu.mem_read(PAGE+5,1)[0]
            assert style==2 and word(manager["bound_hz"])==word(0x20380714) and cpu.mem_read(addr("aprs_auto_beacon"),1)[0]
            if scope_test=="scope-baseline":
                assert "APRS" not in labels and "BCN" not in labels,labels
                return dict(scope_style=style,enabled_on_bound_channel=True,missing_on_scope=True)
            assert {"APRS","BCN"}<=set(labels),(style,labels)
            # Change only the binding for the reference frame, leaving the VFO and scope fixed.
            settle();display_binding=hz+5000
            screen("scope-off-frequency","APRS","BCN")
            cpu.mem_write(manager["bound_hz"],pack("<I",hz))
            settle();display_binding=0
            assert "APRS" not in screen("scope-disabled")
            cpu.mem_write(manager["bound_hz"],pack("<I",hz))
            settle();display_binding=hz
            screen("scope-return","APRS","BCN")
            armed=Image.open(out/"scope-armed.png").convert("RGB")
            away=Image.open(out/"scope-off-frequency.png").convert("RGB")
            assert ImageChops.difference(armed,away).getbbox()==(132,5,166,16)
            off=Image.open(out/"scope-disabled.png").convert("RGB")
            restored=Image.open(out/"scope-return.png").convert("RGB")
            box=ImageChops.difference(armed,off).getbbox()
            assert box==(132,5,197,16) and not ImageChops.difference(armed,restored).getbbox(),box
            cpu.mem_write(0x2038026c,b"\x01")
            settle();tick((word(0x20381e08)+61999)//1000*1000)
            assert word(addr("auto_waiting"))
            screen("scope-wait-lit")
            lit=Image.open(out/"scope-wait-lit.png").convert("RGB")
            assert not ImageChops.difference(armed,lit).getbbox()
            settle();tick(word(0x20381e08)+500)
            assert "BCN" not in screen("scope-wait-dark","APRS")
            dark=Image.open(out/"scope-wait-dark.png").convert("RGB")
            assert ImageChops.difference(armed,dark).getbbox()==(171,6,197,16)
        finally:
            cpu.hook_del(hook)
        return dict(scope_style=style,labels_bounds=box,off_frequency_aprs_dimmed=True,only_bcn_blinks=True)
    tick(due)
    assert word(addr("auto_waiting")) and not word(addr("stage"))
    screen("07-wait-lit","APRS","BCN")
    settle()
    tick(due+500)
    assert "BCN" not in screen("08-wait-dark","APRS")
    settle();tick(due+1000);screen("09-wait-lit","APRS","BCN")
    assert (out/"07-wait-lit.png").read_bytes()==(out/"09-wait-lit.png").read_bytes()
    assert (out/"08-wait-dark.png").read_bytes()!=(out/"09-wait-lit.png").read_bytes()
    # Drive the same OEM status painters with and without APRS, including
    # incremental moves into an empty run and restoration of the old pixels.
    from PIL import Image,ImageChops
    draw=g.rom(0x201636f8)
    cases=[
        ("battery",{},132),
        ("battery-wifi-sd",{55:4,58:1},132),
        ("occupied-near-battery",{48:1},198),
        ("occupied-middle",{48:1,51:1},264),
        ("crowded",{48:1,51:1,55:1},44),
        ("full",{41:1,42:1,48:1,51:1,55:1},0),
        ("near-battery-again",{},132),
    ]
    def indicators(armed):
        for index,(name,flags,x) in enumerate(cases):
            settle()
            if not index: cpu.mem_write(0x20380c98,b"\x01\0")
            def status(c,*_):
                for offset in (41,42,43,47,48,49,51,52,53,54,55,56,58):
                    c.mem_write(PAGE+offset,bytes([3 if offset==47 else flags.get(offset,0)]))
            hook=cpu.hook_add(uc.UC_HOOK_CODE,status,begin=draw,end=draw)
            try:
                screen(name+("-and-beacon" if armed else "-stock"))
            finally:
                cpu.hook_del(hook)
    indicators(True)
    gps();g.press_exit();g.render();g.click(145,174)
    screen("shared-gps-settings","Auto Beacon  ON","Beacon Interval  1 min")
    for _ in range(4):
        g.press_exit();g.render()
        if cpu.mem_read(0x204bab5d,1)==b"\x01" and not cpu.mem_read(0x203e1a28,2).strip(b"\0"):break
    enter();g.render();g.click(429,64);screen("10-auto-stopped","RX & TX","OFF")
    select(0);screen("11-disabled","APRS","OFF")
    g.press_exit();assert "APRS" not in screen("12-home-disabled","FM")
    indicators(False)
    bounds={}
    for name,_,x in cases:
        armed=Image.open(out/(name+"-and-beacon.png")).convert("RGB")
        stock=Image.open(out/(name+"-stock.png")).convert("RGB")
        diff=ImageChops.difference(armed,stock)
        box=diff.getbbox()
        if not x:
            assert box is None,(name,box)
            continue
        width=52 if x==44 else 66
        assert box and x<=box[0]<box[2]<=x+width and 0<=box[1]<box[3]<=20,(name,box)
        tx=stock.crop((1,0,42,21)).getbbox()
        tx_center=(tx[1]+tx[3]-1)/2
        split=x+(29 if x==44 else 38)
        centers=[]
        for left,right in ((x,split),(split,x+width)):
            ink=diff.crop((left,0,right,20)).getbbox()
            assert ink,(name,left)
            centers.append((ink[1]+ink[3]-1)/2)
        assert all(abs(y-tx_center)<=0.5 for y in centers),(name,centers,tx_center,box)
        bounds[name]=dict(box=box,centers=centers,tx_center=tx_center)
    assert (out/"battery-and-beacon.png").read_bytes()==(out/"near-battery-again-and-beacon.png").read_bytes()
    return dict(page=2,slots=[4,5],receive_only_blocks_auto=True,cycle_minutes=1,
                wait_blink_ms=500,off_clears_header=True,stock_battery_preserved=True,gps_setting_shared=True,
                top_bar=bounds)
