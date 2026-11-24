from datetime import datetime, timezone

import pytest

from stall_board.db import Board

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def board():
    with Board(":memory:") as b:
        yield b


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("STALL_BOARD_DB", "STALL_BOARD_NOW", "STALL_IDLE_HOURS",
                 "STALL_QUEUED_HOURS", "STALL_BLOCKED_ALERT_HOURS",
                 "STALL_HUMAN_ALERT_HOURS"):
        monkeypatch.delenv(name, raising=False)
