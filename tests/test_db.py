from datetime import timedelta, timezone

import pytest

from stall_board.db import Board, BoardError, format_ts, parse_ts


def test_add_task_defaults_to_queued_and_logs_a_move(board, now):
    task = board.add_task("T-1", "Write the thing", owner="agent-a", now=now)
    assert task.state == "queued"
    assert task.owner == "agent-a"
    assert task.created_at == now
    assert task.last_moved_at == now
    moves = board.moves_for("T-1")
    assert [(m.from_state, m.to_state) for m in moves] == [(None, "queued")]


def test_duplicate_id_is_rejected(board, now):
    board.add_task("T-1", "One", now=now)
    with pytest.raises(BoardError, match="already exists"):
        board.add_task("T-1", "Two", now=now)


def test_blank_id_or_title_is_rejected(board, now):
    with pytest.raises(BoardError):
        board.add_task("  ", "Title", now=now)
    with pytest.raises(BoardError):
        board.add_task("T-1", "   ", now=now)


def test_unknown_state_is_rejected(board, now):
    with pytest.raises(BoardError, match="unknown state"):
        board.add_task("T-1", "One", state="paused", now=now)
    board.add_task("T-2", "Two", now=now)
    with pytest.raises(BoardError, match="unknown state"):
        board.move_task("T-2", "paused", now=now)


def test_move_updates_state_time_and_history(board, now):
    board.add_task("T-1", "One", owner="agent-a", now=now)
    later = now + timedelta(hours=3)
    task = board.move_task("T-1", "waiting_human", waiting_on="ops lead",
                           note="need a yes or no", now=later)
    assert task.state == "waiting_human"
    assert task.waiting_on == "ops lead"
    assert task.last_moved_at == later
    assert task.created_at == now
    moves = board.moves_for("T-1")
    assert [(m.from_state, m.to_state) for m in moves] == [
        (None, "queued"), ("queued", "waiting_human")]
    assert moves[-1].note == "need a yes or no"


def test_leaving_a_waiting_state_clears_waiting_on(board, now):
    board.add_task("T-1", "One", state="blocked", waiting_on="API down", now=now)
    task = board.move_task("T-1", "in_progress", now=now + timedelta(hours=1))
    assert task.waiting_on is None


def test_same_state_move_is_a_heartbeat_that_keeps_waiting_on(board, now):
    board.add_task("T-1", "One", state="waiting_human", waiting_on="bookkeeper", now=now)
    later = now + timedelta(hours=2)
    task = board.move_task("T-1", "waiting_human", now=later)
    assert task.last_moved_at == later
    assert task.waiting_on == "bookkeeper"


def test_move_unknown_task_raises(board, now):
    with pytest.raises(BoardError, match="no task"):
        board.move_task("T-404", "done", now=now)


def test_list_orders_oldest_move_first(board, now):
    board.add_task("T-new", "New", now=now)
    board.add_task("T-old", "Old", now=now - timedelta(hours=5))
    assert [t.id for t in board.list_tasks()] == ["T-old", "T-new"]


def test_data_survives_reopening_the_file(tmp_path, now):
    path = str(tmp_path / "board.db")
    with Board(path) as first:
        first.add_task("T-1", "Persist me", owner="agent-a", now=now)
    with Board(path) as second:
        assert second.get_task("T-1").title == "Persist me"


def test_timestamp_round_trip_and_naive_input():
    stamp = parse_ts("2026-01-15T07:00:00-05:00")
    assert stamp.tzinfo == timezone.utc
    assert format_ts(stamp) == "2026-01-15T12:00:00Z"
    assert parse_ts("2026-01-15T12:00:00Z") == stamp
    assert parse_ts("2026-01-15T12:00:00") == stamp
    with pytest.raises(BoardError):
        parse_ts("yesterday")
