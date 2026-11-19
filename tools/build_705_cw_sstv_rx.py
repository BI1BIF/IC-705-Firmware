"""Build and exercise the combined J140 D6 CW and SSTV firmware."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import iter_unpack, pack, unpack_from
from zipfile import ZipFile, ZIP_DEFLATED

from tools.build_705_cw_sim import END, PICKER_REFERENCES, PICKER_STRIDE, load_image
from tools.decode_705_main import decode_main
from tools.emulate_705 import BASE, arm, call, uc
from tools.firmware_scan import layout
from tools.probe_705_sstv_arm import build, replay, scheduler_replay
from tools.probe_705_sstv_picture import OPEN_APP, PICTURE_CALL, branch, frame, tick
from tools.render_705_display import load, require
from tools.replay_705_cw_dat import pack_main_dat


D6 = Path(".analysis/cw-reacquire-1118")
D6_SHA = "8a5aa8c6083fb49dc6889871357dcd4cdb98eb7bda70d384c0f00f321d9c4aa6"


def digest(data):
    return sha256(data).hexdigest()


def verify_boot_slots(package, stock_dat):
    from tools.probe_705_boot_selection import FIRST, SECOND, MARKER, NOR_BYTES, part
    from tools.decode_705_main import BOOT_SIZE
    from tools.emulate_705 import BOOT, machine
    from tools.replay_705_nor_boot import boot_from_nor
    from tools.replay_705_stock_install import A_PREFIX, SHARED, load_a

    boot, payload, main, package_hash = part(package)
    _, candidate = load_a(package.read_bytes(), digest(main))
    _, original = load_a(stock_dat, digest(decode_main(stock_dat)[1]))
    require(candidate[A_PREFIX:] == original[A_PREFIX:] and len(payload) <= A_PREFIX-BOOT_SIZE,
            "packed application exceeds update slot or changes shared data")
    snapshot = bytearray(b"\xff" * NOR_BYTES)
    snapshot[:BOOT_SIZE] = boot
    snapshot[SHARED:SHARED+len(original)-A_PREFIX] = original[A_PREFIX:]
    boots = {}
    for address in (FIRST, SECOND):
        offset = address - BOOT
        snapshot[offset:offset+len(payload)] = payload
        if address == SECOND:
            snapshot[MARKER-BOOT:MARKER-BOOT+16] = boot[0x47e8:0x47f8]
        result = boot_from_nor(machine(), None, main, snapshot=bytes(snapshot))
        require(int(result["source_slot"], 16) == address and result["application_sha256"] == digest(main),
                "bootstrap selected the wrong application")
        boots[hex(address)] = result
    return dict(dat_sha256=package_hash, shared_data_matches_stock=True, slots=boots)


def combine(app, meta, folder, cc, diagnostics=False, robot_sync=False, basic=False, late_join=False, *, tx_study=False):
    require(not tx_study or late_join, "TX study uses the RX4 selector layout")
    old_table,=unpack_from("<I",app,PICKER_REFERENCES[0]-BASE)
    records=app[old_table-BASE:old_table-BASE+280*PICKER_STRIDE]
    require(len(records)==280*72,"missing CW selector records")
    original_text=old_table+len(records)
    if late_join:
        table=old_table
        # D6's trailing region contains only its selector records and their
        # strings. Preserve the original code and extend its existing table.
        head=bytearray(app[:old_table-BASE])
    else:
        head=bytearray(app)
        base=(BASE+len(app)+31)&~31
        raw,sym=build(folder,cc,base=base,limit=END,cw_pcm=meta["symbols"]["cw_pcm_bridge"],
                      diagnostics=diagnostics,robot_sync=robot_sync,basic=basic)
        sym["sstv_link_base"]=base
        head.extend(bytes(base-BASE-len(head))+raw)
        table=(sym["end_rx"]+3)&~3
        require(BASE+len(head)<=table,"static SSTV data outside its assigned range")
        head.extend(bytes(table-BASE-len(head)))
    tx_count=23
    texts=table+(294+tx_count if tx_study else 293 if late_join else 283)*72
    tail=b"PICTURE\0DV\0SSTV\0"+pack("<HH",281,282)
    archive_title=texts+len(tail)
    if late_join:
        tail+=b"SSTV HISTORY\0SAVE\0"+pack("<9H",*range(284,293))
    if tx_study:
        mode_rows=texts+len(tail)
        tail+=pack(f"<{tx_count}H",*range(294,294+tx_count))
    if late_join:
        cw_tail=app[original_text-BASE:]
        require(cw_tail.startswith(b"KEYER/DECODE\0KEYER\0CW DECODE\0"),"unexpected CW selector labels")
        relocated=bytearray(records)
        for row,fields in ((277,(48,56,68)),(278,(52,60)),(279,(52,60))):
            for field in fields:
                index=row*72+field
                value,=unpack_from("<I",records,index)
                require(original_text<=value<BASE+len(app),"CW selector points outside its text")
                relocated[index:index+4]=pack("<I",value+texts+len(tail)-original_text)
        base=(texts+len(tail)+len(cw_tail)+31)&~31
        raw,sym=build(folder,cc,base=base,limit=END,cw_pcm=meta["symbols"]["cw_pcm_bridge"],
                      diagnostics=True,robot_sync=True,basic=True,late_join=True,tx_study=tx_study)
        sym["sstv_link_base"]=base
        image=head+relocated
    else:
        image=head+records
    for i,fields in enumerate(({12:sym["sstv_select"],32:sym["sstv_choice"],48:texts,56:texts,68:texts+16},
                              {52:texts+8,60:texts+8},{52:texts+11,60:texts+11})):
        row=bytearray(records[(277+i)*72:(278+i)*72])
        for offset,pointer in fields.items():
            row[offset:offset+4]=pack("<I",pointer)
        image.extend(row)
    if late_join:
        title=bytearray(records[277*72:278*72])
        title[1]=8
        for field,value in ((12,sym["sstv_archive_select"]),(32,sym["sstv_archive_choice"]),
                            (48,archive_title),(56,archive_title),(68,archive_title+18)):
            title[field:field+4]=pack("<I",value)
        image.extend(title)
        for pos in range(9):
            row=bytearray(records[278*72:279*72])
            label=archive_title+13 if pos==0 else sym["archive_names"]+16*(pos-1)
            row[52:56]=row[60:64]=pack("<I",label)
            image.extend(row)
    if tx_study:
        title=bytearray(records[277*72:278*72])
        title[1]=tx_count-1
        for field,value in ((12,sym["sstv_tx_select"]),(32,sym["sstv_tx_choice"]),
                            (48,sym["sstv_tx_title"]),(56,sym["sstv_tx_title"]),(68,mode_rows)):
            title[field:field+4]=pack("<I",value)
        image.extend(title)
        count,stride,name_offset=unpack_from("<III",raw,sym["sstv_tx_table_layout"]-base)
        require(count==tx_count,"receiver mode count changed")
        labels=[sym["sstv_tx_robot"],sym["sstv_tx_martin"]]
        for i in range(count-2):
            labels.append(unpack_from("<I",raw,sym["basic_modes"]-base+i*stride+name_offset)[0])
        for label in labels:
            row=bytearray(records[278*72:279*72])
            row[52:56]=row[60:64]=pack("<I",label)
            image.extend(row)
    image.extend(tail)
    if late_join:
        image.extend(cw_tail)
        image.extend(bytes(base-BASE-len(image))+raw)
        image.extend(bytes(sym["end_rx"]-BASE-len(image)))
    require(BASE+len(image)<=END,"combined main overlaps stock globals")
    sites={}
    def replace(site,old,new):
        offset=site-BASE
        require(unpack_from("<I",image,offset)==(old,),f"D6 instruction/data mismatch at {site:#x}")
        image[offset:offset+4]=pack("<I",new)
        sites[hex(site)]=[hex(old),hex(new)]
    for site in PICKER_REFERENCES:
        replace(site,old_table,table)
    bl=0xeb000000
    replace(PICTURE_CALL,branch(PICTURE_CALL,OPEN_APP,bl),branch(PICTURE_CALL,sym["sstv_picker_open"],bl))
    for site,old,name in ((0x2010feac,branch(0x2010feac,meta["symbols"]["cw_pcm_bridge"]),"sstv_pcm_hook"),
                          (0x2013c5e8,0xe92d5ff0,"sstv_frame_hook"),(0x2018e838,0xe59f4430,"sstv_image_hook"),
                          (0x2018f818,0xe5d4001d,"sstv_thumbnail_hook"),
                          (0x200c4620,0xe92d4010,"sstv_pict_tx"),(0x200c46cc,0xe92d4008,"sstv_tx_all")):
        replace(site,old,branch(site,sym[name]))
    label_sites=(0x2018fd0c,0x201911d0,0x20191268,0x2018f104,0x2018f240)
    if late_join:
        replace(0x200c493c,0xe92d4010,branch(0x200c493c,sym["sstv_archive_button"]))
        label_sites+=(0x20190bc8,0x20190e30,0x20190e74)
    if tx_study:
        replace(0x20060d28,0xe7d00001,branch(0x20060d28,sym["sstv_tx_source_hook"]))
        replace(0x20109674,0xe1a012a0,branch(0x20109674,sym["sstv_tx_request_hook"]))
        replace(0x200ffeb0,branch(0x200ffeb0,0x201f644c,bl),branch(0x200ffeb0,sym["sstv_tx_mod_block"],bl))
        replace(0x200c4d90,0xe92d403e,branch(0x200c4d90,sym["sstv_tx_mode_button"]))
        label_sites+=(0x201903f8,0x201905e8,0x20190778,0x20190808,0x201908a0)
        replace(0x20190150,branch(0x20190150,0x2018e7e8,bl),branch(0x20190150,sym["sstv_tx_detail_draw"],bl))
    for site in label_sites:
        replace(site,branch(site,0x20142698,bl),branch(site,sym["sstv_picture_label"],bl))
    cw_end=old_table-BASE if late_join else len(app)
    require(image[meta["code_base"]-BASE:cw_end]==app[meta["code_base"]-BASE:cw_end],
            "embedded D6 CW code or its original table changed")
    return bytes(image),sym,sites


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    parser.add_argument("--clang",required=True)
    parser.add_argument("--diagnostics",action="store_true",help="Build the RX2 field diagnostic")
    parser.add_argument("--robot-sync",action="store_true",help="Build RX3 with Robot 36 line recovery and diagnostics")
    parser.add_argument("--basic",action="store_true",help="Build multimode RX with Robot 36 line recovery")
    parser.add_argument("--late-join",action="store_true",help="Build RX4 with line detection and Robot 36 clock tracking")
    parser.add_argument("--tx",action="store_true",help="Include RX4 and SSTV transmission over the stock SSI0 modulation path")
    parser.add_argument("--decoder",type=Path,default=Path(".analysis/sstv-colaclanth"),help="Independent SSTV decoder checkout for TX checks")
    args=parser.parse_args()
    out=args.output
    out.mkdir(parents=True,exist_ok=True)
    args.late_join |= args.tx
    edition="RX4-TX4" if args.tx else "RX4" if args.late_join else "RX3-MULTI" if args.basic else "RX3-LINE" if args.robot_sync else "RX2-DIAG" if args.diagnostics else "RX1-TEST"
    target=out/f"705J140-CW-D6-SSTV-{edition}.dat"
    require(not target.exists(),"existing delivery must be preserved")
    stock_dat=Path("firmware/705J140.dat").read_bytes()
    stock=load(stock_dat)
    d6_dat=(D6/"delivery-d6/705J140-CW-WAKE-D6-TEST.dat").read_bytes()
    require(digest(d6_dat)=="c50899d0931a81d46b145f21e30c876344effa428491e50961511e1ee7869b41","incorrect D6")
    app,meta=load_image(D6/"CW-RX3-WAKE2-PC/CW-RX3-WAKE2-PC.ic705sim")
    require(decode_main(d6_dat)[1]==app[0] and digest(app[0])==D6_SHA,"D6 bundle and DAT differ")
    merged,sym,sites=combine(app[0],meta,out/"build",args.clang,args.diagnostics or args.robot_sync or args.basic,args.robot_sync or args.basic,args.basic,args.late_join,tx_study=args.tx)
    data,_=pack_main_dat(stock_dat,stock,merged)
    boot,exact,_=decode_main(data)
    exact=bytes(exact)
    require(exact==merged and boot==decode_main(stock_dat)[0] and layout(data)["all_records_valid"],
            "DAT unpack failed")
    wav=Path(".analysis/sstv-robot36-v1/robot36.wav")
    previous=json.loads(Path(".analysis/sstv-auto-rx/evidence.json").read_text())
    print("Testing original scheduler with both tasks and native heap",flush=True)
    rtx=scheduler_replay(stock[0],exact,sym,wav,previous["image_rgb565_sha256"],combined=meta)
    print(rtx,flush=True)
    def install(g):
        # The isolated panel test supplies the two scheduler endpoints.
        # The independent scheduler test above uses original allocation and actual RTX tasks.
        cpu=g.cpu
        cpu.mem_write(BASE,exact)
        cpu.ctl_remove_cache(BASE,BASE+len(exact))
        cpu.mem_write(sym["sstv_thread"],pack("<I",1))
        def event(cpu,*_):
            cpu.reg_write(arm.UC_ARM_REG_R0,0)
            cpu.reg_write(arm.UC_ARM_REG_PC,cpu.reg_read(arm.UC_ARM_REG_LR))
        cpu.hook_add(uc.UC_HOOK_CODE,event,begin=0x202d4850,end=0x202d4850)
    print("Testing both selectors, two SSTV modes, navigation and the D6 CW path",flush=True)
    panel=replay(stock,exact,sym,wav,wav.with_name("reference.ppm"),out,
                 Path(".analysis/sstv-colaclanth/examples/m1.ogg"),installed=install)
    require(panel["image_rgb565_sha256"]==previous["image_rgb565_sha256"] and
            panel["sequences"]["complete_then_martin"]["rgb565_sha256"]==
            previous["sequences"]["complete_then_martin"]["rgb565_sha256"],"SSTV regression")
    controls=check_controls(stock,exact,meta,sym,install,out)
    if args.late_join:
        from tools.probe_705_sstv_archive import check_archive
        controls["archive"]=check_archive(stock,exact,sym,install,out)
    if args.tx:
        import sys
        from tools.probe_705_sstv_tx import exercise as tx_replay
        sys.path.insert(0,str(args.decoder.resolve()))
        controls["tx"]=tx_replay(out/"tx",args.clang,installed=(exact,sym))
        from tools.probe_705_sstv_tx_modes import run as tx_modes
        from shutil import which
        sys.path.insert(0,str(Path(".analysis/sstv-independent-tx").resolve()))
        modes=tx_modes(exact,sym,out/"build",Path(which(args.clang) or args.clang))
        (out/"tx-multimode.json").write_text(json.dumps(dict(dat_sha256=digest(data),modes=modes),indent=2))
    report=dict(base="Japanese IC-705 1.40 CW D6",d6_sha256=digest(d6_dat),dat_sha256=digest(data),
                main_sha256=digest(exact),bytes=len(data),main_end=hex(BASE+len(exact)),sites=sites,
                rtx=rtx,panel=panel,controls=controls,physical_radio_tested=False)
    with target.open("xb") as stream: stream.write(data)
    require(digest(target.read_bytes())==digest(data),"saved package differs")
    if args.robot_sync or args.basic or args.late_join:
        from tools.probe_705_sstv_robot_lines import exercise
        from shutil import which
        clang=Path(which(args.clang) or args.clang)
        line_checks=exercise(target,clang.with_name("llvm-nm"+clang.suffix))
        (out/"rx3-lines.json").write_text(json.dumps(line_checks,indent=2),encoding="utf-8")
    (out/"boot-slots.json").write_text(json.dumps(verify_boot_slots(target, stock_dat),indent=2),encoding="utf-8")
    archive=target.with_suffix(".zip")
    with ZipFile(archive,"x",compression=ZIP_DEFLATED) as z:
        z.write(target,"IC-705/705J140.dat")
    with ZipFile(archive) as z:
        require(z.namelist()==["IC-705/705J140.dat"] and z.read(z.namelist()[0])==data,
                "SD archive round-trip mismatch")
    report["zip_sha256"]=digest(archive.read_bytes())
    (out/"verification.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    (out/"SHA256SUMS.txt").write_text(f"{digest(data)}  {target.name}\n",encoding="ascii")
    print(target,digest(data),flush=True)


def check_controls(stock,exact,meta,sym,install,out):
    from unittest.mock import patch
    from tools import render_705_stock_row as renderer
    from tools.replay_705_settings import SettingsGuest
    from tools.probe_705_cw_menu import MODE_UI_A, MODE_VFO_A
    from tools.probe_705_cw_session import read_session
    from tools.probe_705_sstv_picture import enter
    with patch.object(renderer,"HEAP_START",0x20700000):
        g=SettingsGuest(stock,front_panel=True)
    install(g)
    cpu=g.cpu
    cpu.mem_write(g.language_address,bytes(2))
    enter(g); frame(g); g.click(115,116); tick(g)
    waiting="NO PCM" if "displayed_peak" in sym else "---"
    if "sstv_tx_mod_block" in sym: waiting="RX"
    button="SEND" if "sstv_tx_mod_block" in sym else "RX ONLY"
    require({button,waiting,"SSTV AUTO"}.issubset(frame(g)[0]),"SSTV half-panel controls missing")
    dispatch=[]
    for a in (0x200c4624,0x200c46d0):
        cpu.hook_add(uc.UC_HOOK_CODE,lambda c,a,*_:dispatch.append(a),begin=a,end=a)
    for x,y in ((365,191),(365,241)): g.click(x,y)
    require(not dispatch,"DV transmit path reached from SSTV")
    g.press_exit();tick(g);frame(g)
    state=g.surface.alloc(5120)
    cpu.mem_write(state,bytes(5120))
    cpu.mem_write(meta["symbols"]["cw_state_anchor"],pack("<I",state))
    for a in (MODE_UI_A,MODE_VFO_A): cpu.mem_write(a,b"\x20")
    g.press_menu();tick(g);frame(g)
    from tools.replay_705_settings import GRID_PAGE
    if cpu.mem_read(GRID_PAGE,1)==b"\x02":
        g.click(186,251);tick(g);frame(g)
    g.click(240,77);tick(g)
    labels,screen=frame(g)
    require({"KEYER","CW DECODE"}.issubset(labels),"D6 CW selector missing")
    (out/"cw-selector.png").write_bytes(screen)
    g.click(115,116);tick(g)
    require(read_session(cpu,state)["active"],"CW decoder did not open")
    # The field RTX probe exercises the shared PCM path with D6's own thread.
    from tools.probe_705_rtx_audio import probe
    field=probe(stock[0],field_rtx=(exact,meta,0))
    from tools.probe_705_cw_field_audio import audio,bl_target,measure
    raw=audio("CQ",trim_leading=True)+bytes(3204)
    groups=list(iter_unpack("<6h",raw[:len(raw)//12*12]))
    worker=bl_target(exact,meta["symbols"]["cw_rtx_worker"]+28)
    decoded=measure(exact,meta,worker,groups,0,None)
    require(decoded["text"].strip()=="CQ","CW did not decode the reference call")
    return dict(cw_selector=labels,cw_active=True,rx_only_transmit_dispatches=dispatch,cw_rtx=field,cw_audio=decoded)


if __name__=="__main__":
    main()
