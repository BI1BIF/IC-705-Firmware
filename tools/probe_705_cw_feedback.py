"""Check stock CW touch confirmation requests offline, without radio or LCD access.

Usage: python -m tools.probe_705_cw_feedback build.ic705sim report.json [--baseline]
The isolated ARM fixture exercises the original touch poll and CW state. It
observes the original beep sequencer, not acoustic output on a physical device.
"""
import argparse
import json
from pathlib import Path
from struct import pack

from tools.build_705_cw_sim import load_image
from tools.emulate_705 import arm, call, uc
from tools.probe_705_cw_field_audio import STATE
from tools.probe_705_cw_session import read_session
from tools.render_705_display import require
from tools.replay_705_ptt_tune import radio
from tools.replay_705_settings import TOUCH_POLL, TOUCH_SAMPLE
from tools.replay_705_vfo_split import exchange_in_guest

BEEP, SEQUENCER, BEEP_ENABLE = 0x2007D478, 0x203871A4, 0x203EAA7D


def replay(bundle, baseline=False):
    (main, _, _, digest, _), meta = load_image(bundle)
    cpu = radio(main, 0, pair=(7_030_000, 145_149_300), split=False)
    cpu.mem_write(meta['symbols']['cw_state_anchor'], pack('<I', STATE))
    cpu.mem_write(STATE, pack('<2I', 1, 1))
    cpu.mem_write(STATE+1692, pack('<I', 350))
    reply, _ = exchange_in_guest(cpu, bytes((6, 3, 1)))
    require(reply[2:-1] == b'\xfb', 'stock mode selection failed')
    beeps = []

    def observe(_cpu, _pc, _size, _data):
        beeps.append(cpu.reg_read(arm.UC_ARM_REG_R0))
    cpu.hook_add(uc.UC_HOOK_CODE, observe, begin=BEEP, end=BEEP)

    def poll(x=9999, y=9999, up=0):
        cpu.mem_write(TOUCH_SAMPLE, pack('>BHH', up, x, y))
        call(cpu, TOUCH_POLL)

    cases = []
    for enabled in (0, 1):
        cpu.mem_write(BEEP_ENABLE, bytes((enabled,)))
        call(cpu, 0x2000E73C, 0)  # Original stop, between independent test cases.
        poll()
        for label, x, y, field in (
                ('SET open', 430, 251, 'color_open'), ('SET close', 430, 251, 'color_open'),
                ('WPM open', 430, 157, 'speed_picker'), ('WPM close', 430, 157, 'speed_picker'),
                ('page 2', 48, 251, 'menu_two'), ('page 1', 48, 251, 'menu_two')):
            call(cpu, 0x2000E73C, 0)
            start = len(beeps)
            before = read_session(cpu, STATE)[field]
            poll(x, y)
            after = read_session(cpu, STATE)[field]
            effective = bool(cpu.mem_read(SEQUENCER, 1)[0])
            for _ in range(4):
                poll(x, y)
            poll()
            requested = beeps[start:]
            require(before != after and requested == ([] if baseline else [1]) and
                    effective == (bool(enabled) and not baseline),
                    f'{label}/{enabled}: action, one-shot feedback or Beep preference mismatch: {requested}')
            cases.append(dict(button=label, beep_enabled=enabled, changed=before != after,
                              requests=requested, sequencer_active_after_press=effective))

        for label,x,y in (('unused TX MEM', 335, 251), ('unused center', 240, 251),
                          ('blank text', 100, 190)):
            call(cpu, 0x2000E73C, 0)
            start = len(beeps)
            poll(x,y)
            poll()
            require(not beeps[start:] and not cpu.mem_read(SEQUENCER,1)[0], f'{label}: spurious tone')
            cases.append(dict(button=label, beep_enabled=enabled, requests=[]))

        call(cpu, 0x2000E73C, 0)
        start = len(beeps)
        poll(145,251)
        cpu.mem_write(0x20381E08, pack('<I', 1100*(enabled+1)))
        poll(145,251)
        poll(145,251)
        poll()
        require(beeps[start:] == ([] if baseline else [1]), 'held HOLD/CLR repeated the tone')
        cases.append(dict(button='long HOLD/CLR', beep_enabled=enabled, requests=beeps[start:]))

    return dict(application_sha256=digest, baseline=baseline,
                scope='original ARM touch poll and beep sequencer; no physical audio output', cases=cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('report', type=Path)
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    evidence = replay(args.bundle, args.baseline)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open('x', encoding='utf-8') as out:
        json.dump(evidence, out, indent=2)
        out.write('\n')
    print(f'CW feedback: {len(evidence["cases"])} cases passed; {args.report}')


if __name__ == '__main__':
    main()
