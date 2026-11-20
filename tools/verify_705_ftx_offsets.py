"""Compare off-bin FT8 CQ and directed reports with timing offsets in both RAM modes."""

import json
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256

from tools.verify_705_ftx_weak import OUT, run

if __name__ == "__main__":
    gen = ["ft8sim"] if shutil.which("ft8sim") else ["wsl", "-e", "ft8sim"]
    paths, expected = [], []
    for i, (msg, hz, dt, snr) in enumerate(
        [
            ("CQ JA1ABC PM95", 1403, 0.27, -17),
            ("DL1ABC K1ABC R-12", 833, -0.23, -15),
            ("CQ F4ABC JN18", 2267, 0.42, -18),
            ("K1ABC DL1ABC RR73", 1791, -0.38, -18),
        ]
    ):
        dest = OUT / "offsets" / str(i)
        dest.mkdir(parents=True, exist_ok=True)
        if len(list(dest.glob("*.wav"))) != 3:
            subprocess.run(
                [*gen, msg, str(hz), str(dt), "0", "0", "3", str(snr)],
                cwd=dest,
                check=True,
                stdout=subprocess.DEVNULL,
            )
        paths.extend(sorted(dest.glob("*.wav")))
        expected.extend([msg] * 3)
    assert len(paths) == 12
    result = {
        "samples": [
            {
                "file": str(path.relative_to(OUT)),
                "sha256": sha256(path.read_bytes()).hexdigest(),
                "expected": msg,
            }
            for path, msg in zip(paths, expected)
        ]
    }
    with ProcessPoolExecutor(max_workers=4) as pool:
        jobs = {
            name: pool.submit(run, folder, paths, False, limit)
            for name, folder, limit in [
                ("rx4", OUT.parent / "j140-ftx-rx4", None),
                ("rx4_compact", OUT.parent / "j140-ftx-rx4", 210000),
                ("tx1", OUT, None),
                ("tx1_compact", OUT, 210000),
            ]
        }
        for name, job in jobs.items():
            report = job.result()
            found = []
            for i, msg in enumerate(expected):
                rows = report["messages"][i]
                assert not set(rows) - {msg}, (i, rows)
                found.append(msg in rows)
            result[name] = {"decoded": found, "dat_sha256": report["dat_sha256"]}
            print(name, sum(found), flush=True)
    result["dat_sha256"] = result["tx1"]["dat_sha256"]
    (OUT / "offsets.json").write_text(json.dumps(result, indent=2))
