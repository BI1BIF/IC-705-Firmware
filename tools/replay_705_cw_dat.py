"""Repack a known J140 CW build and verify it with the stock updater on virtual NOR."""

import argparse
from hashlib import md5
import json
from pathlib import Path
from struct import unpack_from

from tools.build_705_cw_sim import digest, load_image
from tools.decode_705_main import BOOT_SIZE, J140_DAT_SHA, J140_MAIN_SHA, checked_group_a
from tools.emulate_705 import BOOT_HASH
from tools.probe_705_boot_selection import FIRST, NOR_BYTES, SECOND
from tools.render_705_display import load, require
from tools.replay_705_nor_boot import with_pc_main
from tools.replay_705_stock_install import A_PREFIX, SELECTOR, SHARED, load_a, update_a


NATIVE_TOUCH_BUNDLE = "cd198808e0f00f0edb2308071145da266e4fa18a43a318fb942001b99221ab85"
NATIVE_UI_BUNDLE = "d2fb5a11831a844a0a18b0fae843426c517259885b5ea658cfe0cb0a6ea8698b"
CW_BUNDLE_SHAS = {
    "705e6b0041fbbbdb4752cadd834483b1d99b04d43594017efc81d16c1a5b7ece",
    "8391f3e3a8c2d3e85130ccc9ecff7aa1e4088dc8caaa4426e004fd91409429d4",
    "4e423e121cae187ba90b45f48312f12233fa298d292268a93483ed68ec4b81b5",
    "1916a340ed6ed7222dc1367372b050b8b238c565c491ae8e5e4c0228c89fa555",
    NATIVE_TOUCH_BUNDLE,
    NATIVE_UI_BUNDLE,
}
PREVIOUS_KEYER_DAT = "da596f0ba9d201165a90f51816018f960280633b9f665cf3f27ffc023407e8da"
PREVIOUS_KEYER_MAIN = "1be7f473e2329f61537adf9d496d7dc2e9de1b48eceb9bf0bd8d89170aba0f70"


def pack_cw_dat(stock_dat, cw_image):
    require(digest(stock_dat) == J140_DAT_SHA and digest(cw_image.read_bytes()) in CW_BUNDLE_SHAS,
            "expected the known official and PC-only J140 inputs")
    stock = load(stock_dat)
    bundle, symbols = load_image(cw_image)
    require(bundle[1:3] == stock[1:3] and bundle[4] == stock[4], "CW bundle changed the stock resources")
    candidate, parts = pack_main_dat(stock_dat,stock,bundle[0])
    stock_a, candidate_a, checksum, stored = parts
    return candidate, (stock, stock_a, bundle, symbols, bundle[0], candidate_a, checksum, stored)


def pack_main_dat(stock_dat, stock, main, *, deeper=False):
    require(digest(stock_dat)==J140_DAT_SHA and digest(stock[0])==J140_MAIN_SHA, "expected stock J140")
    _, group = checked_group_a(stock_dat)
    _, stock_a = load_a(stock_dat, J140_MAIN_SHA)
    packed = with_pc_main(stock[2], main, deeper=deeper)
    stored, = unpack_from("<I", packed, BOOT_SIZE)
    # Rejoin stock encoded bytes after one unchanged padding byte has restored feedback state.
    join = BOOT_SIZE+8+stored+1
    require(stock_a[join-1:join] == packed[join-1:join] == b"\xff", "no unchanged padding to rejoin")
    start, end = group["offset"], group["end_exclusive"]
    group_a = bytearray(stock_dat[start:end])
    previous = packed[BOOT_SIZE-1]
    for i in range(BOOT_SIZE, join):
        plain = packed[i]
        group_a[i] = plain ^ ((previous + start + i - 0x19) & 255)
        previous = plain
    checksum = md5(group_a, usedforsecurity=False).digest()
    candidate = stock_dat[:start]+group_a+checksum+stock_dat[end+16:]
    candidate_main, candidate_a = load_a(candidate, digest(main))
    require(candidate_main == main and candidate_a == packed[:join]+stock_a[join:] and
            candidate[:start+BOOT_SIZE] == stock_dat[:start+BOOT_SIZE] and
            candidate[end+16:] == stock_dat[end+16:] and len(candidate) == len(stock_dat),
            "candidate did not round-trip with stock bootstrap, metadata and peripheral images intact")
    return candidate, (stock_a, candidate_a, checksum, stored)


def run(stock_dat, cw_image, previous=None, *, previous_in_second=True):
    from tools.replay_705_cw_upgrade import boot
    candidate, data = pack_cw_dat(stock_dat, cw_image)
    stock, stock_a, bundle, symbols, candidate_main, candidate_a, checksum, stored = data
    initial = bytearray(b"\xff"*NOR_BYTES)
    initial[:A_PREFIX] = stock_a[:A_PREFIX]
    initial[A_PREFIX:SELECTOR] = stock_a[BOOT_SIZE:A_PREFIX]
    initial[SHARED:SHARED+len(stock_a)-A_PREFIX] = stock_a[A_PREFIX:]
    initial_main, target, end, slot, tag = stock[0], A_PREFIX, SELECTOR, SECOND, stock_a[0x4F00:0x4F10]
    active_second = previous is not None and previous_in_second
    if previous is not None:
        require(digest(previous) == PREVIOUS_KEYER_DAT, "expected the previously delivered KEYER test DAT")
        initial_main, prior_a = load_a(previous, PREVIOUS_KEYER_MAIN)
        require(prior_a[:BOOT_SIZE] == stock_a[:BOOT_SIZE] and prior_a[A_PREFIX:] == stock_a[A_PREFIX:],
                "previous image changed the bootstrap or shared data")
        if active_second:
            initial[A_PREFIX:SELECTOR] = prior_a[BOOT_SIZE:A_PREFIX]
            initial[SELECTOR:SELECTOR+16] = tag
            target, end, slot, tag = BOOT_SIZE, A_PREFIX, FIRST, b"\xff"*16
        else:
            initial[BOOT_SIZE:A_PREFIX] = prior_a[BOOT_SIZE:A_PREFIX]
    print(f"Memory-only candidate {digest(candidate)}; running J140 updater from {'B' if active_second else 'A'}.", flush=True)
    written, writer = update_a(initial_main, candidate, bytes(initial), prior=stock_dat if previous is None else previous,
                               active_second=active_second)
    changed = {int(at, 16) for at in writer["erased_sectors"]} | {int(at, 16) for at in writer["programmed_by_sector"]}
    require(changed and all(target <= at < end or at == SELECTOR for at in changed),
            "stock updater issued an erase or page program outside the inactive application and the selector")
    require(digest(written[:BOOT_SIZE]) == BOOT_HASH, "stock bootstrap contents changed")
    expected = initial.copy()
    expected[target:end] = candidate_a[BOOT_SIZE:A_PREFIX]
    expected[SELECTOR:SELECTOR+16] = tag
    require(written == expected, "guest-written NOR differs from independently decoded candidate layout")
    require(writer["completion"]["restart_tail"]["watchdog_request_pc"], "no stock reset request")
    print("Stock updater verified the target and requested restart; booting the exact NOR it wrote.", flush=True)

    native_touch = digest(cw_image.read_bytes()) in (NATIVE_TOUCH_BUNDLE, NATIVE_UI_BUNDLE)
    after, frames = boot(written, (candidate_main, *stock[1:3], bundle[3], stock[4]), symbols,
                         closed_sql=native_touch)
    reset, panel = after["nor_boot"], after["panel"]
    require(after["snapshot_sha256"] == writer["nor_sha256_after"] and reset["source_slot"] == hex(slot) and
            reset["application_ram_empty_before_reset"] and reset["application_sha256"] == bundle[3] and
            not panel["cw_packaged_boot"]["host_attachment"] and panel["cw_receive"]["shown_text"] == "CQ",
            "guest-written slot did not cold boot and decode CQ on the LCD")
    evidence = dict(scope="RZ/A1 Cortex-A9 in Unicorn with modeled peripherals; in-memory DAT and virtual NOR only",
                    stock_dat_sha256=J140_DAT_SHA, source_pc_bundle_sha256=digest(cw_image.read_bytes()),
                    candidate_sha256=digest(candidate),
                    candidate_bytes=len(candidate), candidate_a_md5=checksum.hex(), candidate_main_sha256=bundle[3],
                    compressed_main_bytes=stored, unchanged_dat_header_bootstrap_b_c_d_and_footer=True,
                    stock_updater_main_sha256=digest(initial_main),
                    previous_cw_dat_sha256=digest(previous) if previous is not None else None,
                    target_slot="A" if active_second else "B", verified_entire_virtual_nor=True,
                    bootstrap_active_slot_and_shared_no_erase_or_program=True, writer=writer, cold_boot=after,
                    decoded_frame_sha256=digest(frames[8]))
    return evidence, frames[8], candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock_dat", type=Path)
    parser.add_argument("cw_bundle", type=Path)
    parser.add_argument("output", type=Path, help="new directory for JSON and LCD evidence")
    parser.add_argument("--dat-output", type=Path, help="save the tested bytes to a new DAT after verification")
    parser.add_argument("--previous-keyer", type=Path, help="model the previously delivered KEYER build active in B")
    args = parser.parse_args()
    require(not args.output.exists(), "evidence directory already exists")
    if args.dat_output:
        require(args.dat_output.suffix.lower() == ".dat" and not args.dat_output.exists(),
                "expected a new DAT path")
    previous = args.previous_keyer.read_bytes() if args.previous_keyer else None
    report, frame, candidate = run(args.stock_dat.read_bytes(), args.cw_bundle, previous)
    require(digest(args.stock_dat.read_bytes()) == J140_DAT_SHA and
            digest(args.cw_bundle.read_bytes()) == report["source_pc_bundle_sha256"],
            "input file changed")
    args.output.mkdir(parents=True)
    (args.output/"evidence.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    (args.output/"cw_decoded.png").write_bytes(frame)
    if args.dat_output:
        args.dat_output.parent.mkdir(parents=True, exist_ok=True)
        with args.dat_output.open("xb") as out:
            out.write(candidate)
        require(digest(args.dat_output.read_bytes()) == report["candidate_sha256"], "saved DAT digest differs")
    print(f"Stock DAT update and CQ on the virtual LCD passed: {args.output}")


if __name__ == "__main__":
    main()
