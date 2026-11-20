"""Build the offline button font and exercise its outlines in J140's text renderer."""
import json
import re
from hashlib import sha256
from pathlib import Path
from struct import pack

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from tools.emulate_705 import PROFILES, SCRATCH, arm, call, uc
from tools.probe_705_fonts import inspect_font
from tools.render_705_stock_row import make_surface, png

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".analysis/ftx-station"
J140 = ROOT / ".analysis/main-decode/705J140"
FONT = ROOT / ".analysis/zh-cn-preview/noto/NotoSansSC-VF.ttf"


def main():
    source = "\n".join((ROOT / "samples/ftx" / name).read_text("utf-8")
                       for name in ("operating.js", "panel.js"))
    button_lines = [line for line in source.splitlines() if 'key(' in line or '"button"' in line]
    chars = "".join(sorted(set(re.findall(r"[\u3400-\u9fff]", "".join(button_lines) + "偶奇"))))
    face = TTFont(FONT, recalcTimestamp=False)
    selection = subset.Subsetter()
    selection.populate(text=chars+"表示言語")
    selection.subset(face)
    face = instantiateVariableFont(face, {"wght": 500}, inplace=True)
    for name in face["name"].names:
        if name.nameID in (1, 3, 4, 6, 16):
            name.string = "IC705PanelSC".encode(name.getEncoding())
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "button-sc.ttf"
    face.save(target)
    stock = (J140 / "font-0.ttf").read_bytes()
    missing = [e["character"] for e in inspect_font(stock, chars)["glyphs"].values() if not e["glyph_id"]]
    image = (J140 / "main.bin").read_bytes()
    profile = PROFILES[sha256(image).hexdigest()]
    data = target.read_bytes()
    cpu, surface = make_surface(image, data, (J140 / "font-1.ttf").read_bytes())
    def use_label(cpu, _address, _size, _user):
        cpu.reg_write(arm.UC_ARM_REG_R1, SCRATCH+0x400)
        cpu.reg_write(arm.UC_ARM_REG_R2, len(label))
    cpu.hook_add(uc.UC_HOOK_CODE, use_label, begin=0x20197A90, end=0x20197A90)
    cpu.mem_write(SCRATCH+12,pack("<BxH",2,0xA7))
    for label in [chars[i:i+8] for i in range(0,len(chars),8)]+["地图","收听总览","回复此"]:
        cpu.mem_write(SCRATCH+0x400,label.encode("utf-16le"))
        surface.events.clear()
        surface.pixels[:] = bytes(len(surface.pixels))
        call(cpu,profile.draw_row,SCRATCH,0,1,0,instruction_limit=2000000)
        glyphs = [g for event in surface.events for g in event["glyphs"]]
        assert "".join(chr(g["key"]) for g in glyphs) == label and all(g["segments"] for g in glyphs), label
        assert any(surface.pixels[3::4])
        if label == "收听总览":
            (OUT / "j140-map-label.png").write_bytes(png(surface.width,surface.height,surface.pixels))
    report = dict(characters=chars, stock_missing="".join(missing), arm_drawn=len(chars),
                  subset_bytes=len(data), font_sha256=sha256(data).hexdigest())
    (OUT / "button-font-check.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),"utf-8")
    print(json.dumps(report,ensure_ascii=True))


if __name__ == "__main__":
    main()
