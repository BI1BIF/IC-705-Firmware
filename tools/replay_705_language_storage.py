"""Replay J140 language persistence with a simulated logical settings store; never access a radio."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import unpack
from tempfile import NamedTemporaryFile

from tools.emulate_705 import PROFILES, arm, call, uc
from tools.render_705_display import DAT_HASH, PAGE, load
from tools.render_705_stock_row import require
from tools.replay_705_settings import OPEN_MENU, SettingsGuest


RELOAD, FLUSH = 0x2004E73C, 0x2004E938
READ, WRITE = 0x2005E4C8, 0x2005E554
DISPLAY, SYSTEM = 0x396BB, 0x396BC  # logical storage offsets
DESCRIPTORS, DISPLAY_DESC = 0x202DE844, 0x202F0DFC
DISPLAY_TEXT_SELECTOR = 0x20179F8C
REDRAW = 0x203806F7
ROWS = ((120, 54), (120, 119), (120, 180))
JA = ["ディスプレイ設定", "6/6", "表示言語", "日本語", "システム言語", "日本語"]
EN = ["DISPLAY", "6/6", "Display Language", "English", "System Language", "Japanese"]


class LogicalStorage:
    def __init__(self, data=None):
        self.data = bytearray(0x40000) if data is None else bytearray(data)
        require(len(self.data) == 0x40000, "unexpected logical store size")
        if data is None:
            self.data[DISPLAY:SYSTEM+1] = b"\x01\x01"
        self.requests = []

    @classmethod
    def read_file(cls, path):
        try:
            return cls(path.read_bytes())
        except FileNotFoundError:
            return cls()

    def write_file(self, path):
        with NamedTemporaryFile(dir=path.parent, delete=False) as pending:
            temp = Path(pending.name)
            try:
                pending.write(self.data)
                pending.close()
                temp.replace(path)
            finally:
                temp.unlink(missing_ok=True)

    def attach(self, cpu):
        def io(_cpu, address, _size, _data):
            offset, pointer, count, lr = map(cpu.reg_read, (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1,
                                                           arm.UC_ARM_REG_R2, arm.UC_ARM_REG_LR))
            require(0 < count <= 32 and offset + count <= len(self.data), "unexpected settings I/O span")
            region = slice(offset, offset + count)
            if address == WRITE:
                self.data[region] = cpu.mem_read(pointer, count)
            else:
                cpu.mem_write(pointer, bytes(self.data[region]))
            self.requests.append({"op": "write" if address == WRITE else "read", "offset": offset,
                                  "ram": hex(pointer), "size": count, "return_pc": hex(lr)})
            cpu.reg_write(arm.UC_ARM_REG_R0, 0)
            cpu.reg_write(arm.UC_ARM_REG_PC, lr)

        for entry in (READ, WRITE):
            cpu.hook_add(uc.UC_HOOK_CODE, io, begin=entry, end=entry)

    def restore(self, guest):
        # Poison both RAM bytes to prove the reader copies them from simulated storage.
        guest.cpu.mem_write(guest.language_address, b"\xFE\xFE")
        self.attach(guest.cpu)
        call(guest.cpu, RELOAD, instruction_limit=2_000_000)

    def flush(self, guest):
        call(guest.cpu, FLUSH, instruction_limit=2_000_000)


def replay(dat, output):
    images = load(dat)
    profile = PROFILES[images[3]]
    require(profile.name == "705J140", "this experiment is tied to original 705J140")
    output.mkdir(parents=True, exist_ok=True)
    evidence = {"dat_sha256": sha256(dat).hexdigest(), "main_sha256": images[3], "stages": {}}
    stages = evidence["stages"]

    def frame(guest, name=None, expected=None):
        labels, image = guest.render()
        if expected is not None:
            require(labels == expected, f"{name}: unexpected labels {labels}")
        if name is not None:
            (output / f"{name}.png").write_bytes(image)
            stages[name] = {"labels": labels, "preferences": guest.language(),
                            "ui_bits": guest.cpu.mem_read(PAGE+9, 1)[0] & 3,
                            "png_sha256": sha256(image).hexdigest()}
        return labels

    def page_six(guest):
        call(guest.cpu, OPEN_MENU, 22)

        def go_to(menu, first, max_clicks):
            for _ in range(max_clicks + 1):
                state = guest.state()
                require(state["menu"] == menu, f"unexpected navigation state: {state}")
                if state["first"] == first:
                    return
                frame(guest)
                guest.click(449, 69 if state["first"] > first else 163)
            raise ValueError(f"menu {menu}, first row {first} not reached")

        go_to(22, 4, 3)
        frame(guest)
        guest.click(120, 230)
        go_to(67, 20, 5)

    def reload(store, name, expected):
        guest = SettingsGuest(images)
        start = len(store.requests)
        store.restore(guest)
        requests = store.requests[start:]
        require(guest.language() == list(expected), f"{name}: settings did not reload: {guest.language()}")
        require(len(requests) == 714 and all(r["op"] == "read" for r in requests),
                f"{name}: unexpected settings read sequence")
        covering = [r for r in requests if r["offset"] <= DISPLAY and r["offset"]+r["size"] > SYSTEM]
        require(len(covering) == 1 and covering[0]["return_pc"] == "0x2004e78c", "missing stock settings read")
        evidence.setdefault("reloads", {})[name] = {"preferences": guest.language(), "request_count": len(requests),
                                                   "language_request": covering[0]}
        return guest

    def select(guest, store, index):
        guest.writes.clear()
        before = len(store.requests)
        hit = guest.click(*ROWS[index])
        writes = [w for w in guest.writes if int(w["address"], 16) in range(guest.language_address,
                                                                           guest.language_address+2)]
        require(hit == (0x3E, 0x3F)[index] and guest.language() == [index, 1], "language selection failed")
        require(writes == [{"pc": "0x200a29c0", "address": hex(guest.language_address), "size": 1, "value": index}],
                f"unexpected click preference writes {writes}")
        require(len(store.requests) == before and guest.cpu.mem_read(REDRAW, 1)[0] & 0x40,
                "click should request redraw without synchronous storage I/O")
        return writes[0]

    def save(guest, store, name, expected):
        before, start = bytes(store.data), len(store.requests)
        store.flush(guest)
        requests = store.requests[start:]
        changed = [i for i, (old, new) in enumerate(zip(before, store.data)) if old != new]
        require(DISPLAY in changed and SYSTEM not in changed and store.data[DISPLAY:SYSTEM+1] == bytes(expected),
                f"{name}: unexpected saved language bytes")
        covering = [r for r in requests if r["offset"] <= DISPLAY < r["offset"]+r["size"]]
        require(len(covering) == 1 and covering[0]["return_pc"] == "0x2004e8fc", "missing stock settings write")
        evidence.setdefault("saves", {})[name] = {"request_count": len(requests), "changed_offsets": changed,
                                                 "language_request": covering[0], "preferences": list(expected)}

    store = LogicalStorage()
    guest = reload(store, "fixture-japanese", (1, 1))
    cpu = guest.cpu
    evidence["settings_descriptor"] = [hex(i) for i in unpack("<4I", cpu.mem_read(DESCRIPTORS+32, 16))]
    require(evidence["settings_descriptor"] == ["0x203eaa49", "0x20396efb", "0x392c0", "0x1099"],
            "unexpected settings descriptor")
    descriptor_limits = [list(unpack("<2I", cpu.mem_read(addr+12, 8)))
                         for addr in (DISPLAY_DESC, DISPLAY_DESC+0x3C)]
    require(descriptor_limits == [[0, 1], [0, 1]], "unexpected picker limits")
    evidence["picker_limits_display_and_system"] = descriptor_limits

    page_six(guest)
    frame(guest, "01-japanese", JA)
    guest.click(*ROWS[0])
    picker = ["表示言語", "1/1", "英語", "日本語"]
    frame(guest, "02-stock-picker", picker)
    before = guest.state(), guest.language(), len(store.requests)
    guest.writes.clear()
    hit = guest.click(*ROWS[2])
    require(hit == 0x40 and before == (guest.state(), guest.language(), len(store.requests))
            and not any(int(w["address"], 16) in range(guest.language_address, guest.language_address+2)
                        for w in guest.writes), "stock picker accepted its empty third slot")
    evidence["stock_third_row_hit"] = hit
    frame(guest, expected=picker)
    evidence["select_english"] = select(guest, store, 0)
    frame(guest, "03-english-selected", EN)
    require(not cpu.mem_read(REDRAW, 1)[0] & 0x40, "redraw flag did not clear")
    reload(store, "before-flush-still-japanese", (1, 1))
    save(guest, store, "english", (0, 1))

    # Fresh CPU, fresh controller object, only the saved logical bytes cross the boundary.
    store = LogicalStorage(bytes(store.data))
    guest = reload(store, "english-after-flush", (0, 1))
    page_six(guest)
    frame(guest, "04-english-reloaded", EN)
    require(stages["03-english-selected"]["png_sha256"] == stages["04-english-reloaded"]["png_sha256"],
            "English display changed after reload")
    guest.click(*ROWS[0])
    frame(guest, expected=["Display Language", "1/1", "English", "Japanese"])
    evidence["select_japanese"] = select(guest, store, 1)
    save(guest, store, "japanese", (1, 1))

    guest = reload(LogicalStorage(bytes(store.data)), "japanese-after-flush", (1, 1))
    page_six(guest)
    frame(guest, "05-japanese-reloaded", JA)

    # Negative probe: seed the unsupported value in RAM only, then use the unmodified save/read code.
    trial = LogicalStorage(bytes(store.data))
    guest = reload(trial, "candidate-start", (1, 1))
    guest.cpu.mem_write(guest.language_address, b"\x02")
    save(guest, trial, "candidate-2", (2, 1))
    guest = reload(LogicalStorage(bytes(trial.data)), "candidate-2-after-flush", (2, 1))
    effective = call(guest.cpu, profile.language)
    require(effective == 2, "raw candidate rejected by getter")
    page_six(guest)
    frame(guest, "06-candidate-reloaded", [*EN[:3], "英語", *EN[4:]])
    packed = stages["06-candidate-reloaded"]["ui_bits"]
    require(packed == stages["04-english-reloaded"]["ui_bits"] == 1, "third value did not alias English UI bit")
    # The stock draw entry passes R2=0, so widening the display bit alone cannot select new resources.
    text_indices = [call(guest.cpu, DISPLAY_TEXT_SELECTOR, value, 1, 0) for value in (0, 1, 2)]
    require(text_indices == [0, 1, 1], "unexpected original display text indices")
    evidence["candidate"] = {"raw_getter": effective, "packed_ui_bits": packed,
                             "stock_text_indices_with_unpacked_0_1_2": text_indices}

    # Independent synthetic fixture: exercise the stock English-system gate without changing the baseline.
    english_system = LogicalStorage(bytes(trial.data))
    english_system.data[SYSTEM] = 0
    guest = reload(english_system, "english-system-control", (2, 0))
    require(call(guest.cpu, profile.language) == 0, "English system did not force English display")
    page_six(guest)
    frame(guest, "07-english-system-control", ["DISPLAY", "6/6", "System Language", "English"])
    require(stages["07-english-system-control"]["ui_bits"] == 0, "unexpected English system bits")

    (output / "language-storage.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path, help=f"original 705J140.dat (SHA-256 {DAT_HASH})")
    parser.add_argument("--out", type=Path, required=True, help="directory for PNG frames and JSON evidence")
    args = parser.parse_args()
    replay(args.dat.read_bytes(), args.out)
    print(f"J140 language storage replay passed: {args.out / 'language-storage.json'}")


if __name__ == "__main__":
    main()
