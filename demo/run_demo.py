"""Offline demo: seed a board, scan it, unstick two tasks, scan again.

Run from the repo root:  python demo/run_demo.py
The clock is pinned so the output is the same on every run.
Writes demo/board.html; demo/output.txt is this script's captured stdout.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stall_board.cli import main  # noqa: E402

DEMO_DIR = ROOT / "demo"
DB = DEMO_DIR / "demo.db"
T0 = "2026-01-15T12:00:00Z"
T1 = "2026-01-15T13:00:00Z"


def step(label: str, *argv: str, now: str = T0) -> int:
    shown = " ".join(f'"{a}"' if " " in a else a for a in argv)
    print(f"\n=== {label}")
    print(f"$ python -m stall_board --now {now} {shown}")
    sys.stdout.flush()
    return main(["--db", str(DB), "--now", now, *argv])


def run() -> int:
    if DB.exists():
        DB.unlink()
    print("stall-board demo (all data is fake, clock pinned, no network)")

    step("1. Load 14 fake tasks", "seed")
    step("2. Everything on the board, oldest move first", "list")
    code = step("3. Scan: who is idle, blocked or waiting on a human?",
                "scan", "--fail-on", "alert")
    print(f"(exit code {code}: alerts exist, so a cron wrapper would notify)")

    step("4. One hour later: the bookkeeper approves the refund",
         "move", "T-106", "in_progress", "--note", "refund approved", now=T1)
    step("5. The stalled review batch sends a heartbeat",
         "move", "T-104", "in_progress", "--note", "resumed at batch 4", now=T1)
    step("6. Scan again: both flags are gone, the rest aged by an hour",
         "scan", now=T1)

    # Relative path so the captured output has no machine specific text.
    out = (DEMO_DIR / "board.html").relative_to(ROOT).as_posix()
    os.chdir(ROOT)
    step("7. Write the static HTML board", "board", "--out", out, now=T1)

    DB.unlink()
    print("\nDone. Open demo/board.html in a browser.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
