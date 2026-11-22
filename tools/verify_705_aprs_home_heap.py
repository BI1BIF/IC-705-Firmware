"""Measure the enhanced image's native heap at the first confirmed HOME frame."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from struct import pack, unpack_from

from tools.decode_705_main import decode_main
from tools.emulate_705 import RAM, RAM_BYTES, arm, call, machine, uc
from tools.probe_705_canvas_heap import CanvasAudit
from tools.render_705_stock_row import FONT_HEADER, SMALL_FONT_HEADER
from tools.replay_705_stock_install import A_PREFIX, load_a
from tools.replay_705_font_boot import replay_resource_task
from tools.verify_705_aprs_resident import REGIONS

def budget(cpu, allocator, region):
    from tools.build_705_cw_sim import PICKER_TABLE, PICKER_ID, PICKER_STRIDE, PICKER_REFERENCES
    from tools.build_705_ftx_rx import MENU
    def blocks(c):
        return CanvasAudit(c, stock=False).free_list()

    before = blocks(cpu)
    ram = bytes(cpu.mem_read(RAM, RAM_BYTES))
    results = {}
    for label, requests in (
        ("sstv", [153631, 153600]),
        ("history_and_sstv", [21760, 153631, 153600]),
        ("resident_aprs_and_sstv", [65536,21760,153631,153600]),
        # Counterfactual: 58 full frames in another owned region, six on heap.
        # This tests only the remaining heap budget, not ownership of that region.
        ("six_history_slots_on_heap_and_sstv", [6*340,153631,153600]),
    ):
        c = machine()
        c.mem_write(RAM, ram)
        obtained = []
        for size in requests:
            pointer = call(c, allocator, size)
            obtained.append(dict(request=size, pointer=hex(pointer)))
            if not pointer:
                break
        remaining = blocks(c)
        results[label] = dict(requests=obtained, success=len(obtained)==len(requests) and bool(pointer),
                              remaining=sum(n for _,n in remaining))
    source = PICKER_TABLE + (224 if region == "E" else 0)
    refs = [a+(228 if region=="E" else 0) for a in PICKER_REFERENCES]
    assert all(unpack_from("<I",ram,ref-RAM)[0] == MENU for ref in refs)
    size = PICKER_ID * PICKER_STRIDE
    original = ram[source-RAM:source-RAM+size]
    live = ram[MENU-RAM:MENU-RAM+size]
    # Measure an alternative layout in a disposable copy of the HOME RAM.
    # This does not grant ownership of the boot table in a flashable build.
    assert size//340 == 58
    c = machine()
    c.mem_write(RAM,ram)
    records = b"".join(pack("<I",i)+bytes((i,))*336 for i in range(64))
    split = 58*340
    c.mem_write(source,records[:split])
    tail = call(c,allocator,len(records)-split)
    assert tail
    c.mem_write(tail,records[split:])
    for n in (153631,153600):
        addr = call(c,allocator,n)
        assert addr
        c.mem_write(addr,b"\xa5"*n)
    assert bytes(c.mem_read(source,split))+bytes(c.mem_read(tail,len(records)-split)) == records
    assert bytes(c.mem_read(MENU,size)) == live
    return dict(free_bytes=sum(n for _,n in before), largest_block=max(n for _,n in before),
                blocks=[[hex(a),n] for a,n in before], allocation_trials=results,
                proposed_history_layout=dict(boot_table=hex(source),live_table=hex(MENU),
                    differing_bytes_at_home=sum(a!=b for a,b in zip(original,live)),boot_table_bytes=size,
                    history_prefix_bytes=split,history_tail_bytes=len(records)-split,
                    all_64_patterns_preserved=True,live_table_preserved=True,source_reuse_in_firmware_verified=False))

def run(region, combined_base=False, check_source=False):
    folder = ".analysis/aprs-integration-base" if combined_base else ".analysis/ft-key-style"
    root = Path(folder if combined_base else ".analysis/aprs-home-heap")/region
    root.mkdir(parents=True, exist_ok=True)
    dat = (Path(folder)/region/f"705{region}140.dat").read_bytes()
    expected = (json.loads((root/"evidence.json").read_text())["sha256"] if combined_base else REGIONS[region])
    assert sha256(dat).hexdigest() == expected
    main, flash = load_a(dat,sha256(decode_main(dat)[1]).hexdigest())
    def font(at):
        count, = unpack_from("<I",flash,at)
        return flash[at+4:at+4+count]

    class Captured(Exception):
        pass

    reads = []
    def observe(cpu, frame_hash):
        result = budget(cpu,0x202d3a19+(224 if region=="E" else 0),region)
        result.update(dat_sha256=expected,frame_sha256=frame_hash,mode="CW",frequency_hz=7030000)
        (root/"home.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
        print(region, result["free_bytes"], result["largest_block"], flush=True)
        if not check_source:
            raise Captured()
        proposal = result["proposed_history_layout"]
        dest = int(proposal["boot_table"],16)
        length = proposal["history_prefix_bytes"]
        # This is a RAM-only negative control. Exercise actual CPU stores
        # under the cold boot's MMU, then watch the old source during MENU/EXIT.
        source = 0x20006000
        expected_bytes = bytes(cpu.mem_read(source,length))
        assert expected_bytes != bytes(cpu.mem_read(dest,length))
        ctx = cpu.context_save()
        resume = cpu.reg_read(arm.UC_ARM_REG_PC)
        try:
            for reg,arg in ((arm.UC_ARM_REG_R0,source),(arm.UC_ARM_REG_R1,dest),
                            (arm.UC_ARM_REG_R2,length),(arm.UC_ARM_REG_LR,resume)):
                cpu.reg_write(reg,arg)
            cpu.emu_start(0x200052ed,resume,count=100000)
            assert cpu.reg_read(arm.UC_ARM_REG_PC) == resume and bytes(cpu.mem_read(dest,length)) == expected_bytes
        finally:
            cpu.context_restore(ctx)
        def record(c, access, address, size, _value, _data):
            reads.append((access,hex(c.reg_read(arm.UC_ARM_REG_PC)),hex(address),size))
        cpu.hook_add(uc.UC_HOOK_MEM_READ|uc.UC_HOOK_MEM_WRITE,record,begin=dest,end=dest+length-1)

    if region == "E":
        from tools.replay_705_e140_home_heap import european_boot_replay
        replay = european_boot_replay()
    else:
        replay = replay_resource_task
    try:
        details = replay(main,font(A_PREFIX),font(A_PREFIX+SMALL_FONT_HEADER-FONT_HEADER),
            fixture_return=False,loader=flash[0x4000:0x49bc],adc_sample=0x180,scif_wait="board_power",
            vbus_high=True,power_key_released=False,riic0_idle=True,riic0_finish="stop",
            eeprom=b"\xff"*16,startup_dma="format-current",startup_home_probe=True,no_power_on_check=True,
            startup_input="close-cw",startup_flash=flash[:A_PREFIX],stock_mmu=True,startup_from_nor=True,
            home_observer=observe)
    except Captured:
        return
    if check_source:
        ui = details["eeprom"]["format_record"]["handoff"]["ui"]
        panel = ui["display"]["openvg"]["surfaces"]["startup_resume"]["main_loop_resume"]["startup_input"]
        assert panel["menu_committed"] and panel["exit_committed"] and not reads, reads[:10]
        (root/"menu-source.json").write_text(json.dumps(dict(dat_sha256=expected,
            prefix_bytes_written_under_stock_mmu=58*340,reads_or_writes_during_menu_exit=reads,
            menu_committed=True,exit_committed=True),indent=2)+"\n",encoding="utf-8")
        return
    (root/"boot-trace.json").write_text(json.dumps(details,indent=2,default=str),encoding="utf-8")
    raise ValueError("HOME frame not observed; inspect boot-trace.json")

if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("region",choices=REGIONS)
    parser.add_argument("--combined-base",action="store_true")
    parser.add_argument("--check-source",action="store_true")
    args=parser.parse_args()
    run(args.region,args.combined_base,args.check_source)
