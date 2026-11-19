"""Compare the common flash region of verified Japanese IC-705 releases with J140."""

from hashlib import sha256
import json
from pathlib import Path

from tools.decode_705_main import BOOT_SIZE, checked_group_a, decode_a_range, decode_boot


SHARED_IN_DECODED_A = 0x600000  # Verified by the original virtual NOR writer.
ROOT = Path(__file__).resolve().parents[1]


def read_release(record):
    dat = (ROOT / "firmware" / (record["name"] + ".dat")).read_bytes()
    layout, group = checked_group_a(dat)
    if layout["sha256"] != record["dat_sha256"] or layout["bytes"] != record["dat_bytes"]:
        raise ValueError(f"official source digest or length differs: {record['name']}")
    boot, _ = decode_boot(dat, group)
    start = group["offset"] + BOOT_SIZE
    body = bytes(decode_a_range(dat, start, group["end_exclusive"] - start, boot[-1]))
    if len(boot) + len(body) != 0x9C0000:
        raise ValueError(f"unverified A-group layout: {record['name']}")
    groups = {entry["name"]: entry["sha256"] for entry in layout["groups"]}
    return boot, body[SHARED_IN_DECODED_A-BOOT_SIZE:], groups


def main():
    records = json.loads((ROOT / "research" / "705j-provenance.json").read_bytes())
    baseline = next(record for record in records if record["name"] == "705J140")
    ref_boot, ref_shared, ref_groups = read_release(baseline)
    rows = []
    for record in records:
        boot, shared, groups = read_release(record) if record != baseline else (ref_boot, ref_shared, ref_groups)
        different_sectors = [
            i // BOOT_SIZE for i in range(0, len(shared), BOOT_SIZE)
            if shared[i:i+BOOT_SIZE] != ref_shared[i:i+BOOT_SIZE]
        ]
        rows.append(dict(name=record["name"], dat_sha256=record["dat_sha256"], same_bootstrap=boot == ref_boot,
                         shared_sha256=sha256(shared).hexdigest(), different_shared_sectors=different_sectors,
                         changed_package_groups=[name for name in groups if groups[name] != ref_groups[name]]))
    print(json.dumps(dict(baseline=baseline["name"], shared_bytes=len(ref_shared), sector_bytes=BOOT_SIZE,
                          rows=rows), indent=2))


if __name__ == "__main__":
    main()
