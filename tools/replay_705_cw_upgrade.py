"""Exercise a stock J140 to CW upgrade entirely in the PC's virtual NOR."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import unpack_from
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from tools.build_705_cw_sim import load_image
from tools.decode_705_main import BOOT_SIZE
from tools.emulate_705 import BOOT, machine
from tools.probe_705_boot_selection import FIRST, SECOND, NOR_BYTES
from tools.probe_705_cw_break_in import audio
from tools.render_705_display import GRAPHICS_FLASH, load, require
from tools.replay_705_font_boot import replay_resource_task
from tools.replay_705_nor_boot import boot_from_nor, with_pc_main
from tools.replay_705_stock_install import A_PREFIX, SELECTOR, SHARED, load_a


SECTOR, PAGE = BOOT_SIZE, 0x100


def digest(data):
    return sha256(data).hexdigest()


def boot(nor, image, metadata=None, *, missing_secondary=False, record_gate=None, closed_sql=False):
    main, large, graphics, _, small = image
    previews = []
    control = replay_resource_task(main, large, small, fixture_return=False,
                                   loader=graphics[0x4000:0x49BC], adc_sample=0x180, scif_wait="board_power",
                                   vbus_high=True, power_key_released=False, riic0_idle=True, riic0_finish="stop",
                                   eeprom=b"\xff"*16, startup_dma="format-current", scene_preview=previews,
                                   startup_home_probe=True, no_power_on_check=True, startup_input="close-cw",
                                   startup_flash=graphics, stock_mmu=True, startup_from_nor=True, nor_snapshot=nor,
                                   nor_missing_secondary=missing_secondary,
                                   cw_image=metadata, cw_rx_ready=True, cw_canvas_audit="stock" if metadata else None,
                                   cw_rx_record_gate=record_gate, cw_rx_closed_sql=closed_sql,
                                   cw_rx_audio=audio("CQ", trim_leading=True)+bytes(3204) if metadata else None)
    ui = control["eeprom"]["format_record"]["handoff"]["ui"]
    surfaces = ui["display"]["openvg"]["surfaces"]
    panel = surfaces["startup_resume"]["main_loop_resume"]["startup_input"]
    require(len(previews) == (10 if metadata else 8) and previews[5] != previews[6] and
            previews[5] == previews[-1] and panel["menu_committed"] and panel["exit_committed"] and
            (panel["frequency_hz"], panel["mode"], panel["stock_menu"], panel["persistent_writes"]) ==
            (7_030_000, "CW", "KEYER", 0), "stock control, HOME or EXIT did not survive")
    return dict(snapshot_sha256=digest(nor), nor_boot=control["nor_boot"], panel=panel), previews


def reject_corrupt(path):
    with TemporaryDirectory() as directory:
        bad = Path(directory)/path.name
        with ZipFile(path) as original, ZipFile(bad, "x") as modified:
            for name in original.namelist():
                data = original.read(name)
                if name == "main":
                    data = bytes((data[0]^1,))+data[1:]
                modified.writestr(name, data)
        try:
            load_image(bad)
        except ValueError as error:
            require(str(error) == "invalid digest: main", f"unexpected package rejection: {error}")
            return str(error)
    raise ValueError("PC loader accepted a package that failed its content check")


def stage(nor, image, stock):
    main, large, graphics, _, small = image
    require((large, graphics, small) == (stock[1], stock[2], stock[4]), "PC package changed stock resources")
    relative = SECOND-GRAPHICS_FLASH
    encoded = with_pc_main(graphics, main)
    stored, = unpack_from("<I", encoded, relative)
    span = ((8+stored+SECTOR-1)//SECTOR)*SECTOR
    require(A_PREFIX+span <= SELECTOR, "PC program would cross into the selection record")
    payload = encoded[relative:relative+8+stored].ljust(span, b"\xff")
    for sector in range(A_PREFIX, A_PREFIX+span, SECTOR):
        nor[sector:sector+SECTOR] = b"\xff"*SECTOR
        for page in range(sector, sector+SECTOR, PAGE):
            begin = page-A_PREFIX
            nor[page:page+PAGE] = payload[begin:begin+PAGE]
    require(nor[A_PREFIX:A_PREFIX+span] == payload, "virtual NOR readback differs from staged program")
    return span


def stock_power_key_choices(nor, stock, pc_image):
    stage(nor, pc_image, stock)
    marker = nor[0x47E8:0x47F8]
    cases = []
    for default, tag in ((FIRST, b"\xff"*16), (SECOND, marker)):
        nor[SELECTOR:SELECTOR+16] = tag
        snapshot = bytes(nor)
        for hold in (0, 1, 0x4DFFF, 0x4E000):
            observed = boot_from_nor(machine(), b"", stock[0], snapshot=snapshot, power_key_probe=hold)
            require(observed["source_slot"] == hex(default), "stock power key changed the selected slot")
            cases.append(dict(snapshot_sha256=digest(snapshot), b_unreadable=False, **observed))
        for hold in (1, 0x4E000):
            observed = boot_from_nor(machine(), b"", stock[0], snapshot=snapshot, missing_main=True,
                                     power_key_probe=hold)
            require(observed["source_slot"] == hex(default) and
                    ("unreadable_address" in observed) == (default == SECOND),
                    "fault result disagreed with the selected slot")
            cases.append(dict(snapshot_sha256=digest(snapshot), b_unreadable=True, **observed))
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock_dat", type=Path)
    parser.add_argument("cw_image", type=Path)
    parser.add_argument("output", type=Path, help="new directory for JSON and LCD evidence only")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--rollback-test", action="store_true", help="make the virtual B header unreadable and boot A")
    modes.add_argument("--stock-power-key", action="store_true", help="observe original startup slot choice with key input")
    args = parser.parse_args()
    require(not args.output.exists(), "evidence directory already exists")
    dat, image_sha = args.stock_dat.read_bytes(), digest(args.cw_image.read_bytes())
    stock = load(dat)
    _, group_a = load_a(dat, stock[3])
    nor = bytearray(b"\xff"*NOR_BYTES)
    nor[:A_PREFIX] = group_a[:A_PREFIX]
    nor[A_PREFIX:SELECTOR] = group_a[BOOT_SIZE:A_PREFIX]
    nor[SHARED:SHARED+len(group_a)-A_PREFIX] = group_a[A_PREFIX:]
    if args.stock_power_key:
        pc_image, _ = load_image(args.cw_image)
        cases = stock_power_key_choices(nor, stock, pc_image)
        require(args.stock_dat.read_bytes() == dat and digest(args.cw_image.read_bytes()) == image_sha,
                "original input files changed")
        report = dict(scope="Original stock bootstrap, key poll counts and synthetic unreadable B; no physical timing",
                      stock_dat_sha256=digest(dat), pc_package_sha256=image_sha, cases=cases)
        args.output.mkdir(parents=True)
        (args.output/"evidence.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
        print(f"{len(cases)} original startup power-key trials: {args.output}")
        return
    baseline = bytes(nor)
    print("Cold booting the original Japanese 1.40 from virtual NOR.", flush=True)
    before, old_frames = boot(baseline, stock)
    require(before["nor_boot"]["source_slot"] == hex(FIRST) and "cw_frame" not in before["panel"],
            "baseline did not run the unchanged stock application from its active slot")

    rejected = reject_corrupt(args.cw_image)
    require(nor == baseline, "rejected package changed virtual NOR")
    pc_image, metadata = load_image(args.cw_image)
    require(metadata["stock_main_sha256"] == before["nor_boot"]["application_sha256"],
            "PC package does not match the running stock version")
    span = stage(nor, pc_image, stock)
    require(nor[:A_PREFIX] == baseline[:A_PREFIX] and nor[A_PREFIX+span:] == baseline[A_PREFIX+span:] and
            nor[A_PREFIX:A_PREFIX+span] != baseline[A_PREFIX:A_PREFIX+span],
            "staging changed the active slot or changed bytes outside the inactive program")
    print("Verified staged bytes; exercising reset before the PC installer commits.", flush=True)
    staged = bytes(nor)
    interrupted = boot_from_nor(machine(), stock[2], stock[0], snapshot=staged)
    require(interrupted["source_slot"] == hex(FIRST) and interrupted["application_sha256"] == stock[3],
            "uncommitted install did not restart the stock application")

    marker = baseline[0x47E8:0x47F8]
    require(nor[SELECTOR:SELECTOR+16] == b"\xff"*16, "expected unused virtual selection record")
    nor[SELECTOR:SELECTOR+16] = marker
    require(nor[:SELECTOR] == staged[:SELECTOR] and nor[SELECTOR+16:] == staged[SELECTOR+16:],
            "activation changed more than the selection record")
    print("PC installer committed; cold booting from the same updated virtual NOR.", flush=True)
    after, new_frames = boot(bytes(nor), pc_image, metadata)
    rx = after["panel"]["cw_receive"]
    require(after["nor_boot"]["source_slot"] == hex(SECOND) and
            after["nor_boot"]["application_sha256"] == pc_image[3] != stock[3] and
            rx["shown_text"] == "CQ" and not after["panel"]["cw_packaged_boot"]["host_attachment"] and
            old_frames[5] == new_frames[5], "upgraded application, CW reception or original HOME did not match")

    frames = dict(stock_home=old_frames[5], stock_menu=old_frames[6], cw_home=new_frames[5],
                  cw_decoded=new_frames[8], cw_exit=new_frames[-1])
    evidence = dict(scope="PC installer; original NOR bootstrap, application and LCD; no stock SD installer or hardware",
                    stock_dat_sha256=digest(dat), pc_package_sha256=image_sha,
                    before=before, rejected_package=rejected, precommit_reset=interrupted,
                    staged_snapshot_sha256=digest(staged), staged_bytes=span, activated_marker_bytes=len(marker),
                    original_slot_unchanged=True, home_equal_before_after_and_exit=True, after=after)
    if args.rollback_test:
        print("CW control passed. Blocking only the virtual B header page and reselecting A.", flush=True)
        failed = boot_from_nor(machine(), b"", pc_image[0], snapshot=bytes(nor), missing_main=True)
        require(failed["application_ram_still_empty"] and failed["unreadable_address"] == hex(SECOND+4),
                "B fault was not observed before application startup")
        nor[SELECTOR:SELECTOR+16] = baseline[SELECTOR:SELECTOR+16]
        require(nor == staged, "reselection changed bytes other than the virtual selector")
        recovered, recovered_frames = boot(bytes(nor), stock, missing_secondary=True)
        require(recovered["nor_boot"]["source_slot"] == hex(FIRST) and
                recovered["nor_boot"]["application_sha256"] == stock[3] and
                recovered_frames[5:8] == old_frames[5:8], "recovered stock app or HOME / KEYER / EXIT frames differ")
        frames.update(rollback_home=recovered_frames[5], rollback_menu=recovered_frames[6])
        evidence["rollback"] = dict(scope="host selected A in virtual NOR; no power-key slot switch",
                                    b_header_page_unreadable_in_both_reboots=True, b_fault=failed,
                                    a_return=recovered, only_selector_bytes_differ=True,
                                    home_menu_exit_frames_match_stock=True)
    require(args.stock_dat.read_bytes() == dat and digest(args.cw_image.read_bytes()) == image_sha,
            "original input files changed")
    evidence["frames"] = {name: digest(data) for name, data in frames.items()}
    args.output.mkdir(parents=True)
    for name, data in frames.items():
        (args.output/f"{name}.png").write_bytes(data)
    (args.output/"evidence.json").write_text(json.dumps(evidence, indent=2)+"\n", encoding="utf-8")
    print(f"Stock to CW passed on one virtual NOR: {args.output}")


if __name__ == "__main__":
    main()
