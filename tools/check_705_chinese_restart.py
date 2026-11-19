"""Verify the offline Chinese panel survives a full Windows preview restart."""

import argparse
from pathlib import Path
import subprocess
import sys

from PIL import Image

from tools.render_705_display import load
from tools.render_705_stock_row import require
from tools.replay_705_language_storage import DISPLAY, SYSTEM, LogicalStorage
from tools.virtual_705_display_catalog import prepare
from tools.virtual_705_panel import make_window


def run_window(stage, dat, font, output):
    store_path = output / "pc-display-settings.bin"
    settings = prepare(font, output / "build", third_language=True)
    root, lcd = make_window(load(dat.read_bytes()), storage=LogicalStorage.read_file(store_path),
                            storage_path=store_path, **settings)
    root.update()
    buttons = {widget.cget("text"): widget for widget in root.winfo_children()[1].winfo_children()
               if widget.winfo_class() == "Button"}
    menu = "MENU" if stage == "select" else "菜单"
    require(menu in buttons, "preview opened in the wrong language")

    def capture(name):
        target = output / f"{name}.png"
        lcd.image.write(str(target), format="png")
        return target

    def click(x, y):
        lcd.event_generate("<Button-1>", x=x, y=y)
        root.update()

    capture("01-home" if stage == "select" else "04-home-after-restart")
    buttons[menu].invoke()
    click(429, 182)
    if stage == "select":
        click(449, 163)
    click(120, 230)
    if stage == "select":
        for _ in range(5):
            click(449, 163)
        click(120, 54)
        capture("02-three-choices")
        click(120, 180)
        capture("03-chinese-selected")
        require(not store_path.exists(), "selection was saved without pressing Save")
        buttons["保存"].invoke()
    else:
        click(120, 54)
        with Image.open(capture("05-chinese-still-selected")) as image:
            require(image.convert("RGB").getpixel((380, 181)) == (93, 160, 201),
                    "the Chinese choice is not highlighted after restart")
    require(store_path.read_bytes()[DISPLAY:SYSTEM+1] == b"\x02\x01", "display or system language differs")
    root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("font", type=Path)
    parser.add_argument("output", type=Path, help="fresh output directory for this test")
    parser.add_argument("--stage", choices=("select", "restart"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.stage:
        run_window(args.stage, args.dat, args.font, args.output)
        return
    args.output.mkdir(parents=True, exist_ok=True)
    require(not (args.output / "pc-display-settings.bin").exists(), "use a fresh test output directory")
    for stage in ("select", "restart"):
        subprocess.run([sys.executable, "-m", "tools.check_705_chinese_restart", str(args.dat), str(args.font),
                        str(args.output), "--stage", stage], check=True)
    print(f"Chinese display persisted after the preview closed and restarted: {args.output}")


if __name__ == "__main__":
    main()
