"""Replay the freestanding Cortex-A9 spectrum helper on synthetic 8 kHz PCM."""

from math import pi, sin
from pathlib import Path
from shutil import which
from struct import pack
from subprocess import check_output, run
from tempfile import TemporaryDirectory
from unittest import TestCase, SkipTest


class CwAudioSpectrumTests(TestCase):
    def test_receive_audio_rows(self):
        for tool in ("arm-none-eabi-gcc", "arm-none-eabi-nm", "arm-none-eabi-objcopy"):
            if not which(tool):
                self.skipTest(f"{tool} not installed")
        try:
            from tools.emulate_705 import BASE, call, machine, uc
        except ModuleNotFoundError as error:
            if error.name != "unicorn":
                raise
            raise SkipTest("Unicorn not installed") from error

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, elf, raw = (root / f"test.{suffix}" for suffix in ("c", "elf", "bin"))
            source.write_text(
                '#include "cw-audio-spectrum.h"\n'
                'void reset(CwAudioSpectrum *s) { cw_spectrum_reset(s); }\n'
                'int feed(CwAudioSpectrum *s, const int16_t *p, uint8_t *o) { return cw_spectrum_feed(s, p, o); }\n',
                encoding="ascii",
            )
            include = Path(__file__).resolve().parents[1] / "samples"
            run(["arm-none-eabi-gcc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-Os", "-mcpu=cortex-a9",
                 "-marm", "-mfloat-abi=soft", "-ffreestanding", "-fno-builtin", "-nostdlib", "-I", str(include),
                 f"-Wl,-Ttext={BASE:#x},-e,feed,--build-id=none", str(source), "-o", str(elf)], check=True)
            symbols = {name: int(addr, 16) for addr, _, name in (line.split() for line in check_output(
                ["arm-none-eabi-nm", "--defined-only", str(elf)], text=True).splitlines())}
            run(["arm-none-eabi-objcopy", "-O", "binary", str(elf), str(raw)], check=True)
            cpu = machine(raw.read_bytes())

        state, pcm, levels = 0x20010000, 0x20011000, 0x20012000
        sentinel = b"\xa5" * 20
        instructions = 0

        def block(_cpu, _address, length, _data):
            nonlocal instructions
            instructions += length // 4

        cpu.hook_add(uc.UC_HOOK_BLOCK, block)

        def feed(tone):
            nonlocal instructions
            instructions = 0
            cpu.mem_write(pcm, pack("<80h", *tone))
            ready = call(cpu, symbols["feed"], state, pcm, levels, instruction_limit=45000)
            self.assertLess(instructions, 40000)
            return ready

        def row(hz, amplitude):
            tone = [round(amplitude * sin(2*pi*hz*t/8000)) for t in range(320)]
            cpu.mem_write(levels, sentinel)
            for start in range(0, len(tone), 80):
                ready = feed(tone[start:start+80])
                self.assertEqual(ready, int(start == 240))
                if not ready:
                    self.assertEqual(bytes(cpu.mem_read(levels, 20)), sentinel)
            return list(cpu.mem_read(levels, 20))

        self.assertEqual(row(0, 0), [0] * 20)
        weak = row(600, 1200)
        strong = row(600, 12000)
        other = row(900, 12000)
        self.assertEqual(strong.index(max(strong)), (600 - 300) // 50)
        self.assertEqual(weak.index(max(weak)), (600 - 300) // 50)
        self.assertEqual(other.index(max(other)), (900 - 300) // 50)
        self.assertGreater(max(strong) - max(weak), 50)
        self.assertGreater(strong[6] - strong[12], 80)
        self.assertGreater(other[12] - other[6], 80)

        between = row(624, 32767)
        self.assertIn(between.index(max(between)), (6, 7))
        self.assertGreater(min(between[6:8]) - between[12], 80)
        high = row(1250, 32767)
        self.assertEqual(high.index(max(high)), 19)

        self.assertEqual(feed([32767, -32768] * 40), 0)
        self.assertEqual(feed([32767, -32768] * 40), 0)
        call(cpu, symbols["reset"], state)
        self.assertEqual(row(0, 0), [0] * 20)
