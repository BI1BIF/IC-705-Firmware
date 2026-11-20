"""Capture J140's USB-D mini-scope header for the offline FT8/FT4 UI."""
from io import BytesIO
from pathlib import Path

from PIL import Image
from tools.emulate_705 import call
from tools.probe_705_cw_menu import MODE_UI_A, MODE_VFO_A
from tools.replay_705_vfo_split import SELECT_VFO, seed_vfos
from tools.virtual_705_panel import load, start


def main():
    root = Path(__file__).resolve().parents[1]
    out = root / ".analysis/ftx-station"
    out.mkdir(parents=True, exist_ok=True)
    images = load((root / "firmware/705J140.dat").read_bytes())
    for mode, hz in (("ft8", 14074000), ("ft4", 14080000)):
        panel = start(images)
        seed_vfos(panel.cpu, (hz, hz))
        call(panel.cpu, SELECT_VFO[0])
        for address in (MODE_UI_A, MODE_VFO_A):
            panel.cpu.mem_write(address, b"\x10")  # USB, FIL1
        panel.render()
        panel._press_key(1, 0)  # M.SCOPE
        panel.render()
        panel.click(37, 32)
        panel.render()
        panel.click(329, 241)  # DATA on the system's MODE page
        labels, png = panel.render()
        assert "USB-D" in labels and "-2.5k" in labels
        (out / f"{mode}-home.png").write_bytes(png)
        Image.open(BytesIO(png)).crop((0, 0, 480, 86)).save(out / f"{mode}-header.png")


if __name__ == "__main__":
    main()
