"""Replay long/short FAT pairs at the native picker and JPEG file-service boundaries."""
from hashlib import sha256
from pathlib import Path
from struct import pack, unpack_from
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from tools.emulate_705 import BASE, SP, arm, call
from tools.probe_705_sstv_tx import CANVAS_BYTES, COMMITTED, TX_IMAGE, decode_request, mount_card


def panel_guest(main, rom, region):
    from tools import render_705_stock_row as renderer
    from tools.render_705_display import load
    from tools.replay_705_settings import SettingsGuest
    dat = Path(f"firmware/705{region}140.dat").read_bytes()
    if region == "E":
        from tools.replay_705_e140_panel import panel_graphics, E_MAIN, A_PREFIX
        from tools.replay_705_stock_install import load_a
        stock, flash = load_a(dat, E_MAIN)
        graphics = panel_graphics(stock, flash, flash[:A_PREFIX])
    else:
        graphics = load(dat)
    with patch.object(renderer,"HEAP_START",0x20710000):
        guest = SettingsGuest(graphics, front_panel=True, rom=rom,
                              language_address=0x203eae44 if region=="E" else None)
    cpu = guest.cpu
    cpu.mem_write(BASE, bytes(main))
    cpu.ctl_remove_cache(BASE,BASE+len(main))
    return guest


def verify(main, rom, region):
    cpu=panel_guest(main,rom,region).cpu
    record, info, text = 0x20700000, 0x20700100, 0x20700200
    source = unpack_from("<I", main, rom(0x200f2e0c)-BASE)[0]
    def publish(index, name, alias, size, *, active=True, menu=279):
        cpu.mem_write(0x20828170, pack("<I", active))
        cpu.mem_write(0x203e84c9, pack("<H", menu))
        encoded = name.encode("ascii")
        cpu.mem_write(text, encoded[:28].ljust(28, b"\0"))
        cpu.mem_write(info+8, pack("<IH", text, min(len(encoded), 28)))
        data = bytearray(60)
        data[:len(alias)] = alias.encode()
        data[31] = len(alias)
        data[36:40] = pack("<I", size)
        cpu.mem_write(record, bytes(data))
        cpu.reg_write(arm.UC_ARM_REG_R0, record)
        cpu.reg_write(arm.UC_ARM_REG_R1, info)
        cpu.reg_write(arm.UC_ARM_REG_SP, SP)
        cpu.emu_start(rom(0x20064bf0), rom(0x20064bf4), count=1000)
        assert cpu.reg_read(arm.UC_ARM_REG_PC) == rom(0x20064bf4)
        result = bytes(cpu.mem_read(record, 60))
        cpu.mem_write(source+60*index, result)
        return result[:28].rstrip(b"\0")

    prefix = "Received_20260725_150031_station_"
    with TemporaryDirectory() as tmp:
        folder = Path(tmp)
        aliases = {}
        for i, color in enumerate(("red", "blue"), 1):
            path = folder/f"{prefix}{i}.jpg"
            Image.new("RGB", (320, 240), color).save(path)
            alias = f"RECEIV~{i}.JPG"
            aliases[alias] = path
            assert publish(i-1,path.name,alias,path.stat().st_size) == alias.encode()
        for active, menu in ((False,279),(True,278)):
            assert publish(2,path.name,alias,1,active=active,menu=menu) == path.name[:28].encode()
        assert publish(2,"ordinary.jpg","ORDINA~1.JPG",1) == b"ordinary.jpg"
        opened, handles = mount_card(cpu, folder, rom, aliases=aliases)
        call(cpu,rom(0x200f3910))
        cpu.mem_write(0x20380820, pack("<I", 3))
        selector = unpack_from("<I", main, rom(0x200f2dd4)-BASE)[0]
        cache = unpack_from("<I", main, rom(0x200f2e1c)-BASE)[0]
        rows = [bytes(cpu.mem_read(cache+36*i,28)).split(b"\0")[0] for i in range(4)]
        pixels = []
        for alias in aliases:
            cpu.mem_write(selector+4, pack("<H", rows.index(alias.encode())))
            call(cpu,rom(0x200f3a10))
            decoded = decode_request(cpu,rom)
            assert decoded == (alias,True), (alias, decoded, opened)
            assert not handles
            pixels.append(bytes(cpu.mem_read(TX_IMAGE,CANVAS_BYTES)))
        assert pixels[0] != pixels[1]
        call(cpu,rom(0x200c4f5c))
        assert bytes(cpu.mem_read(COMMITTED,13)).rstrip(b"\0") == alias.encode()
        cpu.mem_write(selector+4,pack("<H",rows.index(b"RECEIV~1.JPG")))
        call(cpu,rom(0x200f3a10))
        assert decode_request(cpu,rom) == ("RECEIV~1.JPG",True)
        call(cpu,rom(0x200c231c))
        assert decode_request(cpu,rom) == (alias,True)
        assert call(cpu,0x20376804) == 1
        assert bytes(cpu.mem_read(TX_IMAGE,CANVAS_BYTES)) == pixels[1]
        cpu.mem_write(0x203e84c9, pack("<H",21))
        from tools.probe_705_cw_pcm import simulated_gpio
        simulated_gpio(cpu, rom=rom)
        assert call(cpu,0x20376494, instruction_limit=2000000) == 1
        snapshot, = unpack_from("<I",cpu.mem_read(0x2082a9b8,4))
        assert snapshot and bytes(cpu.mem_read(snapshot,CANVAS_BYTES)) == pixels[1]
        return dict(opened=opened,selected=aliases[alias].name,
                    send_snapshot_matches=True,
                    canvas_sha256=[sha256(x).hexdigest() for x in pixels])
