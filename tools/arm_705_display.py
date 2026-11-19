"""Build and load the offline ARM localization experiment. Writes only emulator RAM."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from struct import pack, unpack
import subprocess

from tools.emulate_705 import call, uc
from tools.render_705_stock_row import require
from tools.zh_705_row import (AUTO_LABEL, AUTO_SOURCE, DISPLAY_PAGE, LAB_SLOT, PAGE_FONT_SHA,
                             STOCK_LABEL, TIMEOUTS, ZH_LABEL)


CODE, STATE, WORDS = 0x21007000, 0x21008000, 0x2100B000
FONT_ROM, MAX_FONT = 0x21100000, 0x10000
LANGUAGE_OPTION = 0x21010000
DISPLAY_DESC, ORIGINAL_CHOICES = 0x202F0DFC, 0x202ED520
THIRD_OPTION_FLAG = STATE + 0x2FF8
DISPLAY_MODE = STATE + 0x2FFC
THIRD_TOKEN, THIRD_LABEL = "Chinese", "简体中文"
SET_CAPTION = "设置"
SET_IMAGE = 0x189ED180
SET_IMAGE_SHA = "ceaee5afd23599ff3607235ab9ffd690df0f1da8997be6cbecf0948315fb107c"
SET_CAPTION_RECT = (26, 65, 64, 83)
SITES = {
    0x20146864: ("layout_select", 0xE1A04000),
    0x20146ADC: ("draw_select", 0xE1A04000),
    0x20146958: ("layout_finish", 0xE28DD008),
    0x20146B90: ("draw_finish", 0xE28DD014),
}


def build(output):
    root = Path(__file__).resolve().parents[1]
    output.mkdir(parents=True, exist_ok=True)
    elf, binary = output / "display-arm.elf", output / "display-arm.bin"
    subprocess.run(["arm-none-eabi-gcc", "-mcpu=cortex-a9", "-marm", "-mfloat-abi=soft", "-Os",
                    "-ffreestanding", "-fno-builtin", "-nostdlib", "-Wl,--build-id=none,-e,init_font",
                    f"-Wl,-Ttext={CODE:#x}", "-o", str(elf),
                    str(root / "samples/705-display-arm.S"), str(root / "samples/705-display-arm.c")], check=True)
    subprocess.run(["arm-none-eabi-objcopy", "-O", "binary", str(elf), str(binary)], check=True)
    listing = subprocess.check_output(["arm-none-eabi-nm", "--defined-only", str(elf)], text=True)
    symbols = {fields[2]: int(fields[0], 16) for line in listing.splitlines() if len(fields := line.split()) == 3}
    return binary.read_bytes(), symbols


def base_words():
    entries = [(8, STOCK_LABEL, ZH_LABEL), (4, AUTO_SOURCE, AUTO_LABEL)]
    for source, target in DISPLAY_PAGE.items():
        scope = 1 if source == "ディスプレイ設定" else 5 if source.startswith("LCD") else 3
        entries.append((scope, source, target))
    entries.extend((3, n + "分", n + " 分钟") for n in TIMEOUTS)
    return entries


def word_table(entries=None):
    if entries is None:
        entries = base_words()
    rows = []
    for scope, source, target in entries:
        a, b = (s.encode("utf-16-le") for s in (source, target))
        require(len(a) <= 48 and len(b) <= 48, "ARM word table field too long")
        rows.append(pack("<3H48s48s", scope, len(a)//2, len(b)//2, a, b))
    return pack("<I", len(rows)) + b"".join(rows)


def set_caption_preview(cpu, font):
    """Replace the caption in a copy of the original padded BGRA tile."""
    from PIL import Image, ImageDraw, ImageFont

    caption_font = ImageFont.truetype(BytesIO(font), 18)
    replacement = None

    def preview(ptr, width, stride, height, pixels):
        nonlocal replacement
        if (ptr, width, stride, height) != (SET_IMAGE, 90, 96, 90) or cpu.mem_read(DISPLAY_MODE, 4)[0] != 2:
            return pixels
        if sha256(pixels).hexdigest() != SET_IMAGE_SHA:
            return pixels
        if replacement is None:
            tile = Image.frombytes("RGBA", (stride, height), pixels, "raw", "BGRA")
            left, top, right, bottom = SET_CAPTION_RECT
            caption = tile.crop((left-1, top, left, bottom)).resize((right-left, bottom-top))
            ImageDraw.Draw(caption).text((45-left, 74-top), SET_CAPTION, font=caption_font, fill="white", anchor="mm")
            tile.paste(caption, (left, top))
            replacement = tile.tobytes("raw", "BGRA")
        return replacement

    return preview


class DisplayArm:
    def __init__(self, guest, font, build_result, table=None, *, font_sha=PAGE_FONT_SHA, third_language=False,
                 text_hooks=True):
        require(guest.front_panel and 0 < len(font) <= MAX_FONT and sha256(font).hexdigest() == font_sha,
                "ARM experiment needs a verified J140 font subset")
        code, symbols = build_result
        require(0 < len(code) <= 0x1000, "unexpected ARM code size")
        if table is None:
            table = word_table()
        require(4 <= len(table) <= 0x4000, "unexpected ARM word table size")
        rows = unpack("<I", table[:4])[0]
        require(rows <= 128 and len(table) == 4 + rows*102, "invalid ARM word table")
        cpu = self.cpu = guest.cpu
        for address, size, permissions, data in (
            (LAB_SLOT, 0x3000, uc.UC_PROT_READ | uc.UC_PROT_WRITE, b""),
            (FONT_ROM, (len(font)+0xFFF) & ~0xFFF, uc.UC_PROT_READ, font),
            (CODE, 0x1000, uc.UC_PROT_READ | uc.UC_PROT_EXEC, code),
            (STATE, 0x3000, uc.UC_PROT_READ | uc.UC_PROT_WRITE, b""),
            (WORDS, 0x4000, uc.UC_PROT_READ, table),
        ):
            cpu.mem_map(address, size, permissions)
            if data:
                cpu.mem_write(address, data)
        require(call(cpu, symbols["init_font"], len(font), instruction_limit=2_000_000) == 1,
                "original FreeType rejected the guest-provided font")
        sites = dict(SITES) if text_hooks else {}
        if third_language:
            sites[0x2009F538] = ("compat_display_preview", 0xE12FFF1E)
            sites[0x20095E94] = ("sync_display_preview", 0xE7C11090)
            require(unpack("<I", cpu.mem_read(DISPLAY_DESC+0x10, 4))[0] == 1 and
                    unpack("<I", cpu.mem_read(DISPLAY_DESC+0x38, 4))[0] == ORIGINAL_CHOICES,
                    "unexpected original display choices")
            # Each language has a row of max+1 pointers. Leave the shared stock table and A8 intact.
            en, jp = (bytes(cpu.mem_read(ORIGINAL_CHOICES + i, 8)) for i in (0, 8))
            token = pack("<I", LANGUAGE_OPTION+24)
            cpu.mem_map(LANGUAGE_OPTION, 0x1000, uc.UC_PROT_READ)
            cpu.mem_write(LANGUAGE_OPTION, en + token + jp + token + THIRD_TOKEN.encode("ascii") + b"\0")
            cpu.mem_write(DISPLAY_DESC+0x10, pack("<I", 2))
            cpu.mem_write(DISPLAY_DESC+0x38, pack("<I", LANGUAGE_OPTION))
            cpu.mem_write(THIRD_OPTION_FLAG, pack("<I", 1))
            if text_hooks and all(call(cpu, symbols["has_glyph"], ord(ch)) for ch in SET_CAPTION):
                guest.surface.image_preview = set_caption_preview(cpu, font)
        for address, (symbol, expected) in sites.items():
            target = symbols[symbol]
            require(CODE <= target < CODE+len(code) and target % 4 == 0, "invalid ARM entry")
            require(cpu.mem_read(address, 4) == pack("<I", expected), f"unexpected original ARM word at {address:#x}")
            # shortcut: branch only within a fresh Unicorn RAM image; no persistent integration or output image.
            relative = (target-address-8)//4
            require(-(1 << 23) <= relative < 1 << 23, "ARM entry outside branch range")
            cpu.mem_write(address, pack("<I", 0xEA000000 | (relative & 0xFFFFFF)))
        self.evidence = {"code_sha256": sha256(code).hexdigest(), "table_sha256": sha256(table).hexdigest(),
                         "font_sha256": sha256(font).hexdigest(), "table_rows": rows,
                         "ram_branches": [hex(address) for address in sites],
                         "set_caption": guest.surface.image_preview is not None}

    def counts(self):
        applied, restored, pending = unpack("<3I", self.cpu.mem_read(STATE, 12))
        require(applied == restored and pending == 0, "ARM renderer did not restore its state")
        return applied

    def missing(self):
        return unpack("<I", self.cpu.mem_read(STATE+12, 4))[0]
