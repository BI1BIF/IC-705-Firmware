"""State machine for the PC-only satellite panel. All VFO state lives in memory."""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class VfoState:
    a_hz: int
    b_hz: int
    a_mode: str = "USB"
    b_mode: str = "FM"
    selected: str = "A"
    split: bool = False

    def tuned(self, **frequencies):
        return replace(self, **{f"{vfo.lower()}_hz": hz for vfo, hz in frequencies.items()})


class VirtualVfo:
    def __init__(self, initial):
        self.state = initial
        self.writes = []
        self.ptt_requested = False
        self.tx_status = False

    def read(self):
        return self.state

    def tx_readback(self):
        return self.tx_status

    def set_status_input(self, tx):
        self.tx_status = tx

    def write(self, requested, action, failure=None):
        if failure == "reject":
            self.writes.append((action, "rejected"))
            return "rejected"
        # Simulate a successful acknowledgement with an incorrect B frequency.
        self.state = replace(requested, b_hz=requested.b_hz + 10) if failure == "mismatch" else requested
        self.writes.append((action, "mismatch" if failure == "mismatch" else "accepted"))
        return "accepted"


class SatellitePanel:
    def __init__(self, vfo):
        self.vfo = vfo
        self.report = None
        self.index, self.role = 0, "A"
        self.status, self.snapshot, self.expected = "preview", None, None
        self.override, self.failure = None, None

    @property
    def ptt(self):
        return self.vfo.ptt_requested

    @property
    def tuning_blocked(self):
        return self.ptt or self.vfo.tx_readback() is not False

    def select(self, report):
        if self.snapshot is not None or self.tuning_blocked:
            return
        self.report = report
        self.index, self.role = 0, "A"
        self.status, self.override, self.failure = "preview", None, None

    def choose_role(self, role):
        if self.snapshot is None and not self.tuning_blocked and role in ("A", "B"):
            self.role = role

    @property
    def sample(self):
        return self.report["samples"][self.index]

    @property
    def gps(self):
        return self.report["controls"][self.override]["original_gps"] if self.override else self.sample["original_gps"]

    @property
    def blocked(self):
        if not self.gps["position_valid"]:
            return "position_expired"
        if not self.gps["utc_valid"]:
            return "utc_expired"
        if self.role not in self.sample["targets"]:
            return "below_horizon"
        return None

    @property
    def target(self):
        return None if self.blocked else self.sample["targets"][self.role]

    @property
    def active(self):
        return self.status in ("waiting", "tracking", "below_horizon", "position_expired", "utc_expired", "ptt_hold")

    def enable(self):
        if (self.report is None or self.snapshot is not None or self.tuning_blocked or
                self.index + 1 == len(self.report["samples"]) or self.blocked not in (None, "below_horizon")):
            return
        state = self.vfo.read()
        if state is None:
            self.status = "unexpected_readback"
            return
        self.snapshot = self.expected = state
        self.status = "waiting"
        self.update()

    def step(self, index):
        if (self.snapshot is None or index >= self.index) and 0 <= index < len(self.report["samples"]):
            self.index = index
            if self.status == "restored":
                self.status = "preview"
            self.update()

    def set_gps(self, override):
        self.override = override
        self.update()

    def set_ptt(self, held):
        self.vfo.ptt_requested = held
        self.after_ptt_change()

    def set_tx_status(self, tx):
        self.vfo.set_status_input(tx)
        self.after_ptt_change()

    def after_ptt_change(self):
        if self.status == "exit_pending" and not self.tuning_blocked:
            self.restore()
        else:
            self.update()

    def take_over(self):
        if self.active:
            self.status = "manual"

    def manual_tune(self):
        if self.status == "manual" and not self.tuning_blocked:
            state = self.vfo.read()
            if state is None:
                self.status = "unexpected_readback"
                return
            hz = getattr(state, f"{state.selected.lower()}_hz")
            self.vfo.write(state.tuned(**{state.selected: hz + 1000}), "manual")

    def apply(self, requested, action):
        failure, self.failure = self.failure, None
        result = self.vfo.write(requested, action, failure)
        if result == "held":
            # A VFO write can stop between two independently verified commits.
            if self.vfo.held_state is not None and self.vfo.read() == self.vfo.held_state:
                self.expected = self.vfo.held_state
                self.status = "exit_pending" if action == "restore" else "ptt_hold"
            else:
                self.status = f"{action}_mismatch"
        elif result == "rejected":
            self.status = f"{action}_rejected"
        elif result == "mismatch" or self.vfo.read() != requested:
            self.status = f"{action}_mismatch"
        else:
            self.expected = requested
            return True
        return False

    def update(self):
        if not self.active:
            return
        if self.tuning_blocked:
            self.status = "ptt_hold"
            return
        if self.vfo.read() != self.expected:
            self.status = "unexpected_readback"
            return
        if self.blocked:
            self.status = self.blocked
            return
        other = "B" if self.role == "A" else "A"
        target = self.target
        requested = VfoState(0, 0, "FM", "FM", self.role, True).tuned(
            **{self.role: target["rx_target_hz"], other: target["tx_target_hz"]})
        if requested == self.expected or self.apply(requested, "tune"):
            self.status = "tracking"

    def restore(self):
        if self.snapshot is None:
            return
        if self.tuning_blocked:
            self.status = "exit_pending"
            return
        if self.vfo.read() == self.snapshot or self.apply(self.snapshot, "restore"):
            self.status = "restored"
            self.snapshot = self.expected = None
            self.failure = None
