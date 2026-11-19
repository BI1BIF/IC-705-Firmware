"""Inputs for the offline J140 cold-start panel replay."""

from hashlib import sha256
from struct import pack


def channel_index_fixture():
    """Reproduce the first settings area observed in the stock synthetic startup."""
    data = bytearray(b"\xff" * 0x2190)
    data[:99 * 19:19] = bytes(range(1, 100))
    data[0x76C:0xB52] = pack("<499H", *range(1, 500))
    data[0x1068:0x106D] = bytes.fromhex("000000f301")
    data[0x198F:0x1993] = bytes.fromhex("0a00ff00")
    if sha256(data).hexdigest() != "da46eaad2e52ae166f39fcd68ff45b03880085ccd1d245ffbbea1067280fdbcd":
        raise ValueError("J140 synthetic settings fixture differs from the captured stock buffer")
    return {((offset & 0x40) << 11) | ((offset >> 7) << 6) | (offset & 0x3F): value
            for offset, value in enumerate(data, 0x355C0)}
