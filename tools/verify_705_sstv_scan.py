"""Compare native DV calls and SSTV pane updates on both regional main images."""
from struct import pack, unpack
from tools.emulate_705 import arm, call, machine, uc


def pixels(main,rom,sy,entry,out,region):
    from tools.verify_705_sstv_picker_name import panel_guest
    from tools.probe_705_sstv_tx import TX_IMAGE
    from PIL import Image, ImageChops
    g=panel_guest(main,rom,region)
    cpu=g.cpu
    p,q=sy["current_page"],sy["previous_page"]
    cpu.mem_write(sy["menu_id"],pack("<H",21))
    cpu.mem_write(TX_IMAGE,pack("<H",0x4698)*(320*240))
    cpu.mem_write(p+1,b"\x01")
    cpu.mem_write(p+3,b"\x00")
    cpu.mem_write(sy["active"],pack("<I",1))
    draws=[]
    cpu.hook_add(uc.UC_HOOK_CODE,lambda *_: draws.append(1),begin=entry,end=entry)
    def draw(label):
        call(cpu,entry+4)
        call(cpu,rom(0x2018fbc4),instruction_limit=2000000)
        _,w,h,rgba=g.surface.targets[12]
        im=Image.frombytes("RGBA",(w,h),bytes(rgba)).convert("RGB")
        im.save(out/(label+".png"))
        return im
    cpu.mem_write(0x20380c98,b"\x01")
    idle=draw("idle")
    cpu.mem_write(q,bytes(cpu.mem_read(p,100)))
    cpu.mem_write(0x20380c98,bytes(1))
    cpu.mem_write(sy["tx_state"],pack("<I",2))
    cpu.mem_write(sy["cursor"],pack("<8I",TX_IMAGE,120,0,0,13,120,1,0))
    mid=draw("sending")
    box=ImageChops.difference(mid,idle).getbbox()
    assert box and box[2]-box[0]==160 and box[3]-box[1]==2,box
    cpu.mem_write(q,bytes(cpu.mem_read(p,100)))
    count=len(draws)
    call(cpu,entry+4)
    call(cpu,rom(0x2018fbc4),instruction_limit=2000000)
    assert len(draws)==count
    cpu.mem_write(sy["tx_state"],bytes(4))
    assert ImageChops.difference(draw("stopped"),idle).getbbox() is None
    return box


def verify(before, after, rom, sy, entry, out, region):
    regs=[arm.UC_ARM_REG_R0,arm.UC_ARM_REG_R1,arm.UC_ARM_REG_R2,arm.UC_ARM_REG_R3]
    arity=dict(clear_box=3,frame_box=2,photo=4,placeholder=3,grid=5,marker=5,
               clear_block=2,update_block=3,caption=4,icon=3,lookup=3,fill=3)
    def prepare(image):
        cpu=machine(image)
        log=[]
        def handler(name):
            def execute(c,pc,size,data):
                args=[c.reg_read(r) for r in regs]
                if arity[name]==5:
                    args+=unpack("<I", c.mem_read(c.reg_read(arm.UC_ARM_REG_SP),4))
                if name=="caption": args[3]=unpack("<I",c.mem_read(args[3],4))[0]
                if name=="lookup": c.mem_write(args[0],pack("<8H",0,0,0,160,148,160,120,0))
                if name=="fill": args[1]=unpack("<4H",c.mem_read(args[1],8))
                log.append((name,*args[:arity[name]]))
                c.reg_write(arm.UC_ARM_REG_PC,c.reg_read(arm.UC_ARM_REG_LR))
            return execute
        for name in arity: cpu.hook_add(uc.UC_HOOK_CODE,handler(name),begin=sy[name],end=sy[name])
        return cpu,log

    def pane(cpu,log,photo,blocks,incremental):
        p,q=sy["current_page"],sy["previous_page"]
        cpu.mem_write(p+1,bytes([photo,1,blocks]))
        cpu.mem_write(p+24,bytes([1,2,3]))
        cpu.mem_write(p+86,b"\x02")
        log.clear()
        call(cpu,entry,p,q,0,incremental)
        return log.copy()
    old,old_log=prepare(before)
    cpu,log=prepare(after)
    for exists in (0,1):
        for blocks in (0,1,2):
            for partial in (0,1):
                a=pane(old,old_log,exists,blocks,partial)
                b=pane(cpu,log,exists,blocks,partial)
                assert a==b,(a,b)
    word=lambda key,val:cpu.mem_write(sy[key],pack("<I",val))
    word("active",1)
    cpu.mem_write(sy["menu_id"],pack("<H",21))
    cases=[]
    for state,head,row,source_y,segment,expected in (
        (0,0,0,0,0,0),(1,0,0,0,0,0),(2,13,0,0,0,0),
        (2,13,0,0,1,1),(2,13,1,1,1,1),(2,13,128,120,1,61),
        (3,13,128,120,1,0),(2,13,255,240,1,120),(5,13,256,240,0,0)):
        old_line=unpack("<I",cpu.mem_read(sy["displayed_line"],4))[0]
        word("tx_state",state)
        cpu.mem_write(sy["cursor"],pack("<8I",1,source_y,0,0,head,row,segment,0))
        cpu.mem_write(sy["previous_page"]+1,b"\x01")
        call(cpu,entry+4)
        invalidated=cpu.mem_read(sy["previous_page"]+1,1)==b"\0"
        assert invalidated==(expected!=old_line)
        calls=pane(cpu,log,1,0,1)
        lines=[x[2] for x in calls if x[0]=="fill"]
        assert "photo" in [x[0] for x in calls] and not {"marker","grid"}.intersection(x[0] for x in calls)
        assert len(lines)==(2 if expected else 0)
        if lines: assert lines[0]==(160,147+expected,160,1) and 148<=lines[1][1]<268
        cases.append(dict(state=state,row=row,overlay=expected,invalidated=invalidated))
    return dict(dv_comparisons=12,cases=cases,scan_pixels=pixels(after,rom,sy,entry,out,region))
