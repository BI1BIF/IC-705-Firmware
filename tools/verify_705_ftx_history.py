"""Exercise scrolling, silent slots and flag pixels from both J140 resource banks."""



import json

from hashlib import sha256

from math import asin, cos, radians, sin, sqrt

from struct import pack



from tools.replay_705_gps_inputs import (

    BYTE_RX,

    GPS_EXPIRE,

    GPS_INIT,

    GPS_MODE,

    POSITION_AGE,

    RMC,

    nmea,

)

from tools.verify_705_ftx_rx import (

    BASE,
    bitmap_messages,

    OUT,

    ROOT,

    SettingsGuest,

    call,

    decode_main,

    load,

    map_atlas,

    symbols,

    uc,

    val,

)





def trial(dat, bank):

    p = SettingsGuest(

        load((ROOT / "firmware/705J140.dat").read_bytes()), front_panel=True

    )

    c, sy = p.cpu, symbols(OUT / "rx.elf")

    image = bytes(decode_main(dat)[1])

    c.mem_write(BASE, image)

    c.ctl_remove_cache(BASE, BASE + len(image))

    if bank == 0x18000000:

        c.mem_map(bank, 0x5f0000, uc.UC_PROT_READ)

        c.mem_write(bank, bytes(c.mem_read(0x185f0000, 0x5f0000)))

    map_atlas(c, dat, bank)

    c.mem_write(0x2038089D, bytes([bank == 0x18000000]))

    assert call(c,sy["ft_data_ready"])

    call(c, sy["ftx_allocate"], 0, instruction_limit=0)

    call(c, sy["view_reset"], 0)

    row = call(c, sy["row_text"], 0)

    c.mem_write(sy["state"], pack("<I", 2))

    codes = json.loads((OUT / "countries.json").read_text())["codes"]



    def add(msg, slot, sender=3, grid_pos=0, assisted=False):

        c.mem_write(

            row,

            msg.encode().ljust(36, b"\0")

            + pack("<4iBB", 1250, 42, sender, -13, assisted, grid_pos),

        )

        call(c, sy["view_publish"], slot, 1)



    def labels():

        # Collect glyph commands for a full repaint, including cached rows.

        call(c, sy["view_invalidate"])

        p.surface.events.clear()

        p.surface.pixel_writes.clear()

        call(c, sy["view_draw"], 1, 1000, instruction_limit=0)

        return [

            "".join(chr(g["key"]) for g in e["glyphs"]).strip()

            for e in p.surface.events

        ] + bitmap_messages(p.surface)



    cases = {

        "MM1AWV": "gb-sct",

        "BG7YOZ": "cn",

        "UA9SIX": "ru",

        "MM1AWV/P": "gb-sct",

        "EA8/DL1ABC": "es",

        "DL1ABC/MM": None,

        "JA1ABC": "jp",

        "9V1ABC": "sg",

        "VU2ABC": "in",

        "HB0ABC": "li",

        "K1ABC": "us",

        "XX9ABC": "mo",

    }

    flag_pixels = {}
    def capture_flag(cpu, *_):
        ptr, stride, fmt, x, y, w, h = p.surface.args(7)
        if (w, h) == (16, 12):
            assert stride == 2**32 - 32 and fmt == 3
            flag_pixels[y] = bytes(cpu.mem_read(ptr - 11*32, 384))
    c.hook_add(uc.UC_HOOK_CODE, capture_flag, begin=0x20263B12, end=0x20263B12)

    for i, (callsign, code) in enumerate(cases.items()):
        flag_pixels.clear()

        add("CQ " + callsign + " AA00", i)

        words = labels()

        n = min(i, 9)

        rect = [18, 272 - (102 + n * 17 + 2) - 12, 16, 12]

        writes = [w for w in p.surface.pixel_writes if w["rect"] == rect]

        assert "CQ " + callsign + " AA00" in words

        if code:

            assert len(writes) == 1
            tile = bytes(c.mem_read(bank + 0x5F0000 + 128*codes.index(code), 128))
            expected = b"".join(tile[2*k:2*k+2] for v in tile[32:] for k in (v&15, v>>4))
            assert flag_pixels[rect[1]] == expected

        else:

            assert not writes

    for i in range(12, 30):

        add(f"CQ K1ABC {i:04}", i)



    def displayed():

        return [w for w in labels() if w.startswith("CQ ")]



    recent = displayed()

    assert recent == [f"CQ K1ABC {i:04}" for i in range(20, 30)]

    for slot in range(30, 40):

        call(c, sy["view_publish"], slot, 0)

    assert displayed() == recent

    call(c, sy["ft_history_action"], 0)

    older = displayed()

    for slot in range(40, 46):

        add(f"CQ K1ABC {slot:04}", slot)

    assert displayed() == older

    for slot in range(46, 71):

        add(f"CQ K1ABC {slot:04}", slot)

    displayed()

    batch = val(c, sy["ftx_memory"]) + 32768 + val(c, sy["front"]) * (8 + 48 * 44)

    assert val(c, batch) == 48

    for _ in range(5):

        call(c, sy["ft_history_action"], 1)

    assert displayed() == [f"CQ K1ABC {i:04}" for i in range(61, 71)]

    call(c, sy["view_reset"], 0)

    assert displayed() == []

    msg = "CQ EX7CQ MN72"

    add(msg, 80, grid_pos=msg.index("MN72") + 1, assisted=True)

    add("K1ABC EX7CQ 73", 81, sender=6)

    add("K1ABC W1XYZ RR73", 81, sender=6)



    def reference(lat, lon):

        a, b, dl = map(radians, (lat, 42.5, 75 - lon))

        return round(

            12742.018

            * asin(sqrt(sin((a - b) / 2) ** 2 + cos(a) * cos(b) * sin(dl / 2) ** 2))

        )



    c.mem_write(sy["ftx_rtc"], pack("<I", 1))

    c.mem_write(GPS_MODE, b"\1")

    call(c, GPS_INIT)

    for byte in nmea(RMC.format(time="181100")):

        call(c, BYTE_RX, byte)



    def check_distance(source, expected):

        words = labels()

        numbers = [int(w) for w in words if w.isdigit() and abs(int(w) - expected) <= 1]

        assert source in words and len(numbers) == 2 and "--" in words, (

            expected,

            words,

        )

        return numbers[0]



    live = check_distance("km G", reference(35.5, 139.5))

    c.mem_write(POSITION_AGE, b"\0")

    call(c, GPS_EXPIRE)

    assert labels().count("--") == 3

    # Original My Position format: degrees, minutes in thousandths, hemisphere.

    c.mem_write(0x203EA85D, bytes([33]) + pack(">H", 30000) + b"S")

    c.mem_write(0x203EA861, bytes([70]) + pack(">H", 15000) + b"W")

    c.mem_write(GPS_MODE, b"\2")

    manual = check_distance("km M", reference(-33.5, -70.25))

    c.mem_write(sy["ftx_rtc"], pack("<I", 0))

    assert check_distance("km M", manual) == manual

    c.mem_write(0x203EA860, b"?")

    assert labels().count("--") == 3

    # The grid-bearing CQ has left all 48 visible history entries.
    c.mem_write(0x203EA860,b"S")
    for slot in range(82,151):
        add("K1ABC W1XYZ 73",slot,sender=6)
    add("K1ABC EX7CQ RR73",151,sender=6)
    saved=labels()
    assert saved.count(str(manual))==1 and saved.count("--")==9, saved
    c.mem_write(0x203EA860,b"N")
    moved=reference(33.5,-70.25)
    assert any(w.isdigit() and abs(int(w)-moved)<=1 for w in labels())
    # Compare the native label blits for the selected example with a fresh

    # rendering from the Chinese typeface, including their pixel positions.

    from PIL import Image, ImageDraw, ImageFont
    call(c,sy["view_reset"],0)

    add("CQ DL1ABC JO62",82)

    words = labels()
    assert "CQ DL1ABC JO62" in words and "QTH" in words

    text_end=max(w["rect"][0]+8 for w in p.surface.pixel_writes if w["rect"][2:]==[8,14])

    blits=[w["rect"] for w in p.surface.pixel_writes if w["rect"][2:]==[16,15]]

    region=[r for r in blits if r[1]==272-103-15]

    assert len(region)==2 and text_end+3<=region[0][0] and region[1][0]+16==253,(text_end,region)

    _,width,height,pixels=p.surface.targets[7]

    actual=Image.frombytes("RGBA",(width,height),bytes(pixels)).convert("RGB")
    font=ImageFont.truetype(str(ROOT/"samples/ftx/font/ft-panel-sc.ttf"),120)
    for ch,rect in zip("德国",region):
        large=Image.new("L",(128,120))
        ImageDraw.Draw(large).text((0,104),ch,font=font,fill=255,anchor="ls")
        alpha=large.resize((16,15),Image.Resampling.LANCZOS)
        reference=[]
        for coverage in alpha.tobytes():
            a=round(15*(coverage/255)**.85)
            rgb=[]
            for shift,limit in ((11,31),(5,63),(0,31)):
                bg=(0x0862>>shift)&limit
                fg=(0xf7be>>shift)&limit
                level=(bg*(15-a)+fg*a+7)//15
                rgb.append((255*level+limit//2)//limit)
            reference.extend(rgb)
        sample=actual.crop((rect[0],103,rect[0]+16,118))
        assert sample.tobytes()==bytes(reference),(bank,ch)
        assert len(set(sample.convert("L").tobytes()))>=12

    c.mem_write(sy["state"], pack("<I", 3))

    call(c, sy["ftx_step"])

    assert not val(c, sy["ftx_memory"])

    return {

        "flag_cases": cases,

        "native_jo62_label":"德国",

        "label_clearance_px":round(region[0][0]-text_end,2),

        "silent_slots": 10,

        "history_capacity": 48,

        "distance_to_MN72_km": {

            "internal_GPS": live,

            "manual": manual, "grid_retained_after_69_reports": True,

            "expired_blank": True,

            "invalid_manual_blank": True,

        },

        "held_while_browsing": True,

    }





if __name__ == "__main__":

    data = (OUT / "bench-rx.dat").read_bytes()

    result = {hex(bank): trial(data, bank) for bank in (0x18000000, 0x185F0000)}

    result["dat_sha256"] = sha256(data).hexdigest()

    (OUT / "history.json").write_text(json.dumps(result, indent=2))

