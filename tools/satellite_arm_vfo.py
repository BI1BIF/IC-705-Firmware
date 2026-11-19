"""Use the original J140 VFO handlers as the offline satellite panel's backend."""

from dataclasses import replace
from hashlib import sha256

from tools.decode_705_main import J140_DAT_SHA, J140_MAIN_SHA, decode_main
from tools.emulate_705 import call, uc
from tools.replay_705_ptt_tune import FLAGS, byte, radio, tune
from tools.replay_705_vfo_split import SELECT_VFO, SET_SPLIT, VFO, frequency, read_in_guest, require
from tools.satellite_panel_state import VfoState


class ArmVfo:
    def __init__(self, dat, initial):
        data = dat.read_bytes()
        require(sha256(data).hexdigest() == J140_DAT_SHA, "回放需要原厂日版 1.40 的 705J140.dat")
        _, main, manifest = decode_main(data)
        require(manifest["main"]["sha256"] == J140_MAIN_SHA, "日版 1.40 主程序校验不匹配")
        self.cpu = radio(bytes(main), "AB".index(initial.selected),
                         pair=(initial.a_hz, initial.b_hz), split=initial.split)
        # shortcut: Mode labels remain a desktop fixture until original mode setters are verified.
        self.modes = initial.a_mode, initial.b_mode
        self.ptt_requested = False
        self.writes, self.legs = [], []
        self.held_state = None
        require(self.read() == initial, "unexpected initial J140 VFO state")

    def query(self, command):
        return read_in_guest(self.cpu, command)[0]

    def tx_readback(self):
        try:
            return {b"\0": False, b"\1": True}.get(self.query("1c 00"))
        except (ValueError, uc.UcError):
            return None

    def set_status_input(self, tx):
        # Drive the observed software input in guest RAM; no original PTT request is sent.
        flags = byte(self.cpu, FLAGS) & 0x7f
        self.cpu.mem_write(FLAGS, bytes([flags | (0x80 if tx else 0)]))

    def read(self):
        try:
            return self._read()
        except (ValueError, uc.UcError):
            return None

    def _read(self):
        selected = (byte(self.cpu, VFO + 74) >> 2) & 1
        current, other = (frequency(self.query(command)) for command in ("25 00", "25 01"))
        split = self.query("0f")
        require(split in (b"\0", b"\1") and frequency(self.query("03")) == current and
                frequency(self.query("1c 03")) == (other if split == b"\1" else current),
                "inconsistent J140 VFO readback")
        a, b = (other, current) if selected else (current, other)
        return VfoState(a, b, *self.modes, "AB"[selected], split == b"\1")

    def blocked(self):
        return self.ptt_requested or self.tx_readback() is not False

    def write(self, requested, action, failure=None):
        self.held_state = None
        try:
            result = self._write(requested, action, failure)
        except (ValueError, uc.UcError):
            result = "mismatch"
        self.writes.append((action, result))
        return result

    def set_frequency(self, relative, hz, action):
        result = tune(self.cpu, relative, hz)
        self.legs.append({"action": action, **result})
        return result

    def _write(self, requested, action, failure):
        state = self.read()
        if state is None:
            return "mismatch"

        def pause():
            self.held_state = state
            return "held"

        if self.blocked():
            return pause()
        if failure == "reject":
            reply = self.set_frequency(0, 300_000_000, action)
            return "rejected" if reply["reply"] == "FA" and not reply["record_commit"] and self.read() == state else "mismatch"
        if state.selected != requested.selected:
            if self.blocked():
                return pause()
            call(self.cpu, SELECT_VFO["AB".index(requested.selected)])
            state = replace(state, selected=requested.selected)
            if self.read() != state:
                return "mismatch"
        if state.split != requested.split:
            if self.blocked():
                return pause()
            call(self.cpu, SET_SPLIT, 0, int(requested.split))
            state = replace(state, split=requested.split)
            if self.read() != state:
                return "mismatch"

        for relative, vfo in enumerate((state.selected, "A" if state.selected == "B" else "B")):
            if self.blocked():
                return pause()
            field = f"{vfo.lower()}_hz"
            hz = getattr(requested, field)
            if hz == getattr(state, field) and failure not in ("reject_second", "hold_between", "mismatch"):
                continue
            # 300 MHz is outside this guest's original receive tuning ranges.
            submitted = 300_000_000 if relative == 1 and failure == "reject_second" else hz
            if failure == "mismatch":
                submitted += 10
            result = self.set_frequency(relative, submitted, action)
            if result["reply"] == "FA":
                return "rejected" if not result["record_commit"] and self.read() == state else "mismatch"
            state = replace(state, **{field: hz})
            if not result["record_commit"] or self.read() != state:
                return "mismatch"
            if relative == 0 and failure == "hold_between":
                self.ptt_requested = True
                self.set_status_input(True)

        self.modes = requested.a_mode, requested.b_mode
        return "accepted"
