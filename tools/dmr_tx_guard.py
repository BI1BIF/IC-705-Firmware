"""Install a receive-only guard at the IC-705 J140/E140 common TX request filter."""
from pathlib import Path
import struct
import subprocess
import tempfile

BASE=0x20005000
FILTER={"J":0x2010a820,"E":0x2010a904}
MAX_BYTES=128

def install_guard(main, region, origin, active_address):
    """Patch a bytearray in place. origin reserves 128 bytes of writable resident
    ARM RAM backed by main. active_address is a resident, initially zero u8."""
    entry=FILTER[region]
    start=origin-BASE
    expected=struct.pack("<4I",0xe92d4ff8,0xe59f04c8,0xe1d000b4,0xe3a0100a)
    if main[entry-BASE:entry-BASE+len(expected)]!=expected:
        raise ValueError("Unexpected stock TX filter entry")
    if origin%4 or not 0<=start<=len(main)-MAX_BYTES:
        raise ValueError("TX guard needs 128 aligned bytes inside the loaded main image")
    if origin<=active_address<origin+MAX_BYTES or not 0x20000000<=active_address<0x20a00000:
        raise ValueError("TX guard enable flag must be a separate resident RAM byte")
    with tempfile.TemporaryDirectory() as temp:
        output=Path(temp)/"guard"
        source=Path(__file__).resolve().parents[1]/"samples/dmr-tx-guard.S"
        subprocess.run(["arm-none-eabi-gcc","-c","-mcpu=cortex-a9","-marm",
                        f"-DDMR_RX_ENABLE={active_address}",f"-DDMR_FILTER_RESUME={entry+4}",
                        source,"-o",output.with_suffix(".o")],check=True)
        subprocess.run(["arm-none-eabi-objcopy","-O","binary","-j",".text",
                        output.with_suffix(".o"),output.with_suffix(".bin")],check=True)
        stub=output.with_suffix(".bin").read_bytes()
    if len(stub)>MAX_BYTES:
        raise ValueError("TX guard exceeds the reserved space")
    offset=(origin-entry-8)//4
    if not -(1<<23)<=offset<(1<<23):
        raise ValueError("TX guard outside ARM branch range")
    main[start:start+len(stub)]=stub
    struct.pack_into("<I",main,entry-BASE,0xea000000|(offset&0xffffff))
    return {"site":entry,"origin":origin,"size":len(stub),"active":active_address}
