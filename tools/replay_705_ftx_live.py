"""Exercise continuous 8 kHz receive from J140 DMA in a single Cortex-A9 guest."""

import json
from hashlib import sha256
from shutil import which
from struct import unpack
import subprocess
from time import perf_counter, sleep

from elftools.elf.elffile import ELFFile
from tools.decode_705_main import decode_main
from tools.emulate_705 import arm, machine, uc
from tools.probe_705_cw_pcm import DECIMATED
from tools.probe_705_rx_audio import AUDIO_GATE, DMAC
from tools.replay_705_ftx_arm import ROOT, LIB, OUT, PCM, STOP, SP

BASELINE = ROOT / ".analysis/j140-sstv-rx4-tx4/705J140-CW-D6-SSTV-RX4-TX4.dat"
LAB = OUT / "live-rx"
CODE = ROOT / "samples/ftx"


def build(*, fixture=True):
    LAB.mkdir(parents=True, exist_ok=True)
    elf = LAB / ("receive.elf" if fixture else "receive-module.elf")
    api = "live_open live_open_gps live_close live_poll live_capture live_vfo live_pending live_gaps live_overruns view_draw view_page live_panel_key".split()
    if fixture:
        api += "live_last_slot row_hz row_snr row_text fixture_clock fixture_captures fixture_input".split()
    # Stock graphics callbacks in the J140 panel replay return to an A32 caller.
    view = LAB / "j140_rx_view.o"
    subprocess.run(
        [
            "arm-none-eabi-gcc",
            "-std=gnu11",
            "-Os",
            "-marm",
            "-mcpu=cortex-a9",
            "-mfpu=vfpv3-d16",
            "-mfloat-abi=softfp",
            "-ffunction-sections",
            "-fdata-sections",
            "-I", LIB,
            "-c",
            CODE / "j140_rx_view.c",
            "-o",
            view,
        ],
        check=True,
    )
    # The pinned upstream's limit of 20 symbols excludes late FT4 signals
    # around DT +0.5 s. Apply this one native-only tuning to a build copy.
    decoder = LIB / "ft8/decode.c"
    original = decoder.read_text(encoding="utf-8")
    limit = "candidate.time_offset < 20"
    if original.count(limit) != 1:
        raise ValueError("recheck the FT4 timing window for this ft8_lib revision")
    native = LAB / "decode.c"
    native.write_text(
        original.replace(limit, "candidate.time_offset < (wf->protocol == FTX_PROTOCOL_FT4 ? 28 : 20)"),
        encoding="utf-8",
    )
    src = [
        CODE / "station.c",
        CODE / "live_rx.c",
        CODE / "j140_rx_clock.c",
        view,
        LIB / "common/monitor.c",
        *(native if path == decoder else path for path in sorted((LIB / "ft8").glob("*.c"))),
        *sorted((LIB / "fft").glob("*.c")),
    ]
    if fixture:
        src.append(ROOT / "tools/fixtures/ftx_j140_pcm.c")
    subprocess.run(
        [
            "arm-none-eabi-gcc",
            "-std=gnu11",
            "-Os",
            "-mthumb",
            "-mcpu=cortex-a9",
            "-mfpu=vfpv3-d16",
            "-mfloat-abi=softfp",
            "-ffunction-sections",
            "-fdata-sections",
            "-DHAVE_STPCPY",
            "-DFTX_RX_RATE=8000",
            "-DLOG_PRINTF(...)=((void)0)",
            "-I",
            LIB,
            "-I",
            LIB / "ft8",
            "-I",
            CODE,
            "-nostartfiles",
            "--specs=nano.specs",
            "--specs=nosys.specs",
            "-Wl,--gc-sections,-e,live_open,-Ttext=0x100000," + ",".join("-u," + name for name in api),
            *src,
            *([] if fixture else ["-flto"]),
            "-o",
            elf,
            "-lm",
        ],
        check=True,
    )
    return elf


class Guest:
    def __init__(self, elf, cpu, *, map_dma=True):
        self.cpu = cpu
        cpu.mem_map(0x100000, 0x400000)
        if map_dma:
            cpu.mem_map(DMAC, 4096)
        with elf.open("rb") as f:
            img = ELFFile(f)
            self.symbols = {s.name: s["st_value"] for s in img.get_section_by_name(".symtab").iter_symbols()}
            for segment in img.iter_segments():
                if segment["p_type"] == "PT_LOAD":
                    cpu.mem_write(segment["p_vaddr"], segment.data())
        assert "tx_slot" not in self.symbols
        self.taps = 0

        def observe(c, *_):
            batch = c.mem_read(c.reg_read(arm.UC_ARM_REG_SP) + 8, 12)
            c.mem_write(self.symbols["observed_pcm"], bytes(batch))
            self.taps += 1

        cpu.hook_add(uc.UC_HOOK_CODE, observe, begin=DECIMATED, end=DECIMATED)
        cpu.reg_write(arm.UC_ARM_REG_C1_C0_2, 0xF00000)
        cpu.reg_write(arm.UC_ARM_REG_FPEXC, 0x40000000)
        cpu.mem_write(AUDIO_GATE, b"\1")
        cpu.mem_write(SP - 65536, b"\xa5" * 65536)

    def call(self, name, *args):
        cpu = self.cpu
        regs = (arm.UC_ARM_REG_R0, arm.UC_ARM_REG_R1, arm.UC_ARM_REG_R2, arm.UC_ARM_REG_R3)
        for reg, value in zip(regs, args):
            cpu.reg_write(reg, value)
        cpu.reg_write(arm.UC_ARM_REG_CPSR, 0x1F)
        cpu.reg_write(arm.UC_ARM_REG_SP, SP)
        cpu.reg_write(arm.UC_ARM_REG_LR, STOP | 1)
        cpu.emu_start(self.symbols[name], STOP, timeout=30_000_000)
        assert cpu.reg_read(arm.UC_ARM_REG_PC) == STOP, name
        return cpu.reg_read(regs[0])

    def feed(self, pcm, poll=True):
        assert len(pcm) % 12 == 0
        self.cpu.mem_write(PCM, pcm)
        before = self.taps
        result = self.call("fixture_input", PCM, len(pcm) // 12, int(poll))
        assert result == 0xFFFFFFFF or result <= 48, hex(result)
        assert self.taps - before == len(pcm) // 12
        return self.result(result)

    def result(self, result):
        if result == 0xFFFFFFFF:
            return None
        rows = [
            bytes(self.cpu.mem_read(self.call("row_text", n), 40)).split(b"\0")[0].decode()
            for n in range(result)
        ]
        return self.call("live_last_slot"), rows


def recording(path, samples):
    raw = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-ac", "1", "-ar", "8000", "pipe:1"]
    )
    return raw[: 2 * samples].ljust(2 * samples, b"\0")


def exercise(g, ft4):
    length = 60000 if ft4 else 120000
    path = OUT / "FT4/independent/000000_000001.wav" if ft4 else LIB / "test/wav/websdr_test1.wav"
    pcm = recording(path, length)
    wanted = (
        {"CQ JA1ABC PM95", "CQ DL1ABC JO62", "F4ABC I4ABC RR73", "CQ F4ABC JN18"}
        if ft4
        else {"CQ IK4LZH JN54"}
    )
    # Start 5 samples before a boundary to exercise a boundary inside a
    # six-sample interrupt. Also cross the 32-bit ADC sample counter rollover.
    first = 0xFFFFC000
    start_id = 11518
    g.call("live_open", int(ft4), first, start_id, length - 5)
    g.call("fixture_clock", first)
    count = 10 if ft4 else 4
    stream = bytes(10) + b"".join(bytes(length * 2) if i % 4 == 2 else pcm for i in range(count)) + bytes(2)
    results = []
    max_wall = 0
    for at in range(0, len(stream), 2880):
        start = perf_counter()
        result = g.feed(stream[at : at + 2880])
        max_wall = max(max_wall, perf_counter() - start)
        if result is not None:
            results.append(result)
    result = g.result(g.call("live_poll"))
    if result is not None:
        results.append(result)
    assert [s for s, _ in results] == list(range(start_id + 1, start_id + 1 + count)), results
    for i, (_, rows) in enumerate(results):
        assert wanted.issubset(rows) if i % 4 != 2 else not rows, (i, rows)
    assert g.call("live_overruns") == g.call("live_gaps") == 0
    heap = unpack("<I", g.cpu.mem_read(g.symbols["heap_end.0"], 4))[0] - g.symbols["_end"]
    g.call("live_close")
    assert g.feed(bytes(120)) is None
    return dict(
        slot_seconds=length / 8000,
        slots=[dict(id=s, rows=len(rows)) for s, rows in results],
        acquisition_seconds=length / 8000 * count,
        overruns=0,
        gaps=0,
        heap_growth_bytes=heap,
        max_emulator_batch_wall_ms=round(max_wall * 1000, 2),
        input=path.name,
    )


def faults(g):
    g.call("live_open", 1, 0, 0, 0)
    g.call("fixture_clock", 0)
    g.feed(bytes(12 * 2300), False)
    assert g.call("live_overruns") == 252
    for _ in range(86):
        assert g.result(g.call("live_poll")) is None
    # The next block carries the first surviving sample number after the loss.
    remaining = (60000 - 2300 * 6) * 2
    assert g.feed(bytes(remaining)) is None
    assert g.call("live_gaps") == 1
    assert g.feed(bytes(120000)) == (1, [])
    g.call("live_close")
    return dict(dropped_blocks=252, discarded_slots=[0], next_complete_slot=1)


def retune(g):
    pcm = recording(OUT / "FT4/independent/000000_000001.wav", 60000)
    g.call("live_open", 1, 0, 0, 0)
    g.call("fixture_clock", 0)
    g.call("live_vfo", 14080000, 0, 0, 0)
    assert g.feed(pcm[:60000]) is None
    g.call("live_vfo", 14080100, 30000, 0, 30000)
    assert g.feed(pcm[60000:]) is None
    slot, rows = g.feed(pcm)
    assert slot == 1 and len(rows) == 4
    g.call("live_close")
    return dict(discarded_split_slot=0, first_complete_slot=slot, messages=len(rows))


def gps_anchor(main_image, elf):
    from tools.replay_705_gps_inputs import GPSGuest, RMC, UTC_AGE

    gps = GPSGuest(main_image)
    g = Guest(elf, gps.cpu)
    edge = 0xFFFFFFF0
    first = (edge + 4000) & 0xFFFFFFFF
    assert g.call("live_open_gps", 1, 86392, edge, first) == 0
    for t in ("235950", "235951", "235952"):
        gps.feed(RMC.format(time=t))
    assert gps.state()["time_hhmmss"] == "235952"
    assert g.call("live_open_gps", 1, 86391, edge, first) == 0
    assert g.call("live_open_gps", 1, 86392, edge, (edge + 8000) & 0xFFFFFFFF) == 0
    assert g.call("live_open_gps", 1, 86392, edge, first) == 1
    g.call("fixture_clock", first)
    assert g.feed(bytes(120000)) == (11519, [])
    assert g.feed(bytes(120000)) == (11520, [])
    gps.expire(UTC_AGE)
    assert g.call("live_open_gps", 1, 86392, edge, first) == 0 and not g.call("live_enabled")
    return dict(
        gps_second="23:59:52",
        first_phase_seconds=0.5,
        slots=[11519, 11520],
        rejected_invalid_expired_or_mismatched=True,
        sample_edge="fixture",
    )


def busy_ft4_input():
    folder = OUT / "FT4/busy"
    folder.mkdir(parents=True, exist_ok=True)
    source = ROOT / "tools/fixtures/ft4-busy-messages.txt"
    wav = folder / "000000_000001.wav"
    manifest = folder / "messages.txt"
    if not wav.exists() or not manifest.exists() or manifest.read_text() != source.read_text():
        manifest.write_text(source.read_text(), encoding="ascii")
        command = ["ft4sim_mult", "12", "1"]
        if not which(command[0]):
            command = ["wsl", "-d", "Debian", "--", *command]
        with (folder / "generated.txt").open("wb") as log:
            subprocess.run(command, cwd=folder, stdout=log, check=True)
    return folder


def paced_ft4(g, folder, minimum):
    """Charge emulation, stock DMA and decoding against the arrival clock.
    Samples due during a synchronous decode are enqueued before polling again."""
    wav = folder / "000000_000001.wav"
    pcm = recording(wav, 60000)
    expected = {
        line.split(maxsplit=5)[5].strip()
        for line in (folder / "generated.txt").read_text().splitlines()
        if line.strip()
    }
    total = 80000  # Eight UTC slots in 6-sample blocks.
    g.call("fixture_clock", 0)
    g.call("live_open", 1, 0, 0, 0)
    start = perf_counter()
    sent = peak = 0
    rows = []
    while sent < total or g.call("live_pending"):
        due = min(total, int((perf_counter() - start) * 8000 / 6))
        if due > sent:
            n = min(due - sent, 10000 - sent % 10000)
            at = sent % 10000 * 12
            assert g.feed(pcm[at : at + n * 12], False) is None
            sent += n
            peak = max(peak, g.call("live_pending"))
        if g.call("live_pending"):
            result = g.result(g.call("live_poll"))
            if result is not None:
                slot, messages = result
                assert minimum <= len(messages) <= len(expected) and set(messages) <= expected, messages
                rows.append(
                    dict(
                        slot=slot,
                        count=len(messages),
                        missing=sorted(expected - set(messages)),
                        late_ms=round((perf_counter() - start - (slot + 1) * 7.5) * 1000, 1),
                    )
                )
        else:
            sleep(0.0045)
    assert [r["slot"] for r in rows] == list(range(8))
    assert g.call("live_overruns") == g.call("live_gaps") == 0 and max(r["late_ms"] for r in rows) < 7500
    g.call("live_close")
    return dict(
        slots=rows,
        input_sha256=sha256(wav.read_bytes()).hexdigest(),
        transmitted=len(expected),
        producer_hz=8000,
        seconds=round(perf_counter() - start, 3),
        peak_queue_blocks=peak,
        capacity_blocks=2048,
        overruns=0,
        gaps=0,
        platform="host-paced Cortex-A9 emulation",
    )


def main():
    data = BASELINE.read_bytes()
    checksum = sha256(data).hexdigest()
    assert checksum == "5297e2581cdeb8f48af1ba6dd9b1bb33704675673c49b9448383f8d9a383c039"
    elf = build()
    main_image = bytes(decode_main(data)[1])
    g = Guest(elf, machine(main_image))
    report = dict(
        baseline=checksum,
        FT4=exercise(g, True),
        FT8=exercise(g, False),
        overrun_recovery=faults(g),
        retune=retune(g),
    )
    report["gps_alignment"] = gps_anchor(main_image, elf)
    report["FT4_paced"] = paced_ft4(g, OUT / "FT4/independent", 4)
    report["FT4_busy_paced"] = paced_ft4(g, busy_ft4_input(), 12)
    report["blocks_through_stock_pcm"] = g.taps
    assert g.taps == g.call("fixture_captures")
    for key, artifact in (("elf_text_data_bss", elf), ("module_lto_text_data_bss", build(fixture=False))):
        report[key] = list(
            map(int, subprocess.check_output(["arm-none-eabi-size", artifact]).splitlines()[1].split()[:3])
        )
        report[key + "_sha256"] = sha256(artifact.read_bytes()).hexdigest()
    stk = g.cpu.mem_read(SP - 65536, 65536)
    report["max_stack_written_bytes"] = 65536 - next(i for i, b in enumerate(stk) if b != 0xA5)
    (LAB / "check.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
