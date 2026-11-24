"""The scan: pure functions that turn tasks plus a clock into findings.

Three flags exist:

  waiting_human  the task is parked until a person answers
  blocked        the task cannot move for a non human reason
  idle           the task claims to be moving (or queued) but nothing has
                 touched it for longer than the threshold

Nothing here reads the database or the wall clock, so every rule can be
tested with plain values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping, Optional

from .db import STATES, Task

FLAGS = ("waiting_human", "blocked", "idle")
SEVERITIES = ("alert", "warn")

ENV_NAMES = {
    "idle_hours": "STALL_IDLE_HOURS",
    "queued_hours": "STALL_QUEUED_HOURS",
    "blocked_alert_hours": "STALL_BLOCKED_ALERT_HOURS",
    "human_alert_hours": "STALL_HUMAN_ALERT_HOURS",
}


@dataclass(frozen=True)
class Thresholds:
    idle_hours: float = 6.0            # in_progress with no move for this long is idle
    queued_hours: float = 24.0         # queued and never picked up for this long is idle
    blocked_alert_hours: float = 8.0   # blocked this long escalates from warn to alert
    human_alert_hours: float = 4.0     # waiting on a human this long escalates to alert

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Thresholds":
        values = {}
        for field, name in ENV_NAMES.items():
            raw = (env.get(name) or "").strip()
            if not raw:
                continue
            try:
                number = float(raw)
            except ValueError as exc:
                raise ValueError(f"{name} must be a number of hours, got {raw!r}") from exc
            if number <= 0:
                raise ValueError(f"{name} must be greater than zero, got {raw!r}")
            values[field] = number
        return cls(**values)


@dataclass(frozen=True)
class Finding:
    task: Task
    flag: str
    severity: str
    age_hours: float
    reason: str


@dataclass(frozen=True)
class ScanResult:
    now: datetime
    tasks: tuple[Task, ...]
    findings: tuple[Finding, ...]

    @property
    def state_counts(self) -> dict[str, int]:
        counts = {state: 0 for state in STATES}
        for task in self.tasks:
            counts[task.state] += 1
        return counts

    @property
    def alerts(self) -> int:
        return sum(1 for f in self.findings if f.severity == "alert")

    @property
    def warns(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warn")

    def by_flag(self, flag: str) -> list[Finding]:
        return [f for f in self.findings if f.flag == flag]

    def finding_for(self, task_id: str) -> Optional[Finding]:
        for finding in self.findings:
            if finding.task.id == task_id:
                return finding
        return None

    def flagged_by_owner(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            owner = finding.task.owner or "(unowned)"
            counts[owner] = counts.get(owner, 0) + 1
        return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def age_hours(task: Task, now: datetime) -> float:
    """Hours since the task last moved. A clock that runs backwards gives 0."""
    return max(0.0, (now - task.last_moved_at).total_seconds() / 3600.0)


def format_age(hours: float) -> str:
    if hours < 1:
        return f"{int(hours * 60)}m"
    whole = int(hours)
    if whole < 48:
        return f"{whole}h"
    days, rest = divmod(whole, 24)
    return f"{days}d {rest}h" if rest else f"{days}d"


def check_task(task: Task, now: datetime, limits: Thresholds) -> Optional[Finding]:
    """Return the single finding for a task, or None if it is moving fine."""
    age = age_hours(task, now)
    shown = format_age(age)

    if task.state == "done":
        return None

    if task.state == "waiting_human":
        who = task.waiting_on or "an unnamed human"
        severity = "alert" if age >= limits.human_alert_hours else "warn"
        return Finding(task, "waiting_human", severity, age,
                       f"waiting on {who} for {shown}")

    if task.state == "blocked":
        what = task.waiting_on or "no blocker recorded"
        severity = "alert" if age >= limits.blocked_alert_hours else "warn"
        return Finding(task, "blocked", severity, age,
                       f"blocked for {shown}: {what}")

    if task.state == "in_progress" and age >= limits.idle_hours:
        severity = "alert" if age >= limits.idle_hours * 3 else "warn"
        return Finding(task, "idle", severity, age,
                       f"in progress but no move for {shown}")

    if task.state == "queued" and age >= limits.queued_hours:
        if task.owner:
            reason = f"queued for {shown}, never started"
        else:
            reason = f"queued for {shown} with no owner"
        return Finding(task, "idle", "warn", age, reason)

    return None


def scan(tasks: Iterable[Task], now: datetime,
         limits: Optional[Thresholds] = None) -> ScanResult:
    """Check every task. Findings come back worst first, then oldest first."""
    limits = limits or Thresholds()
    tasks = tuple(tasks)
    findings = [f for f in (check_task(t, now, limits) for t in tasks) if f]
    findings.sort(key=lambda f: (SEVERITIES.index(f.severity), -f.age_hours, f.task.id))
    return ScanResult(now=now, tasks=tasks, findings=tuple(findings))
