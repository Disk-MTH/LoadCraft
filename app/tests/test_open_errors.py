"""Tests of the port open error messages.

Each failure cause has a known fix. Returning it raw
("[Errno 13] Permission denied") leaves the user hunting for what the
program already knows. These tests keep those messages from being lost.
"""

from __future__ import annotations

import errno

import pytest

from handbrake_tuner.link import _open_failure_hint


class FakeSerialException(OSError):
    """Reproduces the shape of pyserial's exceptions.

    SerialException derives from OSError and is built with (errno, message),
    so `isinstance(exc, PermissionError)` is False: only `.errno` can tell
    the cases apart.
    """

    def __init__(self, code: int, message: str):
        super().__init__(code, message)


def test_permission_denied_mentions_dialout(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    message = _open_failure_hint(
        "/dev/ttyACM0",
        FakeSerialException(errno.EACCES, "could not open port"),
    )
    assert "dialout" in message
    assert "usermod" in message


def test_permission_denied_warns_about_already_running_apps(monkeypatch):
    """This is the real trap: adding the group is not enough, an
    application started before it keeps its old credentials."""
    monkeypatch.setattr("sys.platform", "linux")
    message = _open_failure_hint(
        "/dev/ttyACM0", FakeSerialException(errno.EACCES, "denied")
    )
    assert "restarted" in message


def test_permission_denied_off_linux(monkeypatch):
    """The "dialout" advice makes no sense on Windows."""
    monkeypatch.setattr("sys.platform", "win32")
    message = _open_failure_hint(
        "COM3", FakeSerialException(errno.EACCES, "denied")
    )
    assert "dialout" not in message
    assert "COM3" in message


def test_port_busy():
    message = _open_failure_hint(
        "/dev/ttyACM0", FakeSerialException(errno.EBUSY, "busy")
    )
    assert "another program" in message


def test_port_missing():
    message = _open_failure_hint(
        "/dev/ttyACM0", FakeSerialException(errno.ENOENT, "no such file")
    )
    assert "does not exist" in message


def test_unknown_cause_stays_readable():
    """With no identified cause, the original error must remain visible
    rather than being replaced by a vague message."""
    message = _open_failure_hint("/dev/ttyACM0", RuntimeError("boom"))
    assert "boom" in message
    assert "/dev/ttyACM0" in message


@pytest.mark.parametrize(
    "code",
    [errno.EACCES, errno.EBUSY, errno.ENOENT, errno.EIO, None],
)
def test_the_port_is_always_named(code):
    exc = FakeSerialException(code, "error") if code else RuntimeError("error")
    assert "/dev/ttyACM0" in _open_failure_hint("/dev/ttyACM0", exc)
