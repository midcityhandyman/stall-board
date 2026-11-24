import io

import pytest

from stall_board.cli import main

NOW = "2026-01-15T12:00:00Z"


def run(db, *argv, now=NOW):
    out = io.StringIO()
    code = main(["--db", str(db), "--now", now, *argv], out=out)
    return code, out.getvalue()


@pytest.fixture
def db(tmp_path):
    return tmp_path / "board.db"


def test_seed_then_scan(db):
    assert run(db, "seed") == (0, "Seeded 14 fake tasks.\n")
    code, text = run(db, "scan")
    assert code == 0
    assert "Flagged: 9 (4 alert, 5 warn)" in text


def test_scan_fail_on_sets_the_exit_code(db):
    run(db, "add", "T-1", "Fresh work", "--state", "in_progress", "--owner", "agent-a")
    assert run(db, "scan", "--fail-on", "any")[0] == 0
    run(db, "add", "T-2", "Stuck", "--state", "blocked", "--waiting-on", "API down")
    assert run(db, "scan", "--fail-on", "alert")[0] == 0   # blocked 0h is only a warn
    assert run(db, "scan", "--fail-on", "any")[0] == 1
    assert run(db, "scan", "--fail-on", "alert", now="2026-01-16T12:00:00Z")[0] == 1


def test_move_clears_a_flag(db):
    run(db, "seed")
    code, text = run(db, "move", "T-106", "in_progress", "--note", "refund approved")
    assert (code, text) == (0, "Moved T-106: waiting_human -> in_progress\n")
    _, summary = run(db, "scan")
    assert "T-106" not in summary
    assert "Flagged: 8 (3 alert, 5 warn)" in summary


def test_list_shows_every_task(db):
    run(db, "seed")
    code, text = run(db, "list")
    assert code == 0
    assert len(text.splitlines()) == 14
    assert text.splitlines()[0].startswith("T-111")  # oldest move first


def test_board_writes_html(db, tmp_path):
    run(db, "seed")
    target = tmp_path / "out" / "board.html"
    code, text = run(db, "board", "--out", str(target), "--title", "Fleet")
    assert code == 0
    assert "14 tasks, 9 flagged" in text
    html = target.read_text(encoding="utf-8")
    assert "<title>Fleet</title>" in html


def test_bad_input_exits_2_with_a_message(db, capsys):
    assert run(db, "move", "T-404", "done")[0] == 2
    assert "no task" in capsys.readouterr().err
    assert run(db, "list", now="not a time")[0] == 2


def test_env_supplies_db_clock_and_thresholds(tmp_path, monkeypatch):
    monkeypatch.setenv("STALL_BOARD_DB", str(tmp_path / "env.db"))
    monkeypatch.setenv("STALL_BOARD_NOW", NOW)
    out = io.StringIO()
    assert main(["seed"], out=out) == 0
    assert (tmp_path / "env.db").exists()

    monkeypatch.setenv("STALL_IDLE_HOURS", "1")
    out = io.StringIO()
    main(["scan"], out=out)
    assert "T-102" in out.getvalue()   # 2h old, idle only under the tighter limit

    monkeypatch.setenv("STALL_IDLE_HOURS", "banana")
    assert main(["scan"], out=io.StringIO()) == 2
