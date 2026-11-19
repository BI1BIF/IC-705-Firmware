"""Decode a local CW audio fixture and render its text through the stock J140 RTTY page."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from struct import pack
from tempfile import TemporaryDirectory
from textwrap import wrap
import wave

from tools.emulate_705 import call, uc
from tools.make_cw_fixtures import RATE, render
from tools.probe_705_resource_paths import LAYOUTS
from tools.probe_705_rx_audio import LAYOUTS as AUDIO_LAYOUTS, replay_wav
from tools.render_705_display import GRAPHICS_FLASH, load
from tools.render_705_stock_row import make_surface, png, require
from tools.score_arrl_cw import body, edit_distance

REFERENCE = "CQ CQ DE TEST 705 THIS IS A CW DISPLAY TEST MESSAGE RECEIVED ON THE ORIGINAL SCREEN 73"
LAYOUT = LAYOUTS["705J140"]
PAGE, DIRTY, STYLE, RX_RGB = 0x201750CC, 0x20380C98, 0x204BAB61, 0x204BD63F
CONSUMER_INDEX, APPEND = 0x20380120, 0x2003E108
DECODER_ROOT = ".analysis/cw-baseline/debian/root"


def decode(wav, raw, pad):
    options = ["-af", "apad=pad_dur=1.5"] if pad else []
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(wav), *options,
                    "-ar", "22050", "-ac", "1", "-c:a", "pcm_s16le", "-f", "s16le", str(raw)], check=True)
    lib = f"{DECODER_ROOT}/usr/lib/x86_64-linux-gnu"
    return subprocess.run(["wsl.exe", "-d", "Debian", "--exec", "env",
                           f"LD_LIBRARY_PATH={lib}:{lib}/pulseaudio", f"{DECODER_ROOT}/usr/bin/multimon-ng",
                           "-q", "-v", "1", "-c", "-a", "MORSE_CW", "-t", "raw", raw.as_posix()],
                          check=True, capture_output=True, text=True, encoding="utf-8").stdout


def replay_display(main, font, graphics, small, text, output):
    cpu, surface = make_surface(main, font, small)
    cpu.mem_map(GRAPHICS_FLASH, len(graphics), uc.UC_PROT_READ)
    cpu.mem_write(GRAPHICS_FLASH, graphics)
    call(cpu, LAYOUT["rtty_init"])
    cpu.mem_write(LAYOUT["rtty_width"], pack("<H", 359))
    call(cpu, LAYOUT["rtty_view"], LAYOUT["ring"])
    cpu.mem_write(LAYOUT["ring"] - 0x18, b"\x01")
    cpu.mem_write(STYLE, b"\x01")
    index = 0
    saved = []
    appended = bytearray()

    def log_append(_cpu, _addr, _size, _data):
        if surface.reg("R0") == LAYOUT["ring"]:
            appended.extend(cpu.mem_read(surface.reg("R1"), surface.reg("R2")))

    def check_graphics(_cpu, addr, _size, _data):
        require(addr in surface.handlers, f"unmodeled OpenVG entry at {addr:#x}")

    cpu.hook_add(uc.UC_HOOK_CODE, log_append, begin=APPEND, end=APPEND)
    cpu.hook_add(uc.UC_HOOK_CODE, check_graphics, begin=0x20263100, end=0x20263DFF)
    queue = LAYOUT["rtty_queue"]
    lines = wrap(text, width=38)
    require(1 <= len(lines) <= 4, "demo must fit the four visible rows")

    for i in range(len(lines) + 1):
        if i:
            payload = (("\r" if i > 1 else "") + lines[i-1]).encode("ascii")
            for start in range(0, len(payload), 15):
                for char in payload[start:start+15]:
                    cpu.mem_write(queue + 0x30E + index, bytes((char,)))
                    index = (index + 1) % 16
                cpu.mem_write(queue + 0x31E, bytes((index,)))
                call(cpu, LAYOUT["rtty_consume"], 0)
                require(cpu.mem_read(CONSUMER_INDEX, 1)[0] == index, "stock queue did not drain")
        call(cpu, LAYOUT["rtty_copy"], 0)
        cpu.mem_write(RX_RGB, bytes((128, 255, 128)))  # UI palette fixture; body is still entirely guest-generated.
        rows = [bytes(cpu.mem_read(LAYOUT["snapshot"] + 83*j, 83)).rstrip(b" \r\n\0").decode("ascii")
                for j in range(4)]
        require([row for row in rows if row] == lines[:i], f"stock text snapshot mismatch: {rows!r}")
        surface.events.clear()
        cpu.mem_write(DIRTY, b"\x03" if i == 0 else b"\x00")
        call(cpu, PAGE, instruction_limit=8_000_000, timeout_us=10_000_000)
        glyph_text = ["".join(chr(g["key"]) for g in e["glyphs"]).rstrip() for e in surface.events]
        if i:
            require(lines[i-1] in glyph_text, f"new line did not render: {glyph_text!r}")
        else:
            require("RTTY DECODE" in glyph_text, "missing original decoder title")
        # Count new receive-color pixels in the actual software LCD buffer.
        ink = sum(g > r + 24 and r == b and a == 255
                  for r, g, b, a in zip(*(surface.pixels[k::4] for k in range(4))))
        previous_ink = saved[-1]["receive_pixels"] if i else 0
        require(ink > previous_ink if i else ink == 0,
                f"unexpected frame {i} ink count: {ink} after {previous_ink}; "
                f"paints: {[e['rgba'] for e in surface.events]}")
        frame = png(surface.width, surface.height, surface.pixels)
        name = f"rtty-frame-{i}.png"
        (output / name).write_bytes(frame)
        saved.append(dict(frame=name, snapshot=rows, new_glyph_text=glyph_text, receive_pixels=ink,
                          frame_sha256=sha256(frame).hexdigest(), queue_index=index))
    expected = "\n".join(lines).encode("ascii")
    require(bytes(appended) == expected, f"stock append bytes mismatch: {bytes(appended)!r}")
    return saved


def stage_demo(main, scratch):
    source, staged = scratch / "demo.wav", scratch / "stock-audio.wav"
    with wave.open(str(source), "wb") as wav:
        wav.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        wav.writeframes(render(REFERENCE, 20, 600, None))
    audio = replay_wav(main, AUDIO_LAYOUTS["705J140"], source, staged)
    return source, staged, audio


def decode_demo(main, output):
    require(not output.is_absolute(), "provide a project-relative output path for the WSL decoder")
    output.mkdir(parents=True)
    with TemporaryDirectory(dir=output) as directory:
        scratch = output / Path(directory).name
        source, staged, audio = stage_demo(main, scratch)
        pcm = scratch / "demo.raw"
        log = decode(staged, pcm, pad=True)
        for artifact in (source, staged, pcm):
            artifact.replace(output / artifact.name)
        audio.update(source=str(output / source.name), output=str(output / staged.name))
    decoded = " ".join(log.split("MAX:", 1)[0].split())
    (output / "decoded.txt").write_text(log, encoding="utf-8")
    (output / "text-comparison.txt").write_text(f"Reference: {REFERENCE}\nDecoded:   {decoded}\n", encoding="utf-8")
    require(decoded == REFERENCE, f"synthetic decode differs from reference: {decoded!r}")
    return decoded, audio


def run(dat, output, arrl_wav=None, arrl_reference=None):
    main, font, graphics, main_hash, small = load(dat.read_bytes())
    decoded, audio = decode_demo(main, output)
    result = dict(main_sha256=main_hash, reference=REFERENCE, decoded=decoded, errors=0,
                  reference_chars_with_spaces=len(REFERENCE),
                  audio=audio, frames=replay_display(main, font, graphics, small, decoded, output))
    if arrl_wav is not None:
        arrl_log = decode(arrl_wav, output / "arrl.raw", pad=False)
        actual, expected = body(arrl_log), body(arrl_reference.read_text(encoding="utf-8-sig"))
        require(actual and expected, "ARRL reference or decoder passage boundaries not found")
        timing = int(arrl_log.rsplit("TIMING_DIT:", 1)[1].split()[0])
        result["arrl_existing_stock_audio"] = dict(chars=len(expected), errors=edit_distance(expected, actual),
                                                   declared_wpm=20, decoder_final_wpm=1200/timing)
    (output / "evidence.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("output", type=Path, help="new project-relative output directory")
    parser.add_argument("--arrl-wav", type=Path, help="existing J140 recording-path WAV (project-relative)")
    parser.add_argument("--arrl-reference", type=Path)
    args = parser.parse_args()
    if (args.arrl_wav is None) != (args.arrl_reference is None):
        parser.error("supply both ARRL inputs or omit both")
    run(args.dat, args.output, args.arrl_wav, args.arrl_reference)


if __name__ == "__main__":
    main()
