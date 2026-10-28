"""DEVELOPMENT ONLY, run by run.sh beside the bench add-on (docs/design.md, Against x.com): each tab's memory.

For each kitter-bench-memory-ready-*.json the add-on saves in FOLDER while this runs, it makes Zen dump its
memory reports with signal 34, which Zen handles (tried on a throwaway instance of the same build first, Oct 27,
2026), and sums each named tab's explicit memory in two parts: the page (`window-objects/top(<address>, id=N)`:
DOM, layout and the page's own JS, x.com's app included) and its content scripts, which Firefox reports apart as
`js-non-window/.../realm([Expanded Principal [<address>, moz-extension:...` (kitter's client and its wasm, and
every add-on's scripts, the same in both tabs). Ends after ROUNDS dumps and writes their medians and every round
to kitter-bench-memory-<time>.json in FOLDER.

usage: memory.py FOLDER ZEN_PID [ROUNDS]   # Zen's downloads folder and main process; 3 rounds, as MEMORY_ROUNDS
"""

import gzip
import json
import os
import re
import signal
import statistics
import sys
import time
from pathlib import Path

DOWNLOADS, PID = Path(sys.argv[1]), int(sys.argv[2])
ROUNDS = int(sys.argv[3]) if len(sys.argv) > 3 else 3
PAGE = re.compile(r"explicit/window-objects/top\((.*?), id=\d+\)/")
SCRIPTS = re.compile(r"explicit/js-non-window/zones/zone\([^)]*\)/realm\(\[Expanded Principal \[(.*?), moz-extension:")


def dump(pid: int) -> dict:
    """A fresh unified memory report of every Zen process, from the folder Zen writes temporary files to."""
    environment = dict(e.split(b"=", 1) for e in (Path("/proc") / str(pid) / "environ").read_bytes().split(b"\0") if b"=" in e)
    folder = Path(environment.get(b"TMPDIR", b"/tmp").decode())
    before = set(folder.glob("unified-memory-report-*.json.gz"))
    os.kill(pid, signal.SIGRTMIN)  # 34: Firefox's "dump memory reports" signal on Linux
    for _ in range(240):
        time.sleep(0.5)
        if new := set(folder.glob("unified-memory-report-*.json.gz")) - before:
            path = new.pop()
            size = -1
            while size != (size := path.stat().st_size):  # Zen may still be writing it
                time.sleep(0.5)
            report = json.loads(gzip.decompress(path.read_bytes()))
            path.unlink()
            return report
    raise SystemExit(f"no memory report in {folder} within 120 s")


def tabs(report: dict, addresses: dict[str, str]) -> dict[str, dict[str, float]]:
    """Each named tab's page and content-script memory in MB. Memory paths write a URL's slashes as backslashes."""
    size = {app: {"page": 0.0, "scripts": 0.0} for app in addresses}
    for entry in report["reports"]:
        if entry["units"] != 0:
            continue  # counts and percentages, not bytes
        for part, pattern in (("page", PAGE), ("scripts", SCRIPTS)):
            if found := pattern.match(entry["path"]):
                for app, address in addresses.items():
                    size[app][part] += entry["amount"] / 2**20 if found[1].replace("\\", "/") == address else 0
    return {
        app: {**{k: round(v, 1) for k, v in s.items()}, "total": round(s["page"] + s["scripts"], 1)} for app, s in size.items()
    }


def main() -> None:
    seen = set(DOWNLOADS.glob("kitter-bench-memory-ready-*.json"))
    rounds: list[dict[str, dict[str, float]]] = []
    while len(rounds) < ROUNDS:
        time.sleep(1)
        for ready in sorted(set(DOWNLOADS.glob("kitter-bench-memory-ready-*.json")) - seen):
            seen.add(ready)
            named = json.loads(ready.read_text())
            measured = tabs(dump(PID), named["urls"])
            print(f"round {named['round']}: {measured}", flush=True)
            rounds.append(measured)
            ready.unlink()
    medians = {app: {part: statistics.median(r[app][part] for r in rounds) for part in rounds[0][app]} for app in rounds[0]}
    out = DOWNLOADS / f"kitter-bench-memory-{int(time.time() * 1000)}.json"
    out.write_text(json.dumps({"unit": "MB of explicit memory per tab", "medians": medians, "rounds": rounds}, indent=2))
    print(f"medians {medians}, saved {out}")


main()
