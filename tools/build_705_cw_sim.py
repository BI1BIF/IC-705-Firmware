"""Package the existing J140 CW lab and original resources for the PC emulator."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from tools.attach_705_cw_replay import FRAME_COMPOSED
from tools.decode_705_main import J140_MAIN_SHA
from tools.emulate_705 import BASE
from tools.probe_705_cw_session import Lab, build
from tools.render_705_display import DAT_HASH, FONT_OFFSET, load, require


FORMAT = "ic705-j140-pc-cw-v1"
SUFFIX = ".ic705sim"
CODE = 0x2036A000
END = 0x20380000
MEMBERS = {"main": END-BASE, "font": FONT_OFFSET, "graphics": FONT_OFFSET, "small_font": FONT_OFFSET}
SYMBOLS = ("cw_sim_boot", "cw_state_anchor", "cw_rtx_worker", "cw_pcm_bridge")
PICKER_ID = 277
PICKER_TABLE = 0x202E65D0
PICKER_STRIDE = 72
PICKER_REFERENCES = (0x200CDD88, 0x200CFB80, 0x200D1988, 0x200D34DC, 0x20140B20)
KEYER_ENTRY = 0x20087990
PICKER_EMPTY_ROW = 0x200CDD08
RAW_PCM = 0x2010FE34


def digest(data):
    return sha256(data).hexdigest()


def picker_table(main, table_address, symbols, *, labels=(b"KEYER/DECODE", b"KEYER", b"CW DECODE"),
                 menu_id=PICKER_ID, code_shift=0, table_shift=0):
    """Keep the 277 stock records, then add one native selector and its two rows."""
    at = PICKER_TABLE + table_shift - BASE
    table = bytearray(main[at:at+PICKER_STRIDE*PICKER_ID])
    require(all(main[a+code_shift-BASE:a+code_shift-BASE+4] == pack("<I", PICKER_TABLE+table_shift)
                for a in PICKER_REFERENCES) and
            len(table) == PICKER_STRIDE*PICKER_ID and
            table[-28:-24] == b"\x01\x01\x00\x00" and main[at+len(table)+44:at+len(table)+48] != b"\x01\x01\x00\x00",
            "unexpected stock selector table")

    def record(i):
        return bytearray(table[i*PICKER_STRIDE:(i+1)*PICKER_STRIDE])

    parent, keyer, decode = (record(i) for i in (12, 0x5D, 0x5E))
    require(parent[:2] == b"\0\x02" and parent[68:] == pack("<I", 0x202E6258+table_shift),
            "unexpected selector template")
    require(menu_id >= PICKER_ID, "native menu ID overlaps a stock record")
    table.extend(bytes((menu_id - PICKER_ID)*PICKER_STRIDE))
    data = bytearray()
    strings = []
    after = table_address + len(table) + 3*PICKER_STRIDE
    for label in labels:
        strings.append(after+len(data))
        data.extend(label+b"\0")
    if len(data) % 2:
        data.append(0)
    rows = after+len(data)
    data.extend(pack("<HH", menu_id+1, menu_id+2))

    parent[1] = 1  # Last row index.
    parent[28] |= 1  # These rows are plain labels, with no row-specific input editor.
    fields = ((parent, {12: symbols["cw_picker_select"], 32: symbols["cw_picker_choice"],
                        48: strings[0], 56: strings[0], 68: rows}),
              (keyer, {8: 0, 52: strings[1], 60: strings[1]}),
              (decode, {8: 0, 52: strings[2], 60: strings[2]}))
    for desc, pointers in fields:
        for offset, pointer in pointers.items():
            desc[offset:offset+4] = pack("<I", pointer)
        table.extend(desc)
    return bytes(table+data)


def pack_image(dat, path, *, merged_entry=False, rx_diagnostics=False):
    require(path.suffix == SUFFIX, f"PC images require the {SUFFIX} suffix")
    main, font, graphics, stock_sha, small_font = load(dat)
    require(stock_sha == J140_MAIN_SHA == digest(main) and BASE+len(main) <= CODE,
            "unexpected J140 program or overlap with the PC-only code area")
    with TemporaryDirectory() as folder:
        code, bridges, symbols = build(Path(folder), rtx=True, stock_canvas=True,
                                       stock_state=True, text_base=CODE, sim_boot=True, merged_entry=merged_entry,
                                       rx_diagnostics=rx_diagnostics)
    if merged_entry:
        code = code.ljust((len(code)+3)&~3, b"\0")
        picker_address = CODE+len(code)
        code += picker_table(main, picker_address, symbols)
    end = CODE+len(code)
    require(end <= END and code[symbols["cw_state_anchor"]-CODE:][:4] == bytes(4),
            "unexpected CW code size or initial anchor")
    sites = {**Lab.stock, FRAME_COMPOSED: "30039fe5", 0x200D4EF0: "122401eb"}
    targets = {**bridges, FRAME_COMPOSED: symbols["cw_rtx_draw_bridge"], 0x200D4EF0: symbols["cw_sim_boot"]}
    if rx_diagnostics:
        sites[RAW_PCM] = "04009de5"
        targets[RAW_PCM] = symbols["cw_diag_raw_bridge"]
    if merged_entry:
        sites[KEYER_ENTRY] = "0d00a0e3"
        targets[KEYER_ENTRY] = symbols["cw_picker_open"]
        sites[PICKER_EMPTY_ROW] = "470055e3"
        targets[PICKER_EMPTY_ROW] = symbols["cw_picker_empty_row"]
    image = bytearray(main.ljust(CODE-BASE, b"\0"))
    image.extend(code)
    for site, target in targets.items():
        offset, delta = site-BASE, target-site-8
        require(image[offset:offset+4].hex() == sites[site] and CODE <= target < end and
                delta % 4 == 0 and -(1 << 25) <= delta < (1 << 25), f"bad J140 branch at {site:#x}")
        image[offset:offset+4] = pack("<I", 0xEA000000 | (delta >> 2 & 0xFFFFFF))
    if merged_entry:
        for site in PICKER_REFERENCES:
            image[site-BASE:site-BASE+4] = pack("<I", picker_address)
        site = 0x200CDCB0-BASE  # The renderer already uses a halfword for the output ID.
        require(image[site:site+4] == pack("<I", 0xE5D52000), "unexpected selector ID load")
        image[site:site+4] = pack("<I", 0xE1D520B0)
    payloads = dict(main=image, font=font, graphics=graphics, small_font=small_font)
    metadata = dict(format=FORMAT, dat_sha256=DAT_HASH, stock_main_sha256=J140_MAIN_SHA,
                    code_base=CODE, code_end=end, symbols={key: symbols[key] for key in SYMBOLS},
                    branch_sites={hex(site): hex(target) for site, target in targets.items()},
                    sha256={name: digest(data) for name, data in payloads.items()})
    if merged_entry:
        metadata["picker_id"] = PICKER_ID
        metadata["picker_choice"] = symbols["cw_picker_choice"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "x") as z:
        for name, data in {"manifest.json": json.dumps(metadata, sort_keys=True).encode(), **payloads}.items():
            z.writestr(ZipInfo(name), data, compress_type=ZIP_DEFLATED, compresslevel=6)
    return metadata


def load_image(path):
    require(path.suffix == SUFFIX, f"expected a {SUFFIX} PC image")
    with ZipFile(path) as z:
        require(sorted(z.namelist()) == sorted(["manifest.json", *MEMBERS]) and
                z.getinfo("manifest.json").file_size <= 4096, "invalid PC image inventory")
        metadata = json.loads(z.read("manifest.json"))
        require(metadata["format"] == FORMAT and metadata["dat_sha256"] == DAT_HASH and
                metadata["stock_main_sha256"] == J140_MAIN_SHA and metadata["code_base"] == CODE and
                CODE < metadata["code_end"] <= END and set(metadata["symbols"]) == set(SYMBOLS) and
                all(CODE <= address <= metadata["code_end"]-4 and address % 4 == 0
                    for address in metadata["symbols"].values()), "invalid J140 PC image")
        payloads = []
        for name, limit in MEMBERS.items():
            require(0 < z.getinfo(name).file_size <= limit, f"invalid size: {name}")
            data = z.read(name)
            require(digest(data) == metadata["sha256"][name], f"invalid digest: {name}")
            payloads.append(data)
        main, font, graphics, small_font = payloads
        offset = metadata["symbols"]["cw_state_anchor"] - BASE
        require(len(main) == metadata["code_end"]-BASE and main[offset:offset+4] == bytes(4),
                "invalid J140 PC image span or initial state")
        if "picker_id" in metadata:
            choice = metadata.get("picker_choice", 0)
            require(metadata["picker_id"] == PICKER_ID and CODE <= choice <= metadata["code_end"]-4 and
                    choice % 4 == 0 and main[choice-BASE:choice-BASE+4] == bytes(4) and choice != offset+BASE,
                    "invalid native selector state")
        return (main, font, graphics, metadata["sha256"]["main"], small_font), metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path, help="original Japanese 1.40 DAT")
    parser.add_argument("output", type=Path, help="new .ic705sim file, for computer testing only")
    parser.add_argument("--merged-entry", action="store_true", help="single KEYER / CW DECODE menu selector")
    parser.add_argument("--rx-diagnostics", action="store_true", help="show receive-pipeline diagnostics with --merged-entry")
    args = parser.parse_args()
    pack_image(args.dat.read_bytes(), args.output, merged_entry=args.merged_entry, rx_diagnostics=args.rx_diagnostics)
    print(f"{digest(args.output.read_bytes())}  {args.output}")


if __name__ == "__main__":
    main()
