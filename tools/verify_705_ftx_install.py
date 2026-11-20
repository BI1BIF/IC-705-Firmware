"""Verify that the original updater installs the FT resources and application together."""

import json
from hashlib import sha256

from tools.build_705_ftx_rx import OUT, ROOT
from tools.decode_705_main import BOOT_SIZE, decode_main
from tools.emulate_705 import machine
from tools.probe_705_boot_selection import FIRST, NOR_BYTES
from tools.replay_705_nor_boot import boot_from_nor
from tools.replay_705_stock_install import A_PREFIX, SELECTOR, SHARED, load_a, update_a


def unpack(dat):
    main = bytes(decode_main(dat)[1])
    return load_a(dat, sha256(main).hexdigest())


if __name__ == "__main__":
    dat = (OUT / "bench-rx.dat").read_bytes()
    previous = (OUT.parent / "j140-ftx-tx2i/bench-rx.dat").read_bytes()
    main, target = unpack(dat)
    prior, old = unpack(previous)
    _, stock = unpack((ROOT / "firmware/705J140.dat").read_bytes())
    initial = bytearray(b"\xff" * NOR_BYTES)
    initial[:A_PREFIX] = stock[:A_PREFIX]
    initial[A_PREFIX:SELECTOR] = old[BOOT_SIZE:A_PREFIX]
    initial[SELECTOR : SELECTOR + 16] = stock[0x47E8:0x47F8]
    initial[SHARED : SHARED + len(stock) - A_PREFIX] = stock[A_PREFIX:]
    written, _ = update_a(prior, dat, bytes(initial), prior=previous, active_second=True)
    expected = initial.copy()
    expected[BOOT_SIZE:A_PREFIX] = target[BOOT_SIZE:A_PREFIX]
    expected[SELECTOR : SELECTOR + 16] = b"\xff" * 16
    assert written == expected
    boot = boot_from_nor(machine(), None, main, snapshot=written)
    assert int(boot["source_slot"], 16) == FIRST
    result = {
        "dat_sha256": sha256(dat).hexdigest(),
        "prior_sha256": sha256(previous).hexdigest(),
        "complete_nor_matches": True,
        "booted_slot": boot["source_slot"],
        "app_sha256": boot["application_sha256"],
    }
    (OUT / "installed.json").write_text(json.dumps(result, indent=2))
