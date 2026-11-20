"""Build the self-contained offline FT8/FT4 panel with Emscripten (Linux/WSL)."""
import base64
import html
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / ".analysis"
CODE = ROOT / "samples/ftx"
OUT = LAB / "ftx-station"
LIB = LAB / "ftx-lib"
FLAGS = LAB / "ftx-flags"
CTY = Path("/usr/share/wsjtx/cty.dat")


def checkout(path, repo, revision):
    if not path.exists():
        subprocess.run(["git", "clone", "--quiet", repo, path], check=True)
        subprocess.run(["git", "-C", path, "checkout", "--quiet", revision], check=True)
    head = subprocess.check_output(["git", "-C", path, "rev-parse", "HEAD"], text=True).strip()
    if head != revision:
        raise ValueError(f"Unexpected revision of {path}: {head}")


def country_data():
    exact, prefixes, entities = {}, {}, []
    for raw in CTY.read_text().splitlines():
        if not raw.strip():
            continue
        if not raw[0].isspace():
            parts = raw.split(":")
            name, primary = parts[0].strip(), parts[7].strip()
            entity = len(entities)
            entities.append([name, primary.lstrip("*")])
            continue
        for token in raw.strip().rstrip(",;").split(","):
            key = re.split(r"[\[(<{~]", token.strip())[0]
            if not key or primary.startswith("*"):
                continue
            if key.startswith("="):
                exact[key[1:]] = entity
            else:
                prefixes[key] = entity
    # A missing flag still has the full CTY entity name in station details.
    region = dict(JA="jp", DL="de", F="fr", I="it", BY="cn", K="us", VE="ca",
                  VK="au", G="gb-eng", GM="gb-sct", GW="gb-wls", EA="es",
                  PA="nl", SP="pl", **{"HB": "ch", "OE": "at", "OK": "cz"})
    flags = {}
    for primary, iso in region.items():
        data = (FLAGS / f"flags/4x3/{iso}.svg").read_bytes()
        flags[primary] = "data:image/svg+xml;base64," + base64.b64encode(data).decode()
    return dict(exact=exact, prefixes=prefixes, entities=entities, flags=flags)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checkout(LIB, "https://github.com/kgoba/ft8_lib.git", "9fec6ca39886edbf96f4f5e71edc76da5074e871")
    checkout(FLAGS, "https://github.com/lipis/flag-icons.git", "fe15c16e7463d0c66d6c5730e9d0e832438d98e1")
    names = "rx_begin rx_push rx_end row_text row_hz row_score row_snr row_sender tx_slot malloc free".split()
    sources = [CODE / "station.c", LIB / "common/monitor.c", *sorted((LIB / "ft8").glob("*.c")),
               *sorted((LIB / "fft").glob("*.c"))]
    subprocess.run(["emcc", "-O2", "-I", LIB, *sources, "-DHAVE_STPCPY", "-DLOG_PRINTF(...)=((void)0)",
                    "-sSINGLE_FILE", "-sENVIRONMENT=web", "-sSTACK_SIZE=131072",
                    "-sEXPORTED_FUNCTIONS=" + json.dumps(["_" + name for name in names]),
                    '-sEXPORTED_RUNTIME_METHODS=["ccall","UTF8ToString"]',
                    "-o", OUT / "audio.js"], check=True)
    notices = [(LIB / "LICENSE").read_text(), (FLAGS / "LICENSE").read_text(),
               "Button glyphs: IC705PanelSC, subset of Noto Sans SC.\n" +
               (LAB / "zh-cn-preview/noto/OFL.txt").read_text(),
               Path("/usr/share/wsjtx/cty.dat_copyright.txt").read_text(),
               "KISS FFT — Copyright (c) 2003–2010 Mark Borgerding. BSD-3-Clause.\n"
               + Path("/usr/share/common-licenses/BSD").read_text().split("\n\n", 1)[1]]
    page = (CODE / "panel.html").read_text()
    page = page.replace("{{BUTTON_FONT}}",base64.b64encode((OUT / "button-sc.ttf").read_bytes()).decode())
    for key, path in (("FT8_HEADER", OUT / "ft8-header.png"), ("FT4_HEADER", OUT / "ft4-header.png"),
                      ("FT8_HOME", OUT / "ft8-home.png"), ("FT4_HOME", OUT / "ft4-home.png"),
                      ("WORLD_LAND", CODE / "world-land.png")):
        page = page.replace("{{"+key+"}}", "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode())
    page = page.replace("/* OPERATING */", (CODE / "operating.js").read_text())
    page = page.replace("/* COUNTRIES */", "const countries = " + json.dumps(country_data()) + ";")
    page = page.replace("/* AUDIO */", (OUT / "audio.js").read_text())
    page = page.replace("/* STATION */", (CODE / "panel.js").read_text())
    (OUT / "IC-705-FT8-FT4.html").write_text(page.replace("<!-- NOTICES -->", html.escape("\n\n".join(notices))))


if __name__ == "__main__":
    main()
