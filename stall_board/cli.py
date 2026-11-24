"""Command line entry point: python -m stall_board <command>."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from .db import STATES, Board, BoardError, parse_ts, utcnow
from .render import render_html, render_text
from .scan import Thresholds, age_hours, format_age, scan
from .seed import seed

DEFAULT_DB = "stall_board.db"


def _now(args: argparse.Namespace) -> datetime:
    """Clock for this run: --now, then STALL_BOARD_NOW, then the wall clock."""
    raw = args.now or os.environ.get("STALL_BOARD_NOW", "").strip()
    return parse_ts(raw) if raw else utcnow()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stall_board",
        description="Work in flight board for a fleet of agents.",
    )
    parser.add_argument("--db", default=None,
                        help=f"SQLite file (default: $STALL_BOARD_DB or {DEFAULT_DB})")
    parser.add_argument("--now", default=None,
                        help="pretend the clock reads this ISO 8601 time (for repeatable runs)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("seed", help="replace all tasks with the fake demo set")

    add = sub.add_parser("add", help="add a task")
    add.add_argument("id")
    add.add_argument("title")
    add.add_argument("--owner")
    add.add_argument("--state", default="queued", choices=STATES)
    add.add_argument("--waiting-on")
    add.add_argument("--note")

    move = sub.add_parser("move", help="change a task's state (same state = heartbeat)")
    move.add_argument("id")
    move.add_argument("state", choices=STATES)
    move.add_argument("--owner")
    move.add_argument("--waiting-on")
    move.add_argument("--note")

    sub.add_parser("list", help="list every task, oldest move first")

    scan_cmd = sub.add_parser("scan", help="print the text summary")
    scan_cmd.add_argument("--fail-on", choices=("alert", "any"), default=None,
                          help="exit 1 when alerts (or any flags) exist, for cron and CI")

    board = sub.add_parser("board", help="write the static HTML board")
    board.add_argument("--out", default="board.html")
    board.add_argument("--title", default="Stall board")
    return parser


def run(args: argparse.Namespace, out) -> int:
    db_path = args.db or os.environ.get("STALL_BOARD_DB", "").strip() or DEFAULT_DB
    now = _now(args)
    limits = Thresholds.from_env(os.environ)

    with Board(db_path) as board:
        if args.command == "seed":
            count = seed(board, now)
            print(f"Seeded {count} fake tasks.", file=out)
            return 0

        if args.command == "add":
            task = board.add_task(args.id, args.title, owner=args.owner, state=args.state,
                                  waiting_on=args.waiting_on, note=args.note, now=now)
            print(f"Added {task.id} [{task.state}] {task.title}", file=out)
            return 0

        if args.command == "move":
            before = board.get_task(args.id)
            task = board.move_task(args.id, args.state, waiting_on=args.waiting_on,
                                   note=args.note, owner=args.owner, now=now)
            print(f"Moved {task.id}: {before.state} -> {task.state}", file=out)
            return 0

        if args.command == "list":
            for task in board.list_tasks():
                print(f"{task.id:<6} {task.state:<14} {(task.owner or '(unowned)'):<16} "
                      f"{format_age(age_hours(task, now)):>7}  {task.title}", file=out)
            return 0

        result = scan(board.list_tasks(), now, limits)

        if args.command == "scan":
            out.write(render_text(result))
            if args.fail_on == "alert" and result.alerts:
                return 1
            if args.fail_on == "any" and result.findings:
                return 1
            return 0

        if args.command == "board":
            target = Path(args.out)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Write bytes so the file has LF endings on every platform.
            target.write_bytes(render_html(result, title=args.title).encode("utf-8"))
            print(f"Wrote {target.as_posix()} ({len(result.tasks)} tasks, "
                  f"{len(result.findings)} flagged)", file=out)
            return 0

    return 2  # unreachable: argparse rejects unknown commands


def main(argv: Optional[Sequence[str]] = None, out=None) -> int:
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    try:
        return run(args, out)
    except (BoardError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
