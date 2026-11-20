"""Replay directed B-slot audio with the same early-decode policy used after a CQ."""
import json
import subprocess
from hashlib import sha256

from tools.verify_705_ftx_weak import OUT, run


def main():
    digest = sha256((OUT / "bench-rx.dat").read_bytes()).hexdigest()
    station = json.loads((OUT / "station.json").read_text())
    assert station["dat_sha256"] == digest
    folder = OUT / "reply-audio"
    folder.mkdir(exist_ok=True)
    peer = "K1ABC DL1ABC JO62"
    subprocess.run(["wsl", "-d", "Debian", "-e", "ft8sim", peer, "1200", "0", "0",
                    "0", "1", "-10"], cwd=folder, check=True, capture_output=True)
    ft8, = folder.glob("*.wav")
    result = {"dat_sha256": digest}
    for mode, recording, message in (
        ("FT8", ft8, peer),
        ("FT4", OUT / "FT4/261119_120000.wav", "JA1ABC K1ABC PM95"),
    ):
        replay = run(OUT, [None, recording], exchange=message, ft4=mode == "FT4")
        arrival = replay["first_reply_ms_from_next_edge"]
        assert arrival is not None and -1500 < arrival < 0, (mode, replay)
        result[mode] = dict(message=message, ms_before_next_slot=-arrival,
                            pcm_sha256=sha256(recording.read_bytes()).hexdigest())
    (OUT / "exchange.json").write_text(json.dumps(result, indent=2))
    print(result)


if __name__ == "__main__":
    main()
