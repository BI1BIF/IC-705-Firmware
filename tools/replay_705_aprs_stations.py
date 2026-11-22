"""Exercise a 13-page RX list, station views and wrapped APRS on the installed module."""
from struct import pack
from elftools.elf.elffile import ELFFile

from tools.emulate_705 import arm, call, uc
from tools.replay_705_dv_panel import attach_position_graphics
from tools.verify_705_aprs_overlay import LINK


def exercise(g,folder,base,sy,ms,*,baseline=False):
    cpu=g.cpu
    attach_position_graphics(g)
    out=folder/"lists"
    out.mkdir(exist_ok=True)
    def sym(name): return base+sy[name]-LINK
    def u(a,n=4): return int.from_bytes(cpu.mem_read(a,n),"little")
    def tap(row): g.click(150,55+61*row)
    def leave(): g.press_exit();call(cpu,sym("aprs_update_panel"));g.render()
    def capture(name,*expected):
        words,png=g.render()
        (out/(name+".png")).write_bytes(png)
        assert set(expected)<=set(words),(name,words)
        return words
    def addr(station,last):
        name,_,suffix=station.partition("-")
        return bytes(ord(c)*2 for c in name.ljust(6))+bytes([0x60+2*int(suffix or 0)+last])
    def inject(source,info,dest="APRS"):
        frame=addr(dest,0)+addr(source,1)+b"\x03\xf0"+info.encode("ascii")+bytes(2)
        seq=u(sym("aprs_rx_written"))
        rec=sym("aprs_rx_frames")+340*(seq%4)
        cpu.mem_write(rec,pack("<II",seq,len(frame))+frame)
        cpu.mem_write(sym("aprs_rx_written"),pack("<I",seq+1))
        call(cpu,ms["aprs_slot_drain"])
        return rec
    def quick(row):
        g._press_key(1,1);g.render();tap(row)
    cpu.mem_write(sym("aprs_alert_styles"),bytes(7))
    for i in range(50):
        inject("BG1ESR-"+str(1+i%2),"!3531.00N/13930.00Er"+str(i))
    quick(0)
    capture("01-13-pages","APRS RX List","1/13","BG1ESR-2")
    resources=[]
    resource=g.rom(0x20148710)
    hook=cpu.hook_add(uc.UC_HOOK_CODE,lambda *_:resources.append(1),begin=resource,end=resource)
    with (folder/"aprs-task.elf").open("rb") as f:
        size=ELFFile(f).get_section_by_name(".symtab").get_symbol_by_name("aprs_draw_icon")[0]["st_size"]
    start=sym("aprs_draw_icon")
    instructions=0
    def block(_cpu,address,size,_):
        nonlocal instructions
        instructions+=size//4
    cost=cpu.hook_add(uc.UC_HOOK_BLOCK,block,begin=start,end=start+size-1)
    cpu.ctl_remove_cache(start,start+size)
    for step in [1]*12+[0]*12:
        assert call(cpu,g.rom(0x200cd168),step,1)
        g.render()
    cpu.hook_del(hook)
    cpu.hook_del(cost)
    assert instructions>0
    # The input task closes the live selector after the LCD has latched its
    # frame but before it draws rows three and four, as during detail entry.
    def close_during_paint(c,*_):
        if c.reg_read(arm.UC_ARM_REG_R1)==1610: c.mem_write(0x203e1a28,bytes(2))
    row_draw=sym("aprs_history_text")
    h=cpu.hook_add(uc.UC_HOOK_CODE,close_during_paint,begin=row_draw,end=row_draw)
    words=capture("02-pending-detail","1/13")
    cpu.hook_del(h)
    cpu.mem_write(0x203e1a28,pack("<H",170))
    count=words.count("APRS RX List")
    if baseline:
        assert count==3 and resources,(count,resources)
        return dict(scroll_steps=24,stock_icon_reads=len(resources),icon_instructions=instructions,spurious_rows=count-1)
    assert count==1 and words.count("BG1ESR-2")==2 and words.count("BG1ESR-1")==2,words
    assert len(resources)<=2,len(resources)
    tap(0);capture("03-selected","POSITION BEACON","BG1ESR-2")
    leave();capture("04-return","APRS RX List","BG1ESR-2");leave()

    def parsed(source,info,dest="APRS"):
        rec=inject(source,info,dest)
        p=sym("aprs_popup_packet")
        call(cpu,sym("aprs_parse_packet"),p,rec)
        def field(offset,n): return bytes(cpu.mem_read(p+offset,n)).split(b"\0")[0].decode("ascii")
        return [field(0,104),field(104,10),field(114,9),field(123,10),field(133,3),field(136,330)]
    pos="3531.00N/13930.00E>"
    parsed("N0A",";RELAY    *092345z"+pos)
    parsed("N0B",";RELAY    *092345z"+pos)
    parsed("N0A",";RELAY    _092345z"+pos)
    parsed("N0B",")TRAIL!"+pos)
    parsed("N0B",")TRAIL_"+pos)
    compressed=parsed("N0B","!/5L!!<*e7>7P[")
    assert parsed("N0B",";COMPRESS *092345z/5L!!<*e7>7P[")[2:5]==compressed[2:5]
    a=parsed("N0GAT","}N0SRC-9>APRS,TCPIP,N0GAT*:!"+pos+"GATED")
    assert a[1:]==["N0SRC-9","3531.00N","13930.00E","/>","GATED"] and "N0GAT | N0SRC-9>" in a[0],a
    direct=parsed("N0MIC","`c0ol!O[/HIKING","TRSW1R")
    tunneled=parsed("N0GAT","}N0MIC>TCPIP>N0GAT*>TRSW1R:`c0ol!O[/HIKING")
    assert direct[1:]==tunneled[1:] and direct[2],(direct,tunneled)
    m=parsed("N0GAT","}N0MSG-4>APRS,TCPIP,N0GAT*::HOME     :HELLO{A1")
    assert m[1]=="N0MSG-4" and m[3]=="HOME" and m[5]=="HELLO",m
    bad=parsed("N0GAT","}N0BAD>APRS-99:!"+pos)
    assert bad[1]=="N0GAT" and bad[5].startswith("}N0BAD"),bad
    quick(2);capture("05-station-options","APRS Stations","Last Heard","Callsign","Distance")
    tap(1)
    words=capture("06-by-call","APRS Stations","BG1ESR-1","BG1ESR-2")
    assert words.index("BG1ESR-1")<words.index("BG1ESR-2") and words.count("BG1ESR-2")==1
    leave();tap(2);capture("07-by-distance","APRS Stations","1.85 km")
    leave();tap(3);g.render();tap(3);g.render();tap(0)
    words=capture("08-objects","APRS Stations","COMPRESS","RELAY")
    assert words.count("RELAY")==1 and "TRAIL" not in words,words
    tap(1);words=capture("09-object-owner","APRS OBJECT","RELAY")
    assert any("N0B>" in s for s in words),words
    leave();capture("10-return-stations","APRS Stations","RELAY")
    leave();leave();quick(0)
    words=capture("11-history-kept","APRS RX List","N0GAT","N0MSG-4","N0MIC")
    # Open a withdrawn item from the raw packet history.
    g.click(395,162);g.render();tap(3)
    words=capture("12-withdrawn","ITEM REMOVED","TRAIL")
    return dict(scroll_steps=24,stock_icon_reads=len(resources),icon_instructions=instructions,spurious_rows=0,
                raw_history_preserved=True,station_sort_filter=True,owner_scoped_withdrawal=True,
                tnc2_aea=True,wrapped_mice=True,wrapped_message_sender=m[1])
