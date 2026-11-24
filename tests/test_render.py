import re

from stall_board.render import render_html, render_text
from stall_board.scan import scan
from stall_board.seed import seed


def seeded_result(board, now):
    seed(board, now)
    return scan(board.list_tasks(), now)


def test_text_summary_has_header_counts_and_sections(board, now):
    text = render_text(seeded_result(board, now))
    lines = text.splitlines()
    assert lines[0] == "STALL BOARD  2026-01-15 12:00 UTC"
    assert lines[1] == ("14 tasks: 3 queued, 4 in_progress, 2 blocked, "
                        "3 waiting_human, 2 done")
    assert lines[2] == "Flagged: 9 (4 alert, 5 warn)"
    assert "WAITING ON A HUMAN (3)" in text
    assert "BLOCKED (2)" in text
    assert "IDLE (4)" in text
    assert "Moving fine: 3 of 12 open tasks" in text
    assert "waiting on bookkeeper for 26h" in text


def test_text_sections_come_in_priority_order(board, now):
    text = render_text(seeded_result(board, now))
    assert text.index("WAITING ON A HUMAN") < text.index("BLOCKED (") < text.index("IDLE (")


def test_text_summary_for_a_healthy_board(board, now):
    board.add_task("T-1", "Fresh work", owner="agent-a", state="in_progress", now=now)
    text = render_text(scan(board.list_tasks(), now))
    assert "Nothing is stalled" in text
    assert "Flagged: 0 (0 alert, 0 warn)" in text


def test_text_summary_for_an_empty_board(board, now):
    text = render_text(scan(board.list_tasks(), now))
    assert text.startswith("STALL BOARD")
    assert "0 tasks" in text


def test_html_has_one_column_per_state_and_a_card_per_task(board, now):
    html = render_html(seeded_result(board, now))
    assert html.startswith("<!doctype html>")
    assert re.findall(r'data-state="(\w+)"', html) == [
        "queued", "in_progress", "blocked", "waiting_human", "done"]
    assert len(re.findall(r'data-task="', html)) == 14
    assert html.count('class="card alert"') == 4
    assert html.count('class="card warn"') == 5
    assert html.count('class="card ok"') == 3


def test_html_is_self_contained(board, now):
    html = render_html(seeded_result(board, now))
    assert "<script" not in html
    assert "http://" not in html and "https://" not in html


def test_html_escapes_task_text(board, now):
    board.add_task("T-x", "<script>alert(1)</script>", owner='a"b<c',
                   state="blocked", waiting_on="<img src=x>", now=now)
    html = render_html(scan(board.list_tasks(), now), title="A & B")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img src=x>" not in html
    assert "<title>A &amp; B</title>" in html


def test_html_for_an_empty_board(board, now):
    html = render_html(scan(board.list_tasks(), now))
    assert "Nothing is stalled." in html
    assert html.count("Empty") == 5
