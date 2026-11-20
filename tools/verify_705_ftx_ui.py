"""Compare the persistent FT list, stock knob layers and both LCD outputs."""

import json
from hashlib import sha256
from struct import pack
from unittest.mock import patch

from tools import replay_705_settings as settings
from tools.probe_705_sstv_picture import frame, tick
from tools.replay_705_gps_inputs import GPS_MODE
from tools.verify_705_ftx_rx import (
    BASE,
    bitmap_messages,
    OUT,
    ROOT,
    arm,
    call,
    decode_main,
    load,
    map_atlas,
    menu_init,
    symbols,
    uc,
    val,
)


def compare(folder, stock, initial_scope=1, *, panel_top=86):
    dat = (folder / "bench-rx.dat").read_bytes()
    sy = symbols(folder / "rx.elf")
    revised = "view_invalidate" in sy
    outputs = [bytearray(480 * 272 * 4) for _ in range(2)]
    attach = settings.attach_front_surface

    def attach_outputs(c, surface):
        attach(c, surface, double_buffered=True)
        # Different stock contexts can address the same physical VRAM.
        items = surface.targets.copy()
        base = min(t[0] for t in items.values())
        end = max(addr + 2 * w * h for addr, w, h, _ in items.values())
        ram = memoryview(bytearray(2 * (end - base)))
        for i, (addr, w, h, _) in items.items():
            at = 2 * (addr - base)
            surface.targets[i] = addr, w, h, ram[at : at + 4 * w * h]

        def select(cpu, *_):
            slot = cpu.reg_read(arm.UC_ARM_REG_R1)
            surface.display = 480, 272, outputs[slot]
            surface.select_target()

        c.hook_add(uc.UC_HOOK_CODE, select, begin=0x20194C18, end=0x20194C18)

    with patch.object(settings, "attach_front_surface", attach_outputs):
        p = settings.SettingsGuest(stock, front_panel=True)
    c = p.cpu
    m = bytes(decode_main(dat)[1])
    c.mem_write(BASE, m)
    c.ctl_remove_cache(BASE, BASE + len(m))
    menu_init(c, m)
    map_atlas(c, dat)
    if "ft_data_ready" in sy: assert call(c,sy["ft_data_ready"])
    c.mem_write(p.language_address, bytes(2))
    p.render()
    c.mem_write(0x203E2128, bytes([16, 1]))
    call(c, 0x200F1F04, initial_scope)
    tick(p)

    # A deferred graphics reader can sample a CPU bitmap any time prior to
    # vgFinish. Keep the bytes alive through that boundary on every page.
    pending = []
    checked = [0]
    if "sender_grid" in sy:
        def check_source(cpu,*_):
            ptr,stride,fmt,x,y,w,h = p.surface.args(7)
            if ptr >= 0x20000000 and p.surface.target == 7 and fmt == 3:
                assert (w,h) in ((8,15),(16,15),(16,12)) and stride == 2**32-32, (hex(ptr),w,h)
                start=ptr-(h-1)*32
                pending.append((start,bytes(cpu.mem_read(start,h*32))))
        def sync_sources(cpu,*_):
            for ptr,data in pending:
                assert bytes(cpu.mem_read(ptr,len(data))) == data
                checked[0] += 1
            pending.clear()
        c.hook_add(uc.UC_HOOK_CODE,check_source,begin=0x20263B12,end=0x20263B12)
        c.hook_add(uc.UC_HOOK_CODE,sync_sources,begin=0x20263190,end=0x20263190)

    searches = 0

    def count_lookup(*_):
        nonlocal searches
        searches += 1

    lookup = sy["lookup"] & ~1
    c.hook_add(uc.UC_HOOK_CODE, count_lookup, begin=lookup, end=lookup)

    def draw(slot):
        nonlocal searches
        if val(c, sy["state"]) == 2:
            c.mem_write(sy["adc"], pack("<I", val(c, sy["adc"]) + 2000))
        c.mem_write(0x20380CBC, bytes([slot]))
        frame(p)
        p.surface.events.clear()
        p.surface.pixel_writes.clear()
        searches = 0
        c.emu_start(0x2013D4A8, 0x2013D4AC, count=12000000)
        assert c.reg_read(arm.UC_ARM_REG_PC) == 0x2013D4AC
        return bytes(outputs[slot])

    for i in (0, 1, 0, 1):
        draw(i)
    original = [draw(i) for i in range(2)]
    if not initial_scope:
        c.mem_write(sy["restore_scope"], pack("<I", 1))
        call(c, 0x200F1F04, 1)
        tick(p)
    call(c, sy["ftx_allocate"], 0, instruction_limit=0)
    call(c, sy["view_reset"], 0)
    c.mem_write(sy["state"], pack("<I", 2))
    c.mem_write(sy["enabled"], pack("<I", 1))
    c.mem_write(sy["clock_ready"], pack("<I", 1))
    c.mem_write(GPS_MODE, b"\2")
    c.mem_write(0x203EA85D, bytes([35]) + pack(">H", 30000) + b"N")
    c.mem_write(0x203EA861, bytes([139]) + pack(">H", 30000) + b"E")
    row = call(c, sy["row_text"], 0)
    result = {}
    total = 0
    for size in (0, 10, 48, 240):
        while total < size:
            msg = f"CQ JA1ABC PM{total % 100:02}"
            c.mem_write(
                row,
                msg.encode().ljust(36, b"\0") + pack("<4iBB", 1250, 42, 3, -13, 0, 11),
            )
            call(c, sy["view_publish"], total, 1)
            total += 1
        fresh = draw(0)
        current = draw(1)
        body = slice(102 * 480 * 4, None)
        assert current[body] == fresh[body]
        if folder == OUT:
            # Both LCD outputs must retain static titles without issuing glyph draws.
            for y in range(86,102):
                for x,right in ((0,132),(219,395)):
                    span = slice(4*(480*y+x),4*(480*y+right))
                    assert current[span] == fresh[span]
            assert len(p.surface.events) <= 1
        flags = sum(w["rect"][2:] in ([12, 9], [16, 12]) for w in p.surface.pixel_writes)
        texts = sum(
            "".join(chr(g["key"]) for g in e["glyphs"]).startswith("CQ JA1ABC")
            for e in p.surface.events
        )
        result[size] = {
            "flag_blits": flags,
            "message_text_runs": texts,
            "text_calls": len(p.surface.events),
            "atlas_searches": searches,
        }
        if revised:
            assert flags == texts == searches == 0
            call(c, sy["view_invalidate"])
            assert draw(1)[body] == current[body]
        elif size:
            assert flags == texts == 10

    if "dim_key" in sy:
        from PIL import Image
        def screen(buf):
            return Image.frombytes("RGBA",(480,272),buf).convert("RGB")
        live, cached = screen(fresh), screen(current)
        if folder == OUT:
            sample = val(c, sy["adc"])
            for mode, length in ((0,120000),(1,60000)):
                c.mem_write(sy["ftx_ft4"], pack("<I",mode))
                call(c, sy["view_invalidate"])
                for lcd in (0,1):
                    # draw() adds 2000 samples; show the middle of A then B.
                    c.mem_write(sy["adc"], pack("<I",length*lcd+length//2-2000))
                    picture = screen(draw(lcd))
                    assert picture.getpixel((148,91)) != picture.getpixel((217,91))
                    for x,right in ((4,40),(133,147),(226,261),(269,295),(307,341),(362,395)):
                        ink = [y for y in range(86,102)
                               if any(min(picture.getpixel((col,y)))>170 for col in range(x,right))]
                        assert ink and abs(ink[0]+ink[-1]-(90+97))<=1, (mode,lcd,x,ink)
            c.mem_write(sy["ftx_ft4"], pack("<I",0))
            c.mem_write(sy["adc"], pack("<I",sample))
            call(c, sy["view_invalidate"])
        rail=(399,89,476,266)
        assert live.crop(rail).tobytes()==cached.crop(rail).tobytes()
        if "key_height" in sy:
            # Validate fractional coverage against each scanline of the actual
            # gradient. Include darkened paging and both corresponding LCDs.
            from PIL import ImageDraw, ImageFont
            import re
            font=ImageFont.truetype(str(ROOT/"samples/ftx/font/ft-panel-sc.ttf"),120)
            edges=(ROOT/"samples/ftx/j140_key_face.h").read_text()
            centres=[int(re.findall(r"0x[0-9a-f]+",row)[2],16)
                     for row in edges.splitlines() if "0x" in row]
            for label,x,y,disabled in (("自动选台" if "ft_slot_bar" in sy else "自动回复",405,134,False),("下页",441,170,True)):
                for column,ch in enumerate(label):
                    surface=Image.new("L",(128,120))
                    ImageDraw.Draw(surface).text((0,104),ch,font=font,anchor="ls",fill=255)
                    glyph=surface.resize((16,15),Image.Resampling.LANCZOS)
                    for j in range(15):
                        bg=centres[9+j]
                        fg=0xf7be
                        if disabled:
                            bg=(bg&0xf7de)>>1
                            fg=0x94b3
                        for i in range(16):
                            a=round(15*(glyph.getpixel((i,j))/255)**.85)
                            rgb=[]
                            for shift,limit in ((11,31),(5,63),(0,31)):
                                level=(((bg>>shift)&limit)*(15-a)+((fg>>shift)&limit)*a+7)//15
                                rgb.append((level*255+limit//2)//limit)
                            assert live.getpixel((x+16*column+i,y+j))==tuple(rgb),(ch,i,j)
        for y in (89,125,161,197,233):
            # The centre of the bottom bevel survives the next cached header draw.
            assert min(live.getpixel((418,y+32)))>=72
            assert max(live.getpixel((418,y+33)))<=30
        for y in (122,158,194,230):
            assert len(set(live.crop((403,y,433,y+3)).getdata()))==1
        assert max(live.getpixel((458,193)))<min(live.getpixel((418,193)))
        assert live.getpixel((400,100))[2]>200
        if "sender_grid" in sy:
            # All ten rows must contain the same complete ASCII message and
            # distance, including the two rows straddled by the old tile seam.
            msg=b"CQ JA1ABC PM95"
            for i in range(10):
                c.mem_write(row,msg.ljust(36,b"\0")+pack("<4iBB",1250,42,3,-13,0,11))
                call(c,sy["view_publish"],242,1)
            for lcd in (0,1):
                picture=screen(draw(lcd))
                for x,right in ((35,178),(269,299),(307,349),(362,395)):
                    boxes=[picture.crop((x,102+17*i,right,118+17*i)).convert("L") for i in range(10)]
                    assert max(boxes[0].getdata())>200 and len({b.tobytes() for b in boxes})==1,(lcd,x)
            if "list_band" in sy:
                call(c, sy["view_reset"], 0)
                slots = [260,260,260,261,261,261,262,262,262,263,263,264]
                public = []
                examples = [b"CQ JA1ABC PM95", b"CQ DL1ABC JO62", b"CQ F4ABC JN18"]
                for i, slot in enumerate(slots):
                    cq = slot != 261
                    message = examples[i % 3] if cq else b"K1ABC JA1ABC -13"
                    if cq:
                        public.append(slot)
                    c.mem_write(row, message.ljust(36,b"\0")+pack("<4iBB",1250,42,3 if cq else 6,-13,0,11 if cq else 0))
                    call(c, sy["view_publish"], slot, 1)

                def check_slot_lines(expected, capture=False):
                    for lcd in (0, 1):
                        picture = screen(draw(lcd))
                        for i in range(10):
                            y = 118 + 17*i
                            color = picture.getpixel((2,y))
                            blue = color[2] > 180 and color[0] < 80
                            assert blue == (i+1 < len(expected) and expected[i]!=expected[i+1]), (lcd,i,color)
                            if blue:
                                assert picture.crop((0,y,395,y+1)).getcolors(1) == [(395,color)]
                                assert all(picture.getpixel(pos)!=color for pos in ((2,y-1),(2,y+1),(395,y)))
                        if capture and initial_scope and lcd == 0:
                            picture.save(folder/"ui-slot-lines.png")
                check_slot_lines(slots[-10:], capture=True)
                call(c, sy["ft_history_action"], 0)
                check_slot_lines(slots[:10])
                call(c, sy["ft_history_action"], 2)
                check_slot_lines(public)
                call(c, sy["ft_history_action"], 2)
            from tools.build_705_ft_panel_assets import LABELS
            caption=[]
            def read_filter(cpu,*_):
                r0,r1,r2,_,paint=p.surface.args(5)
                if r1>=399 and r2==206 and paint:
                    caption.append(list(LABELS)[r0-1])
            addr=sy["panel_word"]&~1
            token=c.hook_add(uc.UC_HOOK_CODE,read_filter,begin=addr,end=addr)
            c.mem_write(row,b"K1ABC JA1ABC 73".ljust(36,b"\0")+pack("<4iBB",1250,42,6,-13,0,0))
            call(c,sy["view_publish"],264,1)
            for current,next_action in ((0,"cq_only"),(1,"all"),(0,"cq_only")):
                picture=screen(draw(0))
                words=["".join(chr(g["key"]) for g in e["glyphs"]) for e in p.surface.events] + bitmap_messages(p.surface)
                assert caption.pop()==next_action and ("K1ABC JA1ABC 73" in words)==(current==0)
                if initial_scope and current==0: picture.save(folder/"ui-manual-distance.png")
                assert call(c,sy["ft_panel_touch"],440,213)
            assert call(c,sy["ft_panel_touch"],440,213)
            c.hook_del(token)
        # Use the actual panel touch handler for the menu and back.
        assert call(c,sy["ft_panel_touch"],440,249)
        call(c,sy["view_invalidate"])
        menu=screen(draw(0))
        for y in (140,171,202,233,264):
            assert menu.getpixel((340,y))==menu.getpixel((380,y))
            assert min(menu.getpixel((380,y)))>max(menu.getpixel((380,y-1)))
        if "sender_grid" in sy:
            for y in (244,244):  # sequence toggles in the menu itself
                assert call(c,sy["ft_panel_touch"],100,y)
                assert val(c,sy["ft_page"])==5
                call(c,sy["view_invalidate"]);draw(0)
            assert call(c,sy["ft_panel_touch"],100,186)
            assert val(c,sy["ft_page"])==2
            call(c,sy["view_invalidate"])
            setup=screen(draw(0))
            if initial_scope: setup.save(folder/"ui-station.png")
            assert call(c,sy["ft_panel_touch"],440,248)
            assert val(c,sy["ft_page"])==5 and checked[0]>0 and not pending
        if initial_scope: menu.save(folder/"ui-menu.png")
        assert call(c,sy["ft_panel_touch"],440,249)
        call(c,sy["view_invalidate"])

    if panel_top < 86:
        # Place a contrasting scope border under the left and folded right tiles.
        # Exercise both first paint and cached paint on both LCD outputs.
        strip = slice(panel_top * 480 * 4, 86 * 480 * 4)
        for page in (0, 2, 0):
            c.mem_write(sy["ft_page"], pack("<I", page))
            call(c, sy["view_invalidate"])
            for i in (0, 1):
                c.mem_write(0x20380CBC, bytes([i]))
                outputs[i][:strip.stop] = b"\x76" * strip.stop
                call(c, sy["ftx_frame"], instruction_limit=0)
                band = bytes(outputs[i][strip])
                assert outputs[i][:strip.start] == b"\x76" * strip.start
                assert band == band[:4] * (len(band) // 4)
                assert band[:4] != b"\x76" * 4
        call(c, sy["view_invalidate"])

    # A differential stock redraw may leave these native buffers untouched.
    # Mark their backing pixels and check exactly what one FT paint changes.
    def scope_pixels():
        return bytes(p.surface.targets[16][3]) + bytes(p.surface.targets[17][3])

    saved = [bytes(p.surface.targets[i][3]) for i in (16, 17)]
    for i in (16, 17):
        pixels = p.surface.targets[i][3]
        pixels[:] = b"\x59" * len(pixels)
    before = scope_pixels()
    if revised:
        call(c, sy["view_invalidate"])
    call(c, sy["ftx_frame"], instruction_limit=0)
    overwritten = sum(a != b for a, b in zip(before, scope_pixels()))
    assert (overwritten == 0) == revised
    for i, content in zip((16, 17), saved):
        p.surface.targets[i][3][:] = content
    # Set the actual committed layer fields, exercise the same clipping as a
    # frame composed by the stock knob handlers, including simultaneous layers.
    if revised:
        full = draw(0)

        def crop(data, box):
            x, y, right, bottom = box
            return b"".join(
                data[(j * 480 + x) * 4 : (j * 480 + right) * 4]
                for j in range(y, bottom)
            )

        boxes = [(361, panel_top, 480, 272), (0, 157, 118, 272), (130, 153, 350, 239)]
        for mask in range(1, 8):
            c.mem_write(0x204BD028, bytes([bool(mask & 1)]))
            c.mem_write(0x204BD19E, bytes([bool(mask & 2), 2]))
            c.mem_write(0x204BD0BC, bytes([bool(mask & 4), 1]))
            for i in range(2):
                c.mem_write(0x20380CBC, bytes([i]))
                outputs[i][:] = b"\x76" * len(outputs[i])
                call(c, sy["ftx_frame"], instruction_limit=0)
                for bit, box in enumerate(boxes):
                    if mask & (1 << bit):
                        assert set(crop(outputs[i], box)) == {0x76}
                assert crop(outputs[i], (121, 102, 300, 150)) == crop(
                    full, (121, 102, 300, 150)
                )
        c.mem_write(0x204BD028, b"\0")
        c.mem_write(0x204BD19E, bytes(2))
        c.mem_write(0x204BD0BC, bytes(2))

    for i in (0, 1):
        draw(i)
    c.mem_write(0x20380431, b"\x09")
    call(c, sy["ftx_input"])
    c.mem_write(0x20380431, b"\0")
    assert val(c, sy["state"]) == 0
    tick(p)
    assert call(c, 0x200F1E48) == initial_scope
    delta = []
    panel_delta = []
    for i in (0, 1):
        after = draw(i)
        bottom = slice(266 * 480 * 4, None)
        delta.append(sum(a != b for a, b in zip(original[i][bottom], after[bottom])))
        panel_delta.append(
            sum(
                a != b
                for a, b in zip(original[i][panel_top * 480 * 4 :], after[panel_top * 480 * 4 :])
            )
        )
    if revised:
        assert panel_delta == delta == [0, 0], (panel_delta, delta, initial_scope)
    return {
        "panel_top": panel_top,
        "repeated_draws": result, "synchronized_glyph_uploads": checked[0],
        "scope_backing_bytes_changed": overwritten,
        "bottom_byte_differences": delta,
        "whole_panel_byte_differences": panel_delta,
        "dat_sha256": sha256(dat).hexdigest(),
    }


def message_pressure(folder, stock, fixed):
    from PIL import Image
    dat=(folder/"bench-rx.dat").read_bytes()
    sy=symbols(folder/"rx.elf")
    p=settings.SettingsGuest(stock,front_panel=True)
    c=p.cpu
    main=bytes(decode_main(dat)[1])
    c.mem_write(BASE,main)
    c.ctl_remove_cache(BASE, BASE+len(main))
    map_atlas(c,dat)
    assert call(c,sy["ft_data_ready"])
    call(c,sy["ftx_allocate"],0,instruction_limit=0)
    call(c,sy["view_reset"],0)
    c.mem_write(sy["state"],pack("<I",2))
    # The RF text of the photographed row is unknown. Use a valid report with
    # the same UI characteristics, including the Russian flag and 1497 Hz.
    msg=b"<...> RA9UAD -17"
    row=call(c,sy["row_text"],0)
    c.mem_write(row,msg.ljust(36,b"\0")+pack("<4iBB",1497,42,6,-17,0,0))
    call(c,sy["view_publish"],80,1)
    active=[False]
    def string_start(cpu,*_):
        active[0]=bytes(cpu.mem_read(cpu.reg_read(arm.UC_ARM_REG_R2),len(msg)))==msg
    def string_end(*_):
        active[0]=False
    c.hook_add(uc.UC_HOOK_CODE,string_start,begin=0x20142698,end=0x20142698)
    c.hook_add(uc.UC_HOOK_CODE,string_end,begin=0x201427a0,end=0x201427a0)
    denied=[]
    requests=[]
    alloc=p.surface.alloc
    def counted(n):
        if active[0]:
            requests.append(n)
        return alloc(n)
    def font_unavailable(cpu,*_):
        if active[0]:
            denied.append(1)
            cpu.reg_write(arm.UC_ARM_REG_R0,0)
            cpu.reg_write(arm.UC_ARM_REG_PC,cpu.reg_read(arm.UC_ARM_REG_LR))
    def pixels():
        call(c,sy["view_invalidate"])
        call(c,sy["view_draw"],80,1000,instruction_limit=0)
        _,w,h,buf=p.surface.targets[7]
        return Image.frombytes("RGBA",(w,h),bytes(buf)).convert("RGB")
    with patch.object(p.surface,"alloc",counted):
        before=pixels()
    c.hook_add(uc.UC_HOOK_CODE,font_unavailable,begin=0x20197568,end=0x20197568)
    after=pixels()
    box=(35,102,175,116)
    assert max(before.crop(box).convert("L").getdata())>180
    assert after.crop((185,102,352,116)).tobytes()==before.crop((185,102,352,116)).tobytes()
    if fixed:
        assert not requests and not denied and before.crop(box).tobytes()==after.crop(box).tobytes()
        assert msg.decode() in bitmap_messages(p.surface)
    else:
        assert requests and denied and max(after.crop(box).convert("L").getdata())<60
    return dict(sample=msg.decode(),hz=1497,old_painter_allocations=len(requests),unavailable_font_runs=len(denied),
                body_visible_under_pressure=fixed)


def deferred_setup(folder,stock):
    """Model a reader that consumes CPU uploads only at the next VG finish."""
    dat=(folder/"bench-rx.dat").read_bytes()
    sy=symbols(folder/"rx.elf")
    p=settings.SettingsGuest(stock,front_panel=True)
    c=p.cpu
    image=bytes(decode_main(dat)[1])
    c.mem_write(BASE,image)
    c.ctl_remove_cache(BASE,BASE+len(image))
    map_atlas(c,dat)
    assert call(c,sy["ft_data_ready"])
    c.mem_write(sy["ft_page"],pack("<I",2))
    pending=[]
    reads=changed=0
    def upload(cpu,*_):
        ptr,stride,fmt,x,y,w,h=p.surface.args(7)
        if p.surface.target==7 and ptr>=0x20000000 and fmt==3:
            stride=(stride^0x80000000)-0x80000000
            for n in range(h):
                a=ptr+n*stride
                pending.append((a,bytes(cpu.mem_read(a,2*w))))
    def finish(cpu,*_):
        nonlocal reads,changed
        for a,data in pending:
            reads+=1
            changed+=cpu.mem_read(a,len(data))!=data
        pending.clear()
    c.hook_add(uc.UC_HOOK_CODE,upload,begin=0x20263B12,end=0x20263B12)
    c.hook_add(uc.UC_HOOK_CODE,finish,begin=0x20263190,end=0x20263190)
    call(c,sy["view_draw"],0,0,instruction_limit=0)
    assert not pending and reads
    return dict(dat_sha256=sha256(dat).hexdigest(),source_scanlines=reads,changed_before_finish=changed)


if __name__ == "__main__":
    stock = load((ROOT / "firmware/705J140.dat").read_bytes())
    result = {
        "rx5": compare(OUT.parent / "j140-ftx-rx5", stock),
        "tx1": compare(OUT, stock,panel_top=84),
        "tx1_scope_initially_off": compare(OUT, stock, 0,panel_top=84),
    }
    previous=deferred_setup(OUT.parent/"j140-ftx-tx2b",stock)
    current=deferred_setup(OUT,stock)
    assert previous["changed_before_finish"]>0 and current["changed_before_finish"]==0
    result["deferred_setup"]={"TX2b":previous,"candidate":current}
    result["message_pressure"]={"TX2e":message_pressure(OUT.parent/"j140-ftx-tx2e",stock,False),
                                "candidate":message_pressure(OUT,stock,True)}
    result["dat_sha256"] = result["tx1"]["dat_sha256"]
    (OUT / "ui.json").write_text(json.dumps(result, indent=2))
    print(result)
