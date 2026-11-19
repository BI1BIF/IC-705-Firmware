"""Replay J140's CW status reader, PCM path and Break-in transitions without a radio."""

import argparse
import json
from pathlib import Path
from struct import unpack
from tempfile import TemporaryDirectory

from tools.emulate_705 import call, uc
from tools.make_cw_fixtures import PAD_FRAMES, render
from tools.probe_705_cw_pcm import (BUILD_REQUEST, FILTERED, FILTER_REQUEST, KEY_ACTIVITY, REQUEST, TEST_CODE,
                                    feed_dsp_tx, probe, simulated_gpio)
from tools.probe_705_rx_audio import require
from tools.render_705_display import load
from tools.replay_705_ptt_tune import FLAGS, STATUS_STORE, STATUS_TASK, byte, radio, word
from tools.replay_705_vfo_split import exchange_in_guest
from tools.verify_705_cw_arm import build


MAILBOX, UNPACK_STATUS, KEY_STEP = 0x20498770, 0x2011DF40, 0x20115A00
BREAK_IN_INPUT = 0x203806F6
TICK, DELAY_COUNTER, DELAY_THRESHOLD = 0x20104A28, 0x20401F96, 0x20380246
OFF, SEMI, FULL = range(3)
SIDETONE_TEXT, REPLY_TEXT = "VVV", "ECQ TEST 123"


def audio(text, *, trim_leading=False):
    wav = bytes(render(text, 20, 600, None))
    if trim_leading:
        wav = wav[PAD_FRAMES*2:]
    return wav + bytes(-len(wav) % 12)


def trial(main, code, entry, mode, mode_command):
    cpu = radio(main, 0, pair=(7_030_000, 7_032_000), split=False)
    simulated_gpio(cpu, extra=((uc.UC_MEM_READ, 0xFCFE3220, 2, 0),))

    def exchange(data):
        return exchange_in_guest(cpu, data)[0][2:-1]

    for data in (bytes((6, mode_command, 1)), bytes((0x16, 0x47, mode)), b"\x14\x0c\x01\x28",
                 b"\x14\x0f\x00\x01"):
        require(exchange(data) == b"\xfb", "original CI-V rejected a fixture setting")
    require(exchange(b"\x04") == bytes((4, mode_command, 1))
            and exchange(b"\x16\x47") == bytes((0x16, 0x47, mode)), "original CI-V settings were not retained")
    call(cpu, 0x20060420)  # Original delay calculation; no fixture writes to the counter or threshold.
    call(cpu, 0x20060494)
    delay = unpack("<H", cpu.mem_read(DELAY_THRESHOLD, 2))[0]
    require(2 <= delay <= 420, f"unexpected stock timer threshold: {delay}")
    status_writes, publishes = [], {}
    cpu.hook_add(uc.UC_HOOK_CODE, lambda c, *_: status_writes.append(byte(c, FLAGS) >> 7),
                 begin=STATUS_STORE+4, end=STATUS_STORE+4)

    def key(down, *, feedback=False):
        def feed(c):
            # Feed only the simulated incoming packet and a separate lower-layer Break-in input.
            c.mem_write(MAILBOX, bytes((0x20 if down else 0,)))
            c.mem_write(MAILBOX+0x40, b"\x01")
            c.mem_write(BREAK_IN_INPUT, bytes((0x10 if down and mode else 0,)))
            call(c, UNPACK_STATUS)
            feed_dsp_tx(c, feedback)
            require(byte(c, KEY_ACTIVITY) == down, "original status parser did not report the expected key state")
        return feed

    def publish(c, label=None):
        for routine in (KEY_STEP, BUILD_REQUEST, FILTER_REQUEST, STATUS_TASK):
            call(c, routine)
        if label is not None:
            publishes[label] = dict(tx=byte(c, FLAGS) >> 7, request=word(c, REQUEST))

    def wait_semi(c):
        for _ in range(delay*2):
            if unpack("<H", c.mem_read(DELAY_COUNTER, 2))[0] == delay-1:
                break
            call(c, TICK)
            publish(c)
        count, = unpack("<H", c.mem_read(DELAY_COUNTER, 2))
        require(count == delay-1 and word(c, REQUEST) == 0x2000 and byte(c, FLAGS) >> 7 == 1,
                f"semi Break-in at tick {count}/{delay}: request={word(c, REQUEST):#x}, flags={byte(c, FLAGS):#x}")

    def after_pcm(c, label):
        if label in ("key already down", "key released", "last hold block"):
            if label == "last hold block":
                for _ in range(2):
                    if unpack("<H", c.mem_read(DELAY_COUNTER, 2))[0] < delay:
                        call(c, TICK)
            publish(c, label)

    incoming, sidetone = audio(REPLY_TEXT, trim_leading=True), audio(SIDETONE_TEXT, trim_leading=True)
    # Preheat with a partial receive dash; key status arrives before the first sidetone PCM block.
    phases = [("partial receive mark", audio("T", trim_leading=True)[:1452], key(False)),
              ("key already down", sidetone, key(True)),
              ("key released", bytes(12) if mode else incoming, key(False, feedback=bool(mode)))]
    if mode == SEMI:
        phases.append(("last hold block", bytes(12), wait_semi))
    if mode:
        def feedback_clears(c):
            key(False)(c)
            for _ in range(40):
                call(c, TICK)
                publish(c, "release settled")
                if not (byte(c, FLAGS) & 0x80 or word(c, FILTERED)):
                    break

        phases.extend([("feedback still reports transmit", bytes(12), None),
                       ("first received reply", incoming, feedback_clears)])
    result = probe(cpu, phases, code, entry, 0, 1, after_first_pcm=after_pcm)
    stages = {stage["stage"]: stage for stage in result["stages"]}
    pressed = stages["key already down"]
    require(stages["partial receive mark"]["mark_in_progress"] and pressed["discarded_partial_samples"] > 0
            and pressed["key_activity"] and not pressed["stock_tx"] and pressed["request"] == 0
            and pressed["fed_blocks"] == 0 and pressed["decoder_state_clear"], "early key gate did not block PCM")
    if mode:
        require(status_writes == [1, 0] and publishes["key already down"] == dict(tx=1, request=0x2000)
                and publishes["key released"]["request"] == (0x2000 if mode == SEMI else 0)
                and publishes["release settled"] == dict(tx=0, request=0),
                f"original Break-in transition differs: mode {mode}/{mode_command}, {status_writes}, {publishes}")
        if mode == SEMI:
            require(publishes["last hold block"]["request"] == 0, "semi Break-in did not expire")
        feedback = stages["feedback still reports transmit"]
        require(feedback["request"] == 0 and feedback["dsp_tx"] and not feedback["rx_enabled"],
                "resume ignored outstanding DSP transmit feedback")
    else:
        require(not status_writes and publishes["key already down"] == dict(tx=0, request=0),
                "Break-in OFF unexpectedly requested transmit")
    require(result["text"] == REPLY_TEXT and result["stages"][-1]["rx_enabled"]
            and result["stages"][-1]["text"].startswith("E"),
            f"local sidetone leaked or first incoming character was lost: {result['text']!r}")
    return dict(delay_threshold_ticks=delay, stock_status_writes=status_writes, after_first_pcm=publishes, pcm=result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    firmware, _, _, digest, _ = load(args.dat.read_bytes())
    with TemporaryDirectory() as folder:
        code, entry = build(Path(folder), address=TEST_CODE)
    results = {f"{name}/{mode_name}": trial(firmware, code, entry, mode, command)
               for name, command in (("CW", 3), ("CW-R", 7))
               for mode, mode_name in enumerate(("off", "semi", "full"))}
    # The blocked audio is independently intelligible if supplied as ordinary RX PCM.
    control = probe(radio(firmware, 0), [("unblocked sidetone", audio(SIDETONE_TEXT, trim_leading=True), None)],
                    code, entry, 0, 1)
    require(control["text"] == SIDETONE_TEXT, "sidetone negative control is not decodable")
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(dict(stock_main_sha256=digest, runs=results, unblocked=control),
                                       indent=2)+"\n", encoding="utf-8")
    print(f"Six offline J140 CW Break-in cases passed: {args.evidence}")


if __name__ == "__main__":
    main()
