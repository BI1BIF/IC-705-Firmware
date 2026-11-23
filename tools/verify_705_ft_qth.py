"""Exercise the regional candidate through the FT row producer and LCD renderer."""
import argparse
import json
from pathlib import Path
from struct import pack

from PIL import Image
from tools.build_705_e140_log_test import BASE, ROOT, decode_main, digest, load_a
from tools.build_705_ft_panel_assets import LABELS, QTH_NAMES
from tools.emulate_705 import arm, call, uc
from tools.replay_705_settings import SettingsGuest
from tools.verify_705_e140_station import E_MAIN, EuropeanReplay
from tools.verify_705_ftx_rx import OUT, load, map_atlas, menu_init, symbols


def verify(folder, region, *, wide=False):
    path=folder/f"705{region}140.dat"
    dat=path.read_bytes()
    stock=(ROOT/"firmware"/path.name).read_bytes()
    image=bytes(decode_main(dat)[1])
    if region=="J":
        guest=SettingsGuest(load(stock),front_panel=True)
        guest.cpu.mem_write(BASE,image)
        guest.cpu.ctl_remove_cache(BASE,BASE+len(image))
        menu_init(guest.cpu,image)
        map_atlas(guest.cpu,dat)
    else:
        native,flash=load_a(stock,E_MAIN)
        guest,_=EuropeanReplay(native,flash,digest(image)).station_guest(dat)
    cpu=guest.cpu
    sy=symbols(OUT/"rx.elf")
    guest.render()
    cpu.mem_write(guest.language_address,bytes(2))
    assert call(cpu,sy["ft_data_ready"])
    call(cpu,sy["ftx_allocate"],0,instruction_limit=0)
    call(cpu,sy["view_reset"],0)
    row=call(cpu,sy["row_text"],0)
    for key,value in (("state",2),("enabled",1),("clock_ready",1)):
        cpu.mem_write(sy[key],pack("<I",value))
    codes=json.loads((OUT/"countries.json").read_text())["codes"]
    names={"cn":"中国","hk":"中国香港","mo":"中国澳门","jp":"日本"}
    places=[names.get(c,c) for c in codes]+QTH_NAMES
    # Same call areas, different first suffix letters, also check fallback.
    for digit,groups in enumerate(("新疆 西藏","北京","黑龙江 吉林 辽宁","天津 内蒙古 河北 山西",
            "上海 山东 江苏","浙江 江西 福建","安徽 河南 湖北","湖南 广东 广西 海南",
            "四川 重庆 贵州 云南","陕西 甘肃 宁夏 青海")):
        stride=6 if digit in (0,3,8,9) else 8
        for i,name in enumerate(groups.split()):
            for letter in (i*stride,23 if digit==1 else min(25,(i+1)*stride-1)):
                ch=chr(65+letter)
                callname=f"BG{digit}{ch}AB"
                cpu.mem_write(row,callname.encode().ljust(43,b"\0")+b"\x01")
                result=call(cpu,sy["ft_place_id"],row)
                assert result and places[result-1]==name,(callname,name,result)
    cases=[("BG4ABC","上海"),("BG4JAB","山东"),("BG4QAB","江苏"),("VR2ABC","中国香港"),
           ("XX9ABC","中国澳门"),("BV2ABC","中国台湾"),("BX5ABC","中国台湾"),
           ("BG5JKZ","江西"),("BI1BIF","北京"),("BG2AAB","黑龙江")]
    for callname,name in cases+[("BG4JAB/P","山东"),("BG4JAB/7","中国"),
                    ("BG4J1A","中国"),("BG4XYZW","中国"),("BG4SOS","中国"),("JA2IXS","日本")]:
        cpu.mem_write(row,callname.encode().ljust(43,b"\0")+b"\x01")
        result=call(cpu,sy["ft_place_id"],row)
        assert result and places[result-1]==name,(callname,name,result)
    ys={}
    def word(c,*_):
        index,x,y,limit=guest.surface.args(4)
        if x==(223 if wide else 199) and limit==64: ys[y]=places[index-len(LABELS)-len(places)-1]
    cpu.hook_add(uc.UC_HOOK_CODE,word,begin=sy["panel_word"]&~1,end=sy["panel_word"]&~1)
    if wide:
        msg=b"CQ JA2IXS PM95"
        cpu.mem_write(row,msg.ljust(36,b"\0")+pack("<4iBB",1200,42,3,-10,0,0))
        call(cpu,sy["view_publish"],0,1)
    for i,(sender,name) in enumerate(cases):
        dest="EA8/DL1XYZ" if i==3 or (wide and i==8) else "CQ"
        body = "RR73X" if wide and i==3 else "R-12 EXTRA" if wide and i==8 else "OL78"
        msg=f"{dest} {sender} {body}"
        if wide and i==3:
            assert len(msg)==23
        cpu.mem_write(row,msg.encode().ljust(36,b"\0")+pack("<4iBB",2980 if wide and i==8 else 1400+i,42,len(dest)+1,-13,0,0))
        call(cpu,sy["view_publish"],i+wide,1)
    headers={}
    bars=[]
    glyphs={}
    marks=[]
    numeric={}
    def header(c,*_):
        ptr,x,y=guest.surface.args(3)
        if y in (87,88): headers[bytes(c.mem_read(ptr,12)).split(b"\0")[0].decode()]=x
        if wide and y==104+8*17 and x>=289:
            numeric[bytes(c.mem_read(ptr,8)).split(b"\0")[0].decode()]=x
    def rail(c,*_):
        _,x,y,w,h=guest.surface.args(5)
        if y==91 and h==6: bars.append((x,w))
        if wide and x==211 and w==8 and h==14: marks.append(y)
    for label,cb in (("text",header),("rectangle",rail)):
        at=sy[label]&~1
        cpu.hook_add(uc.UC_HOOK_CODE,cb,begin=at,end=at)
    if wide:
        def tile(c,*_):
            _,_,_,x,inverted_y=guest.surface.args(5)
            glyphs.setdefault(272-inverted_y-14,[]).append(x)
        cpu.hook_add(uc.UC_HOOK_CODE,tile,begin=0x2037D682,end=0x2037D682)
    for slot in range(2):
        cpu.mem_write(sy["ftx_ft4"],pack("<I",slot))
        bars.clear()
        glyphs.clear()
        marks.clear()
        call(cpu,sy["view_invalidate"])
        call(cpu,sy["view_draw"],slot,30000 if slot else 60000,instruction_limit=0,timeout_us=10000000)
        assert list(ys.values())==[v for k,v in cases],ys
        assert bars==([(46,88),(46,44)] if wide else [(116,70),(116,35)]),bars
        assert [headers[k] for k in ("AB"[slot],"QTH","dB","Hz","km")]==(
            [31,223,299,335,367] if wide else [101,199,269,307,362]),headers
        if wide:
            for line in (3,8):
                assert glyphs[104+17*line]==list(range(35,219,8)),glyphs
            assert marks==[104+8*17],marks
            assert numeric["-13"]==292 and numeric["2980"]==321,numeric
        guest.surface.select_target()
        lcd=Image.frombytes("RGBA",(480,272),bytes(guest.surface.pixels)).convert("RGB")
        # The two live action keys use the same factory left bevel.
        assert lcd.crop((399,90,402,121)).tobytes()==lcd.crop((399,126,402,157)).tobytes()
        lcd.crop((0,84,480,272)).save(folder/f"QTH-{'AB'[slot]}.png")
        if wide:
            bars.clear()
            headers.clear()
            call(cpu,sy["view_draw"],slot^1,0,instruction_limit=0,timeout_us=10000000)
            assert bars==[(46,88)] and headers["AB"[slot^1]]==31,(bars,headers)
    if wide:
        assert call(cpu,sy["ft_panel_touch"],416,177) and call(cpu,sy["ft_is_history"])
        ys.clear()
        glyphs.clear()
        call(cpu,sy["view_draw"],0,30000,instruction_limit=0,timeout_us=10000000)
        assert ys[103]=="日本" and glyphs[104+17*4]==list(range(35,219,8)),(ys,glyphs)
        guest.surface.select_target()
        lcd=Image.frombytes("RGBA",(480,272),bytes(guest.surface.pixels)).convert("RGB")
        lcd.crop((0,84,480,272)).save(folder/"QTH-history.png")
        assert call(cpu,sy["ft_panel_touch"],455,177) and not call(cpu,sy["ft_is_history"])
    (folder/"qth.json").write_text(json.dumps(dict(region=region,sha256=digest(dat),rows=ys,
        province_boundaries=31,slot_frames=["A","B"],message_characters=23 if wide else 20,
        history_and_live_share_layout=wide),ensure_ascii=False,indent=2),encoding="utf8")
    print(region,"province boundaries, details and ten LCD rows passed")

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("folder",type=Path)
    p.add_argument("region",choices=["J","E"])
    p.add_argument("--wide",action="store_true")
    args=p.parse_args()
    verify(args.folder,args.region,wide=args.wide)
