"""Exercise stock UTC Offset, FT settings and FTLOG.ADI in a local virtual radio."""
from argparse import ArgumentParser
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from struct import pack

from tools.build_705_e140_log_test import ROOT, decode_main, digest, load_a
from tools.emulate_705 import arm, call, machine, uc
from tools.replay_705_e140_ft import A_PREFIX, GRAPHICS_FLASH, OUT, symbols
from tools.replay_705_gps_inputs import BYTE_RX, GPS_INIT, GPS_MODE, RMC, nmea
from tools.replay_705_stock_install import european_update_rom
from tools.replay_705_vfo_split import exchange_in_guest, seed_vfos
from tools.verify_705_ftx_tx import mount_station_card


def check(path, baseline):
    dat = path.read_bytes()
    region = {"705J140.dat": "J", "705E140.dat": "E"}[path.name]
    main, flash = load_a(dat, digest(decode_main(dat)[1]))
    cpu = machine(main)
    cpu.mem_map(GRAPHICS_FLASH, A_PREFIX, uc.UC_PROT_READ)
    cpu.mem_write(GRAPHICS_FLASH, flash[:A_PREFIX])
    rom = lambda pc: pc
    if region == "E":
        stock = [bytes(decode_main((ROOT/f"firmware/705{r}140.dat").read_bytes())[1]) for r in "JE"]
        rom = european_update_rom(*stock)
    sy = symbols(OUT/"rx.elf")
    def ft(name, *args):
        return call(cpu, sy[name], *args, instruction_limit=0)
    def word(at, value):
        cpu.mem_write(at, pack("<I", value))
    def civ(payload):
        frame, _ = exchange_in_guest(cpu, payload, invoke=lambda pc, *args: call(cpu, rom(pc), *args))
        return frame[2:-1]
    assert ft("ft_data_ready")
    seed_vfos(cpu)
    files, pump, _ = mount_station_card(cpu, sy, rom=rom)
    labels = []
    def capture(c, pc, *_):
        if pc != sy["ft_blank"] & ~1:
            labels.append(bytes(c.mem_read(c.reg_read(arm.UC_ARM_REG_R0), 32)).split(b"\0")[0])
        c.reg_write(arm.UC_ARM_REG_PC, c.reg_read(arm.UC_ARM_REG_LR))
    for name in ("ft_blank", "ft_key", "ft_label"):
        pc = sy[name] & ~1
        cpu.hook_add(uc.UC_HOOK_CODE, capture, begin=pc, end=pc)
    current = sy["journal"] + 4*76
    path_on_card = r"C:\IC-705\FTLOG.ADI"
    rows = []
    assert bytes(cpu.mem_read(sy["pref"]+22, 1)) == b"\0"
    for label, offset, legacy, rtc, local in (
        ("reported", 480, 0, True, "20261114201015"),
        ("stale_preference", 480, -4, True, "20260101003015"),
        ("negative", -210, 32, True, "20261231235915"),
        ("quarter_hour", 345, 32, True, "20240301001015"),
        ("utc", 0, 32, True, "20261114131015"),
        ("gps", 480, 32, False, "20261114201015"),
    ):
        minutes = abs(offset)
        signed = f"{'-' if offset<0 else '+'}{minutes//60:02}:{minutes%60:02}"
        payload = bytes.fromhex(signed[1:].replace(":", "") + ("01" if offset < 0 else "00"))
        cmd = bytes.fromhex("1a 05 01 70")
        assert civ(cmd+payload) == b"\xfb" and civ(cmd) == cmd+payload
        cpu.mem_write(sy["pref"]+22, pack("b", legacy))
        word(sy["ftx_rtc"], int(rtc))
        ft4 = len(rows) % 2
        word(sy["ftx_ft4"], ft4)
        word(sy["ft_page"], 7)  # FT_TIME
        labels.clear()
        ft("ft_panel_draw", 1)
        if not baseline:
            assert (f"RTC UTC{signed}".encode() if rtc else b"GPS UTC") in labels, labels
            assert b"+15 min" not in labels and b"-15 min" not in labels
            assert all(ft("ft_panel_touch", x, 191) == 0 for x in (65, 240))
        if not rtc:
            cpu.mem_write(GPS_MODE, b"\1")
            call(cpu, rom(GPS_INIT))
        cpu.mem_write(current, pack("<7s7s5s5s4s4s15s15s2xIII", b"K1ABC", b"JA1ABC",
                                    b"PM95", b"FN42", b"-13", b"-09", b"", b"", 14074000, ft4, 6))
        start = datetime.strptime(local, "%Y%m%d%H%M%S")
        for step in (0, 1):
            t = start + timedelta(minutes=step)
            cpu.mem_write(0x2038079a, bytes.fromhex(t.strftime("%y%m%d00%H%M%S")))
            cmd = bytes.fromhex("1a 05 01 66")
            assert civ(cmd) == cmd+bytes.fromhex(t.strftime("%H%M"))
            if not rtc:
                utc = t - timedelta(minutes=offset)
                for sec in range(10,16):
                    sentence = RMC.replace("141126",utc.strftime("%d%m%y")).format(time=utc.replace(second=sec).strftime("%H%M%S"))
                    for octet in nmea(sentence):
                        call(cpu, rom(BYTE_RX), octet)
            if step == 0:
                assert ft("utc_stamp", current+32) == 1
            else:
                word(sy["log_complete"], 1)
                ft("consume_complete")
        word(sy["journal"]+1604, 0)
        ft("log_poll")
        pump()
        ft("log_poll")
        adi = files[path_on_card].decode("ascii")
        assert adi.count("<EOR>") == len(rows)+1
        fields = dict(re.findall(r"<(\w+):\d+>([^ ]+)", adi.splitlines()[-1]))
        assert fields.get("SUBMODE", fields["MODE"]) == ("FT4" if ft4 else "FT8")
        expected = start - timedelta(minutes=legacy*15 if baseline and rtc else offset)
        for suffix, tick in (("", expected), ("_OFF", expected+timedelta(minutes=1))):
            assert fields["QSO_DATE"+suffix] == tick.strftime("%Y%m%d")
            assert fields["TIME_OFF" if suffix else "TIME_ON"] == tick.strftime("%H%M%S")
        rows.append(dict(case=label, mode=fields.get("SUBMODE", fields["MODE"]),
                         clock="RTC" if rtc else "GPS", local=local, radio_offset=signed,
                         old_ft_offset_minutes=legacy*15, on=fields["QSO_DATE"]+fields["TIME_ON"],
                         off=fields["QSO_DATE_OFF"]+fields["TIME_OFF"]))
    return dict(region=region, dat_sha256=digest(dat), cases=rows), files[path_on_card]


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("dat", type=Path)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    report, adi = check(args.dat, args.baseline)
    args.folder.mkdir(exist_ok=True, parents=True)
    (args.folder/"card.json").write_text(json.dumps(report, indent=2)+"\n")
    (args.folder/"FTLOG.ADI").write_bytes(adi)
    print(report["region"], len(report["cases"]), "virtual SD records verified")
