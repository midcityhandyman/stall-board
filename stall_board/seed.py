"""Fake tasks for the demo and tests. Everything here is invented.

Each row is placed a number of hours before "now", so the same seed
always produces the same mix of healthy, idle, blocked and waiting work.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .db import Board

# (id, title, owner, state, hours since last move, waiting_on, note)
SEED_TASKS = [
    ("T-101", "Reply to new lead from web form (Sample Customer A)",
     "agent-intake", "in_progress", 0.5, None, "drafting first reply"),
    ("T-102", "Build quote for deck repair (Sample Customer B)",
     "agent-quotes", "in_progress", 2, None, "pricing materials"),
    ("T-103", "Reconcile last week's card receipts",
     "agent-ledger", "in_progress", 9, None, "stopped after batch 3 of 7"),
    ("T-104", "Send review request batch for closed jobs",
     "agent-outreach", "in_progress", 31, None, "no heartbeat since yesterday"),
    ("T-105", "Reschedule Thursday crew after cancellation",
     "agent-scheduler", "waiting_human", 1.5, "field supervisor",
     "two slot options offered"),
    ("T-106", "Approve refund above the auto limit (Sample Customer C)",
     "agent-ledger", "waiting_human", 26, "bookkeeper",
     "needs sign off, amount over limit"),
    ("T-107", "Confirm scope change before sending revised quote",
     "agent-quotes", "waiting_human", 7, "ops lead",
     "customer asked to add a second room"),
    ("T-108", "Sync calendar holds to the job tracker",
     "agent-scheduler", "blocked", 3, "tracker API returning 503",
     "retry scheduled"),
    ("T-109", "Import supplier price sheet",
     "agent-quotes", "blocked", 52, "file arrived as a scanned image",
     "needs a readable copy"),
    ("T-110", "Draft weekly numbers summary",
     "agent-ledger", "queued", 5, None, None),
    ("T-111", "Clean duplicate contacts in the CRM",
     None, "queued", 70, None, "nobody picked this up"),
    ("T-112", "Follow up on unanswered quote (Sample Customer D)",
     "agent-outreach", "queued", 30, None, None),
    ("T-113", "Post job photos to the shared album",
     "agent-outreach", "done", 4, None, "12 photos posted"),
    ("T-114", "Send appointment reminders for tomorrow",
     "agent-scheduler", "done", 20, None, "9 reminders sent"),
]


def seed(board: Board, now: datetime, reset: bool = True) -> int:
    """Load the fake tasks. Returns how many were written."""
    if reset:
        board.clear()
    for task_id, title, owner, state, hours_ago, waiting_on, note in SEED_TASKS:
        moved = now - timedelta(hours=hours_ago)
        if state == "queued":
            # A queued task has not moved since it was created.
            board.add_task(task_id, title, owner=owner, note=note, now=moved)
            continue
        board.add_task(task_id, title, owner=owner, now=moved - timedelta(hours=2))
        board.move_task(task_id, state, waiting_on=waiting_on, note=note, now=moved)
    return len(SEED_TASKS)
