"""Create the fixed Chinese label and region-name masks used by the FT panel."""
from pathlib import Path
import json
from struct import pack
import subprocess
import re
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
LABELS = {
    "cq":"呼叫 CQ","reply":"应答","info":"详情","auto":"自动选台","menu":"菜单",
    "live":"回到最新","clear":"取消选择","old":"上页","new":"下页","cq_only":"仅看 CQ",
    "all":"全部报文","stop":"■停止","send":"▶发送","seq":"自动通联","back":"返回",
    "start":"启用","exit":"退出","save":"保存","del":"删除","ok":"确定","set":"设置",
    "log":"通联日志","time":"授时来源","station":"本台设置","scope":"应答范围",
    "direct":"仅答本台","open":"含公开 CQ","call":"本台呼号","grid":"本台网格",
    "slot":"呼叫时隙","frequency":"音频","follow":"跟随","fixed":"固定","position":"取用本机位置",
    "on":"开","off":"关","rtc":"机内时钟","gps":"卫星授时","pending":"待存卡",
    "empty":"暂无通联","manual":"手动","finished":"已通联","filter":"筛选","waiting":"等待应答",
    "heard":"接收详情","place":"国家或地区","older":"上一条","newer":"下一条","queued":"等待时隙","idle":"待发送","stopped":"已停止","keying":"等待","rxmsg":"刚刚收到","draft":"准备发送","lasttx":"刚刚发出","sending":"正在发射","change":"改报文",
    "cancel":"取消待发","cut":"停止发射","end":"结束通联","home":"返回收听","saved":"日志已保存",
    "late":"本轮已过","next":"下次发射","other":"来叫","canceled":"已取消待发","cutdone":"已中断",
    "complete":"已发结束语","contact":"通联","resend":"重发","locator":"网格","report":"信号报告","rreport":"确认报告","again":"重试存卡",
}
def glyph_masks(chars):
    # 15 px type in a 16 x 15 cell. All glyphs share the same baseline.
    scale = 8
    face = ImageFont.truetype(str(ROOT / "samples/ftx/font/ft-panel-sc.ttf"), 15 * scale)
    masks = bytearray()
    for ch in chars:
        width = 8 if ch.isascii() else 16
        source_width = max(width * scale, face.getbbox(ch, anchor="ls")[2])
        surface = Image.new("L", (source_width, 15 * scale))
        pen = ImageDraw.Draw(surface)
        if ch == "▶":
            pen.polygon([(3*scale,2*scale),(3*scale,13*scale),(13*scale,7.5*scale)],fill=255)
        elif ch == "■":
            pen.rectangle((3*scale,3*scale,12*scale,12*scale),fill=255)
        else:
            pen.text((0,13*scale),ch,font=face,anchor="ls",fill=255)
        alpha = surface.resize((width, 15), Image.Resampling.LANCZOS)
        cell = Image.new("L",(16,15))
        cell.paste(alpha,(0,0))
        levels = [round(15 * (value / 255) ** .85) for value in cell.tobytes()]
        if ch != " " and max(levels) < 12:
            raise ValueError(f"missing foreground in FT glyph {ch}")
        masks.extend(a | (b << 4) for a,b in zip(levels[::2],levels[1::2]))
    return bytes(masks)


def coverage_palette():
    # Row, menu, selected row, then all 33 gradient rows of the two key states.
    face = (ROOT / "samples/ftx/j140_key_face.h").read_text()
    centres = [int(re.findall(r"0x[0-9a-f]+", row)[2],16)
               for row in face.splitlines() if "0x" in row]
    assert len(centres) == 33
    backgrounds = [0x0862,0x10e5,0x2b6c] + centres + [(c & 0xf7de) >> 1 for c in centres] + [0x1125]
    table = bytearray()
    for index, bg in enumerate(backgrounds):
        fg = 0x94b3 if 36 <= index < 69 else 0xf7be
        for alpha in range(16):
            rgb = 0
            for shift,mask in ((11,31),(5,63),(0,31)):
                a,b = (bg >> shift) & mask, (fg >> shift) & mask
                rgb |= ((a*(15-alpha) + b*alpha + 7)//15) << shift
            table.extend(pack("<H",rgb))
    return table


def build_key_faces(out):
    edges = [
        [int(value, 16) for value in re.findall(r"0x[0-9a-f]+", line)]
        for line in (ROOT / "samples/ftx/j140_key_face.h").read_text().splitlines() if "0x" in line
    ]
    pixels = bytearray()
    # All keys share the two edge pixels and a constant-colour centre.
    # A narrower key reads its left portion and the last two pixels of this strip.
    for dim in range(2):
        for l,li,mid,ri,r in edges:
            line = [l,li]+[mid]*168+[ri,r]
            pixels.extend(pack("<172H", *((v & 0xf7de) >> 1 if dim else v for v in line)))
            pixels.extend(bytes(8))  # 352-byte, cache-line-aligned stride
    (out/"key-faces.bin").write_bytes(pixels)
    return pixels


RX_CHARS = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ+-./?<>"
RX_SPLIT = 30


def message_tiles():
    """Immutable 8 × 14 RGB565 cells in the two list background colours."""
    font = ImageFont.truetype(str(ROOT / "samples/ftx/font/ft-message-latin.ttf"), 13 * 8)
    palette = coverage_palette()
    tiles = bytearray()
    for ch in RX_CHARS:
        width = max(64, font.getbbox(ch, anchor="ls")[2])
        glyph = Image.new("L", (width, 112))
        ImageDraw.Draw(glyph).text((0, 88), ch, font=font, fill=255, anchor="ls")
        alpha = glyph.resize((8, 14), Image.Resampling.LANCZOS)
        assert ch == " " or alpha.getextrema()[1] > 100, ch
        for background in (0, 2):
            for value in alpha.tobytes():
                i = 2 * (16 * background + round(15 * (value / 255) ** .85))
                tiles.extend(palette[i:i+2])
    return tiles


def build_panel_assets(codes, out):
    # ICU/CLDR uses the same ISO region keys as the offline flag atlas.
    region = json.loads(subprocess.check_output([
        "node","-e","const d=new Intl.DisplayNames(['zh-CN'],{type:'region'});"
        "console.log(JSON.stringify(JSON.parse(process.argv[1]).map(k=>d.of(k.slice(0,2).toUpperCase()))))",
        json.dumps(codes)],encoding="utf8"))
    for i,code in enumerate(codes):
        region[i]={"gb-eng":"英格兰","gb-sct":"苏格兰","gb-wls":"威尔士"}.get(code,region[i])
    labels=list(LABELS.values())
    strings=labels+region
    chars=sorted(set("".join(strings)))
    (out/"glyphs.bin").write_bytes(glyph_masks(chars))
    narrow=sum(ord(c)<128 for c in chars)
    offsets=[]; pool=bytearray()
    for s in strings:
        offsets.append(len(pool))
        for ch in s: pool.extend(pack("<H",chars.index(ch)+1))
        pool.extend(bytes(2))
    payload=pack("<4H",len(strings)*2,len(strings)*2+len(pool),narrow,len(labels))+b"".join(pack("<H",i) for i in offsets)+pool+coverage_palette()
    defines = [f'#define Z_{k} "\\177\\{i+1:03o}"' for i,k in enumerate(LABELS)]
    # Centre-line colours for the existing 29..39 pixel key heights; the
    # first two rows describe plain screen and menu backgrounds.
    heights = [[0] * 15 for _ in range(40)]
    heights[1] = [1] * 15
    heights[2] = [69] * 15
    for height in range(15,40):
        top = (height - 15) // 2
        heights[height] = [3 + 32*(top+y)//(height-1) for y in range(15)]
    (out/"ft_key_shades.h").write_text("static const uint8_t key_shades[40][15]={\n"+
        ",\n".join("{"+",".join(map(str,row))+"}" for row in heights)+"};\n")
    (out/"ft_panel_words.h").write_text("\n".join(defines)+"\n")
    return payload
