"""Shared fixtures."""

from __future__ import annotations

import pytest

from loadcraft.link import SerialLink

from fake_board import FakeBoard


@pytest.fixture
def board() -> FakeBoard:
    return FakeBoard()


@pytest.fixture
def link(board: FakeBoard):
    connection = SerialLink(board, port="/dev/fake0")
    connection.start()
    yield connection
    connection.close()


@pytest.fixture
def available():
    """The USB port list the link manager scans: one handbrake board."""
    return [
        {
            "device": "/dev/fake0",
            "description": "Arduino Leonardo [2341:8036]",
            "hwid": "USB VID:PID=2341:8036",
            "usb": True,
            "vid": 0x2341,
            "pid": 0x8036,
        }
    ]


@pytest.fixture
def clock():
    """A fake monotonic clock: call it to advance and get the new time.

    Drives the link manager deterministically, without threads or sleeps.
    """
    state = {"now": 100.0}

    def tick(seconds: float = 0.5) -> float:
        state["now"] += seconds
        return state["now"]

    return tick
