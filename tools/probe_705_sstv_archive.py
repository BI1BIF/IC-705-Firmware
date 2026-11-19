"""Exercise the native SSTV buttons with a controlled SD file service."""
from io import BytesIO
from struct import pack
from unittest.mock import patch

from PIL import Image
from tools import render_705_stock_row as renderer
from tools.emulate_705 import arm, call, uc
from tools.probe_705_sstv_picture import enter, frame, tick
from tools.replay_705_settings import SettingsGuest
from tools.render_705_stock_row import require


def check_archive(stock,app,sym,install,out):
    with patch.object(renderer,"HEAP_START",0x20700000):
        g=SettingsGuest(stock,front_panel=True)
    install(g)
    cpu=g.cpu
    cpu.mem_write(g.language_address,bytes(2))
    files,handles={},{}
    path=r"C:\IC-705\Picture\SSTV0001.BMP"
    card=True
    def sd(_cpu,address,_size,_data):
        r0,r1,r2,r3=[cpu.reg_read(r) for r in (arm.UC_ARM_REG_R0,arm.UC_ARM_REG_R1,arm.UC_ARM_REG_R2,arm.UC_ARM_REG_R3)]
        code=0
        if address==0x200c27e8:
            code=int(not card)
        elif address==0x2023fec8:
            name=bytes(cpu.mem_read(r0,40)).split(b"\0")[0].decode("ascii")
            require(name.startswith(path[:-5]) and name[-4:]==".BMP","unexpected file path")
            if r1==0 and name not in files: code=7
            else:
                require(r1 in (0,0x201),"unsafe open mode")
                files.setdefault(name,bytearray())
                fd=max(handles,default=100)+1
                handles[fd]=[name,0]
                cpu.mem_write(r2,pack("<I",fd))
        elif address==0x2023fee4:
            del handles[r0]
        else:
            fp=handles[r0]
            buf=files[fp[0]]
            pos=fp[1]
            if address==0x2023ff64:
                fp[1]=(len(buf) if r2==2 else 0)+r1
                cpu.mem_write(r3,pack("<I",fp[1]))
            elif address==0x2023ff18:
                require(len(buf)==pos,"unexpected overwrite")
                buf.extend(cpu.mem_read(r1,r2))
                fp[1]+=r2
                cpu.mem_write(r3,pack("<I",r2))
            else:
                data=bytes(buf[pos:pos+r2])
                if data: cpu.mem_write(r1,data)
                fp[1]+=len(data)
                cpu.mem_write(r3,pack("<I",len(data)))
        cpu.reg_write(arm.UC_ARM_REG_R0,code)
        cpu.reg_write(arm.UC_ARM_REG_PC,cpu.reg_read(arm.UC_ARM_REG_LR))
    for address in (0x200c27e8,0x2023fec8,0x2023fee4,0x2023ff00,0x2023ff18,0x2023ff64):
        cpu.hook_add(uc.UC_HOOK_CODE,sd,begin=address,end=address)
    enter(g); frame(g); g.click(115,116); tick(g); frame(g)
    canvas=int.from_bytes(cpu.mem_read(sym["pixels"],4),"little")
    data=(pack("<H",0xf800)*320*120 + pack("<H",0x001f)*320*120)
    cpu.mem_write(canvas,data)
    cpu.mem_write(sym["counts"]+24,pack("<I",240))
    cpu.mem_write(sym["counts"]+32,pack("<II",2,8))
    g.click(60,193); tick(g); labels,screen=frame(g)
    require("SAVE/HIST" in labels,"SSTV archive button missing")
    card=False
    g.click(371,245); tick(g)
    require("SD error" in frame(g)[0] and not files,"no-card save must fail cleanly")
    card=True
    g.click(371,245); tick(g); labels,screen=frame(g)
    require({"SSTV HISTORY","SAVE","Empty 1"}.issubset(labels),str(labels))
    (out/"archive-chooser.png").write_bytes(screen)
    g.click(115,52); tick(g)
    require("Saved" in frame(g)[0] and set(files)=={path} and not handles,"save failed")
    im=Image.open(BytesIO(files[path])).convert("RGB")
    require(im.size==(320,240) and im.getpixel((5,5))==(255,0,0) and im.getpixel((5,239))==(0,0,255),"BMP differs")
    require(files[path][66:]==data,"saved pixel payload differs")
    corrupt=path.replace("0001","0002")
    files[corrupt]=bytearray(files[path][:-20])
    g.click(371,245); tick(g); frame(g)
    g.click(115,180); tick(g); labels,_=frame(g)
    require("SD error" in labels and cpu.mem_read(canvas,len(data))==data and not handles,
            "truncated file replaced the live preview")
    g.click(371,245); tick(g); frame(g); g.click(115,52); tick(g); frame(g)
    next_path=path.replace("0001","0003")
    require(files[path][66:]==data and len(files[corrupt])==153646 and files[next_path][66:]==data,
            "save reused an occupied or damaged slot")
    cpu.mem_write(canvas,bytes(len(data)))
    g.click(371,245); tick(g); labels,screen=frame(g)
    require("SSTV  1" in labels,str(labels))
    # Reopening copies the entire 150 KiB image through the stock memory routine.
    with patch("tools.replay_705_settings.call",
               lambda cpu,pc,*args: call(cpu,pc,*args,instruction_limit=2_000_000)):
        g.click(115,116)
    tick(g); labels,screen=frame(g)
    require("Saved SSTV" in labels and cpu.mem_read(canvas,len(data))==data and not handles,
            f"history read failed: {labels}, pixel head={bytes(cpu.mem_read(canvas,8)).hex()}, handles={handles}")
    (out/"archive-reopened.png").write_bytes(screen)
    g.press_exit(); tick(g); frame(g)
    require(g.state()["menu"]==21 and not cpu.mem_read(sym["gallery_loading"],4)[0],"return to live failed")
    return dict(card_model="file service shim",no_card=True,bmp_bytes=len(files[path]),
                save=True,reopened=True,truncated_read_rejected=True,occupied_slots_preserved=True,path=path)
