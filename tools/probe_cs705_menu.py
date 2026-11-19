"""Locate selected menu references in CS-705 PE files and test raw DAT matches."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from struct import unpack_from

from tools.probe_ui_resources import ENCODINGS, hits


MENUS = {
    "CL_Common_Digital_RPT_Set": ("デジタルレピータセット", "Digital Repeater Set"),
    "CL_Common_RepeaterMonitorTimer": ("レピータモニタータイマー", "Repeater Monitor Timer"),
    "CL_Common_DispLang": ("表示言語", "Display Language"),
}


def data_range(image):
    if len(image) < 64 or image[:2] != b"MZ":
        raise ValueError("not an MZ image")
    pe, = unpack_from("<I", image, 0x3C)
    if pe + 24 > len(image) or image[pe:pe + 4] != b"PE\0\0":
        raise ValueError("invalid PE header")
    count, = unpack_from("<H", image, pe + 6)
    opt_len, = unpack_from("<H", image, pe + 20)
    table = pe + 24 + opt_len
    if table + count * 40 > len(image):
        raise ValueError("section table exceeds the image")
    for i in range(count):
        pos = table + i * 40
        if image[pos:pos + 8].rstrip(b"\0") == b".data":
            size, offset = unpack_from("<II", image, pos + 16)
            if not size or offset + size > len(image):
                raise ValueError(".data section exceeds the image")
            return offset, offset + size
    raise ValueError("no .data section")


def find_menu_references(section, base=0):
    menus = {}
    for key, (japanese, english) in MENUS.items():
        escaped = re.escape(key.encode("ascii"))
        labels = {}
        for encoding, label in (("cp932", japanese), ("ascii", english)):
            pattern = re.escape(label.encode(encoding)) + rb"[^\x00]{0,80}\(%" + escaped + rb"\)"
            labels[encoding] = [base + m.start() for m in re.finditer(pattern, section)]
        topics = re.finditer(rb"\x00" + escaped + rb"\t([0-9]+\.htm)\x00", section)
        menus[key] = {
            "label_file_offsets": labels,
            "help_links": [{"file_offset": base + m.start() + 1, "topic": m[1].decode("ascii")}
                           for m in topics],
        }
    return menus


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", nargs="+", type=Path, help="extracted CS705.exe files, never executed")
    parser.add_argument("--firmware", action="append", type=Path, default=[], help="raw comparison DAT (repeatable)")
    args = parser.parse_args()
    executable, firmware = {}, {}
    try:
        for path in args.exe:
            data = path.read_bytes()
            start, end = data_range(data)
            executable[path.as_posix()] = {"sha256": sha256(data).hexdigest(), "data_range": [start, end],
                                         "menus": find_menu_references(data[start:end], start)}
        probes = [(key, key.encode("ascii")) for key in MENUS]
        for enc in ENCODINGS:
            probes.extend((f"{enc}:{label}", label.encode(enc)) for labels in MENUS.values() for label in labels)
        for path in args.firmware:
            data = path.read_bytes()
            firmware[path.as_posix()] = {"sha256": sha256(data).hexdigest(), "exact_hits": hits(data, probes)}
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"executable": executable, "firmware": firmware}, indent=2))


if __name__ == "__main__":
    main()
