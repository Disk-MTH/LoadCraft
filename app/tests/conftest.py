"""Fixtures partagées."""

from __future__ import annotations

import pytest

from handbrake_tuner.link import SerialLink

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
