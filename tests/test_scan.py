from datetime import timedelta

import pytest

from stall_board.db import Task
from stall_board.scan import Thresholds, check_task, format_age, scan
from stall_board.seed import seed


def make(now, state, hours_ago, owner="agent-a", waiting_on=None, task_id="T-1"):
    moved = now - timedelta(hours=hours_ago)
    return Task(id=task_id, title="Some task", owner=owner, state=state,
                waiting_on=waiting_on, note=None, created_at=moved, last_moved_at=moved)


LIMITS = Thresholds()  # idle 6h, queued 24h, blocked alert 8h, human alert 4h


def test_done_tasks_are_never_flagged(now):
    assert check_task(make(now, "done", 500), now, LIMITS) is None


def test_fresh_in_progress_is_fine(now):
    assert check_task(make(now, "in_progress", 5.9), now, LIMITS) is None


def test_in_progress_goes_idle_at_the_threshold(now):
    finding = check_task(make(now, "in_progress", 6), now, LIMITS)
    assert (finding.flag, finding.severity) == ("idle", "warn")
    assert "no move for 6h" in finding.reason


def test_in_progress_idle_escalates_at_three_times_the_threshold(now):
    assert check_task(make(now, "in_progress", 17.9), now, LIMITS).severity == "warn"
    assert check_task(make(now, "in_progress", 18), now, LIMITS).severity == "alert"


def test_waiting_human_is_always_flagged_and_names_who(now):
    fresh = check_task(make(now, "waiting_human", 0.2, waiting_on="ops lead"), now, LIMITS)
    assert (fresh.flag, fresh.severity) == ("waiting_human", "warn")
    assert "ops lead" in fresh.reason
    stale = check_task(make(now, "waiting_human", 4, waiting_on="ops lead"), now, LIMITS)
    assert stale.severity == "alert"


def test_waiting_human_without_a_name_says_so(now):
    finding = check_task(make(now, "waiting_human", 1), now, LIMITS)
    assert "unnamed human" in finding.reason


def test_blocked_is_always_flagged_and_escalates(now):
    fresh = check_task(make(now, "blocked", 1, waiting_on="API down"), now, LIMITS)
    assert (fresh.flag, fresh.severity) == ("blocked", "warn")
    assert "API down" in fresh.reason
    assert check_task(make(now, "blocked", 8), now, LIMITS).severity == "alert"


def test_queued_only_flags_after_the_queue_threshold(now):
    assert check_task(make(now, "queued", 23), now, LIMITS) is None
    owned = check_task(make(now, "queued", 24), now, LIMITS)
    assert (owned.flag, owned.severity) == ("idle", "warn")
    assert "never started" in owned.reason
    unowned = check_task(make(now, "queued", 30, owner=None), now, LIMITS)
    assert "no owner" in unowned.reason


def test_clock_skew_does_not_produce_negative_ages(now):
    future = make(now, "blocked", -3)
    assert check_task(future, now, LIMITS).age_hours == 0


def test_findings_sort_alerts_first_then_oldest(now):
    tasks = [
        make(now, "blocked", 1, task_id="warn-young"),
        make(now, "in_progress", 7, task_id="warn-old"),
        make(now, "waiting_human", 5, task_id="alert-young"),
        make(now, "blocked", 40, task_id="alert-old"),
        make(now, "in_progress", 1, task_id="fine"),
    ]
    result = scan(tasks, now, LIMITS)
    assert [f.task.id for f in result.findings] == [
        "alert-old", "alert-young", "warn-old", "warn-young"]
    assert (result.alerts, result.warns) == (2, 2)
    assert result.finding_for("fine") is None


def test_custom_thresholds_change_the_verdict(now):
    task = make(now, "in_progress", 2)
    assert check_task(task, now, LIMITS) is None
    assert check_task(task, now, Thresholds(idle_hours=1)).flag == "idle"


def test_thresholds_from_env():
    limits = Thresholds.from_env({"STALL_IDLE_HOURS": "2.5", "STALL_HUMAN_ALERT_HOURS": " 1 "})
    assert limits.idle_hours == 2.5
    assert limits.human_alert_hours == 1
    assert limits.queued_hours == 24  # untouched default
    assert Thresholds.from_env({"STALL_IDLE_HOURS": ""}) == Thresholds()


@pytest.mark.parametrize("bad", ["soon", "0", "-4"])
def test_thresholds_from_env_rejects_bad_values(bad):
    with pytest.raises(ValueError, match="STALL_IDLE_HOURS"):
        Thresholds.from_env({"STALL_IDLE_HOURS": bad})


@pytest.mark.parametrize("hours,expected", [
    (0.5, "30m"), (1, "1h"), (47.9, "47h"), (48, "2d"), (52, "2d 4h")])
def test_format_age(hours, expected):
    assert format_age(hours) == expected


def test_seeded_board_has_the_expected_mix(board, now):
    assert seed(board, now) == 14
    result = scan(board.list_tasks(), now, LIMITS)
    flagged = {f.task.id: (f.flag, f.severity) for f in result.findings}
    assert flagged == {
        "T-103": ("idle", "warn"),
        "T-104": ("idle", "alert"),
        "T-105": ("waiting_human", "warn"),
        "T-106": ("waiting_human", "alert"),
        "T-107": ("waiting_human", "alert"),
        "T-108": ("blocked", "warn"),
        "T-109": ("blocked", "alert"),
        "T-111": ("idle", "warn"),
        "T-112": ("idle", "warn"),
    }
    assert result.state_counts == {
        "queued": 3, "in_progress": 4, "blocked": 2, "waiting_human": 3, "done": 2}
    assert result.flagged_by_owner()["(unowned)"] == 1


def test_seeding_twice_replaces_rather_than_duplicates(board, now):
    seed(board, now)
    seed(board, now)
    assert len(board.list_tasks()) == 14


@pytest.mark.parametrize("state,flag", [("waiting_human", "waiting_human"),
                                        ("blocked", "blocked")])
def test_heartbeat_does_not_reset_time_parked(board, now, state, flag):
    start = now - timedelta(hours=30)
    board.add_task("T-1", "Parked", state=state, waiting_on="ops lead", now=start)
    board.move_task("T-1", state, now=now - timedelta(minutes=5))   # agent checks in
    finding = scan(board.list_tasks(), now).finding_for("T-1")
    assert (finding.flag, finding.severity) == (flag, "alert")
    assert finding.age_hours == 30
    assert "for 30h" in finding.reason


def test_heartbeat_still_clears_idle(board, now):
    board.add_task("T-1", "Working", state="in_progress", now=now - timedelta(hours=30))
    assert scan(board.list_tasks(), now).finding_for("T-1").severity == "alert"
    board.move_task("T-1", "in_progress", now=now)
    assert scan(board.list_tasks(), now).finding_for("T-1") is None


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf"])
def test_thresholds_from_env_rejects_non_finite_values(bad):
    with pytest.raises(ValueError):
        Thresholds.from_env({"STALL_IDLE_HOURS": bad})
