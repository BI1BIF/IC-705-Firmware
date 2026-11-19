"""Localize selected J140 display runs in the offline panel."""

from hashlib import sha256
from struct import unpack

from tools.emulate_705 import arm, call, uc
from tools.render_705_display import PAGE
from tools.render_705_stock_row import require


FONT_SHA = "5995e4107666666dbbb388930fe694b580d42e372200736ec3f8afb935867426"
PAGE_FONT_SHA = "3fab4325c600893616349c329439b1d1b3dc2245062d41af7d4cc38f1059718d"
STOCK_LABEL, ZH_LABEL = "表示言語", "显示语言"
DISPLAY_PAGE = {
    "ディスプレイ設定": "显示设置",
    "LCDバックライト": "LCD 背光",
    "LCDバックライト (自動調整中)": "LCD 背光（自动调节中）",
    "スクリーンセーバー (バッテリーパック)": "屏幕保护（电池供电）",
    "スクリーンセーバー (外部電源)": "屏幕保护（外部供电）",
    "画面消灯 [POWER]キー": "屏幕熄灭 [POWER] 键",
    "OFF": "关闭",
    "ON": "开启",
}
TIMEOUTS = ("1", "2", "5", "15", "30", "60")
PAGE_CHARS = ZH_LABEL + "表 分钟012356" + "".join(DISPLAY_PAGE.values())
AUTO_SOURCE, AUTO_LABEL = "自動調整", "自动调节"
OPTIONS_IDS = (0x8E, 0x8F, 0x90)
RUN, SLOT, SLOT_SIZE = 0x204CC1D4, 0x204C9FC0, 0x2214
CACHED_SMALL = 0x204C1770
LAB_SLOT, LAB_FONT = 0x21000000, 0x21003000
# Each path returns from the stock converter, selects a font and finally unwinds.
LAYOUT, DRAW = (0x20146844, 0x20146864, 0x20146958), (0x20146ABC, 0x20146ADC, 0x20146B90)
GLYPH_INDEX = 0x201971F0


class ChineseLabel:
    def __init__(self, guest, font):
        require(guest.front_panel, "the Chinese label requires the front panel")
        self.font_sha = sha256(font).hexdigest()
        require(self.font_sha in (FONT_SHA, PAGE_FONT_SHA), "expected a verified IC705 Lab SC font subset")
        self.full_page = self.font_sha == PAGE_FONT_SHA
        cpu, surface = guest.cpu, guest.surface
        cpu.mem_map(LAB_SLOT, 0x3000, uc.UC_PROT_READ | uc.UC_PROT_WRITE)
        cpu.mem_map(LAB_FONT, 0x4000, uc.UC_PROT_READ)
        cpu.mem_write(LAB_FONT, font)
        require(call(cpu, 0x20197410, LAB_SLOT+4, LAB_FONT, len(font), 0, 18,
                     instruction_limit=2_000_000) == 1, "original FreeType rejected the lab font")

        def glyphs(slot, chars):
            obj, = unpack("<I", cpu.mem_read(slot+4, 4))
            face, = unpack("<I", cpu.mem_read(obj+4, 4))
            return {ch: call(cpu, 0x2025B668, face, ord(ch)) for ch in sorted(set(chars))}

        self.glyphs = {"stock": glyphs(SLOT, ZH_LABEL+"表"),
                       "lab": glyphs(LAB_SLOT, PAGE_CHARS if self.full_page else ZH_LABEL+"表")}
        require(self.glyphs["stock"]["表"] == 3136 and self.glyphs["stock"]["显"] == self.glyphs["stock"]["语"] == 0
                and all(self.glyphs["lab"].values()), "unexpected stock or lab cmap")
        self.active, self.runs = None, []

        def bridge(cpu, address, _size, _data):
            if address in (LAYOUT[0], DRAW[0]):
                n = surface.reg("R0")
                if guest.language() != [1, 1] or not 0 < n <= 256:
                    return
                state = guest.state()
                if state["menu"] not in (67, 286):
                    return
                source = bytes(cpu.mem_read(RUN, n*2)).decode("utf-16-le", errors="surrogatepass")
                text = None
                if source == STOCK_LABEL:
                    text = ZH_LABEL
                else:
                    item, = unpack("<H", cpu.mem_read(PAGE+348, 2))
                    page = self.full_page and state["menu"] == 67 and state["first"] == 0
                    picker = self.full_page and state["menu"] == 286 and item in OPTIONS_IDS
                    editor = self.full_page and state["menu"] == 286 and item == 0x8C
                    if page or picker or editor:
                        text = DISPLAY_PAGE.get(source.rstrip(" "))
                        if source.endswith("分") and source[:-1] in TIMEOUTS:
                            text = source[:-1] + " 分钟"
                        elif editor and source == AUTO_SOURCE:
                            text = AUTO_LABEL
                if text is None:
                    return
                require(self.active is None, "nested Chinese label")
                path = DRAW if address == DRAW[0] else LAYOUT
                self.active = {"path": path, "stock": None, "glyphs": [], "source": source.rstrip(" "),
                               "text": text, "count": n}
            elif self.active is not None:
                active = self.active
                if address == active["path"][1]:
                    selected = surface.reg("R0")
                    require(selected in (SLOT, CACHED_SMALL), "unexpected stock font selection for translated text")
                    # Use the stock transient path even for values that normally use the persistent ASCII cache.
                    active["stock"] = bytes(cpu.mem_read(SLOT, SLOT_SIZE))
                    active["selected"] = hex(selected)
                    replacement = active["text"].encode("utf-16-le")
                    active["buffer"] = bytes(cpu.mem_read(RUN, max(active["count"]*2, len(replacement))))
                    # shortcut: translate exact runs in the renderer until the resource loader is modeled.
                    cpu.mem_write(RUN, replacement)
                    cpu.reg_write(arm.UC_ARM_REG_R5 if active["path"] == DRAW else arm.UC_ARM_REG_R7,
                                  len(replacement)//2)
                    cpu.mem_write(SLOT, bytes(cpu.mem_read(LAB_SLOT, SLOT_SIZE)))
                    cpu.reg_write(arm.UC_ARM_REG_R0, SLOT)
                elif address == GLYPH_INDEX:
                    active["glyphs"].append(surface.reg("R0"))
                elif address == active["path"][2]:
                    require(active["stock"] is not None, "missing original font selection")
                    cpu.mem_write(LAB_SLOT, bytes(cpu.mem_read(SLOT, SLOT_SIZE)))
                    cpu.mem_write(SLOT, active["stock"])
                    cpu.mem_write(RUN, active["buffer"])
                    self.runs.append({"stage": "draw" if active["path"] == DRAW else "layout",
                                      "source": active["source"], "text": active["text"],
                                      "selected": active["selected"], "indices": active["glyphs"]})
                    self.active = None

        for address in (*LAYOUT, *DRAW, GLYPH_INDEX):
            cpu.hook_add(uc.UC_HOOK_CODE, bridge, begin=address, end=address)
