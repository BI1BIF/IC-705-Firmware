"""Build the J140 offline flag atlas and exact-call / longest-prefix indexes."""

import json
import re
from hashlib import sha256
from io import BytesIO
from struct import pack

from PIL import Image
from resvg_py import svg_to_bytes

from tools.build_705_ftx_preview import FLAGS, LAB, checkout


def atlas():
    cn = LAB / "ftx-cn-ref"
    checkout(
        cn,
        "https://github.com/N0BOY/FT8CN.git",
        "a98fbfaec379a0c7a07d2a50c27be223aef948d8",
    )
    checkout(
        FLAGS,
        "https://github.com/lipis/flag-icons.git",
        "fe15c16e7463d0c66d6c5730e9d0e832438d98e1",
    )
    assets = cn / "ft8cn/app/src/main/assets"
    dxcc = json.loads((assets / "dxcc_list.json").read_text(encoding="utf8"))
    regions = {
        r["pp"]: r["flag"][:-4]
        for r in dxcc.values()
        if r.get("pp") and r.get("prefix")
    }
    regions.update(
        {
            "EU": "by",
            "KG4": "us",
            "G": "gb-eng",
            "GM": "gb-sct",
            "GW": "gb-wls",
            "GI": "gb",
            "3B6": "mu",
            "E5/n": "ck",
            "E5/s": "ck",
            "PJ4": "bq",
            "PJ5": "bq",
            "FK/c": "nc",
            "FO/m": "pf",
            "ZD8": "sh",
            "ZD9": "sh",
            "KH0": "mp",
            "KH8/s": "as",
        }
    )
    prefixes, exact, entities = {}, {}, {}
    for line in (assets / "cty.dat").read_text(encoding="utf8").splitlines():
        if not line.strip():
            continue
        if not line[0].isspace():
            primary = line.split(":")[7].strip()
            if not primary.startswith("*"):
                entities[primary] = regions[primary]
        elif not primary.startswith("*"):
            for raw in line.strip().rstrip(",;").split(","):
                token = re.split(r"[\[(<{~]", raw)[0]
                table = exact if token.startswith("=") else prefixes
                table[token.lstrip("=")] = regions[primary]

    # Only store overrides that change a shorter prefix's result.
    def match(call, table):
        while call:
            if call in table:
                return table[call]
            call = call[:-1]

    kept = {k: v for k, v in prefixes.items() if match(k[:-1], prefixes) != v}

    def portable(call):
        parts = call.split("/")
        if len(parts) == 1:
            return match(call, prefixes)
        if len(parts) != 2 or parts[1] in ("MM", "AM"):
            return None
        if parts[1] in ("P", "M", "QRP") or parts[1].isdigit():
            return match(parts[0], prefixes)
        a, b = parts
        return (
            match(a if len(a) < len(b) else b, prefixes) if len(a) != len(b) else None
        )

    overrides = {k: v for k, v in exact.items() if portable(k) != v}
    codes = sorted(set(entities.values()))
    ids = {code: i + 1 for i, code in enumerate(codes)}
    pixels = bytearray()
    for code in codes:
        svg = FLAGS / f"flags/4x3/{code}.svg"
        png = svg_to_bytes(
            svg_string=svg.read_text(encoding="utf8"), width=96, height=72
        )
        im = (
            Image.open(BytesIO(png))
            .convert("RGB")
            .resize((16, 12), Image.Resampling.LANCZOS)
            .quantize(colors=16, dither=Image.Dither.NONE)
        )
        palette = bytes(im.getpalette()[:48]).ljust(48, b"\0")
        for r, g, b in zip(palette[::3], palette[1::3], palette[2::3]):
            pixels.extend(pack("<H", (r >> 3) << 11 | (g >> 2) << 5 | (b >> 3)))
        indices = im.tobytes()
        pixels.extend(a | b << 4 for a, b in zip(indices[::2], indices[1::2]))
    # Offsets stay 32-bit so a data revision can grow beyond 64 KiB.
    pool, indices = bytearray(), bytearray()
    for table in (overrides, kept):
        for key in sorted(table):
            indices.extend(pack("<I", len(pool) | ids[table[key]] << 24))
            pool.extend(key.encode("ascii") + b"\0")
    start = 20 + len(indices)
    pix = (start + len(pool) + 1) & ~1
    body = (
        pack("<4I", len(overrides), len(kept), start, pix)
        + indices
        + pool
        + bytes(pix - start - len(pool))
        + pixels
    )
    return sha256(body).digest()[:4] + body, {
        "entities": len(entities),
        "flags": len(codes),
        "codes": codes,
        "prefixes": len(prefixes),
        "exceptions": len(exact),
        "stored_prefixes": len(kept),
        "stored_exceptions": len(overrides),
    }
