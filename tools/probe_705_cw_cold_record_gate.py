"""Replay exact RX-FIX NOR with a forced gate (0/2) or stock SQL-derived gate (stock-sql)."""

import argparse
import json
from pathlib import Path

from tools.build_705_cw_sim import load_image
from tools.decode_705_main import BOOT_SIZE, J140_DAT_SHA, J140_MAIN_SHA
from tools.probe_705_boot_selection import FIRST, NOR_BYTES
from tools.render_705_display import load, require
from tools.replay_705_cw_dat import PREVIOUS_KEYER_DAT, PREVIOUS_KEYER_MAIN
from tools.replay_705_cw_upgrade import boot, digest
from tools.replay_705_stock_install import A_PREFIX, SELECTOR, SHARED, load_a


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("stock", "previous", "candidate", "pc_bundle", "update_evidence", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("gate", choices=("0", "2", "stock-sql"))
    a = parser.parse_args()
    require(not a.output.exists(), "expected a new output directory")
    update = json.loads(a.update_evidence.read_text(encoding="utf-8"))
    stock, previous, candidate = (path.read_bytes() for path in (a.stock, a.previous, a.candidate))
    require(digest(stock) == update["stock_dat_sha256"] == J140_DAT_SHA and
            digest(previous) == update["previous_cw_dat_sha256"] == PREVIOUS_KEYER_DAT and
            digest(candidate) == update["candidate_sha256"] and update["target_slot"] == "A" and
            digest(a.pc_bundle.read_bytes()) == update["source_pc_bundle_sha256"], "unexpected RX-FIX inputs")
    _, stock_a = load_a(stock, J140_MAIN_SHA)
    _, old_a = load_a(previous, PREVIOUS_KEYER_MAIN)
    app, candidate_a = load_a(candidate, update["candidate_main_sha256"])
    bundle, symbols = load_image(a.pc_bundle)
    stock_image = load(stock)
    require(app == bundle[0] and bundle[1:3] == stock_image[1:3] and bundle[4] == stock_image[4],
            "PC metadata did not match the DAT application or original resources")

    nor = bytearray(b"\xff"*NOR_BYTES)
    nor[:A_PREFIX] = candidate_a[:A_PREFIX]
    nor[A_PREFIX:SELECTOR] = old_a[BOOT_SIZE:A_PREFIX]
    nor[SHARED:SHARED+len(stock_a)-A_PREFIX] = stock_a[A_PREFIX:]
    require(digest(nor) == update["writer"]["nor_sha256_after"] == update["cold_boot"]["snapshot_sha256"],
            "snapshot reconstructed from the two DATs differed from the guest-written bytes")
    closed_sql = a.gate == "stock-sql"
    gate = 0 if closed_sql else int(a.gate)
    print(f"Cold-booting the verified NOR with {a.gate}.", flush=True)
    result, frames = boot(bytes(nor), (app, *stock_image[1:3], bundle[3], stock_image[4]), symbols,
                          record_gate=None if closed_sql else gate, closed_sql=closed_sql)
    reset, panel = result["nor_boot"], result["panel"]
    rx = panel["cw_receive"]
    require(reset["source_slot"] == hex(FIRST) and reset["application_ram_empty_before_reset"] and
            reset["application_sha256"] == update["candidate_main_sha256"] and not panel["cw_packaged_boot"]["host_attachment"] and
            rx["cw_input_recording_gate"] == gate and rx["shown_text"] == "CQ" and rx["dma_groups"] == 2827 and
            rx["lcd_waveform_rows"] > 2 and rx["dropped_dma_groups"] == 0 and panel["exit_committed"],
            "packaged CW did not take all DMA samples and present a waveform and CQ")
    a.output.mkdir(parents=True)
    scope = ("stock gate from virtual EEPROM SQL with injected PCM; no gate override" if closed_sql else
             "controlled recording state only while ARM copies PCM into CW")
    report = dict(scope=scope+"; no hardware or updater",
                  dat_sha256=update["candidate_sha256"], **result)
    (a.output/"evidence.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    (a.output/"cw_decoded.png").write_bytes(frames[8])
    print(f"Gate {a.gate}: {rx['dma_groups']} groups, {rx['lcd_waveform_rows']} waveform rows, {rx['shown_text']}; {a.output}")


if __name__ == "__main__":
    main()
