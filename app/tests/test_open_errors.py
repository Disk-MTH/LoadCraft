"""Tests des messages d'erreur à l'ouverture du port.

Chaque cause d'échec a une correction connue. La renvoyer brute
(« [Errno 13] Permission denied ») laisse chercher ce que le programme sait
déjà — d'où ces messages, et ces tests pour qu'ils ne se perdent pas.
"""

from __future__ import annotations

import errno

import pytest

from handbrake_tuner.link import _open_failure_hint


class FakeSerialException(OSError):
    """Reproduit la forme des exceptions de pyserial.

    SerialException dérive d'OSError et est construite avec (errno, message),
    donc `isinstance(exc, PermissionError)` est faux : seul `.errno` permet
    de distinguer les cas.
    """

    def __init__(self, code: int, message: str):
        super().__init__(code, message)


def test_permission_refusee_mentionne_dialout(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    message = _open_failure_hint(
        "/dev/ttyACM0",
        FakeSerialException(errno.EACCES, "could not open port"),
    )
    assert "dialout" in message
    assert "usermod" in message


def test_permission_refusee_signale_les_applications_deja_ouvertes(monkeypatch):
    """C'est le piège réel : ajouter le groupe ne suffit pas, une application
    lancée avant garde ses anciennes credentials."""
    monkeypatch.setattr("sys.platform", "linux")
    message = _open_failure_hint(
        "/dev/ttyACM0", FakeSerialException(errno.EACCES, "denied")
    )
    assert "relancée" in message


def test_permission_refusee_hors_linux(monkeypatch):
    """Le conseil « dialout » n'a aucun sens sous Windows."""
    monkeypatch.setattr("sys.platform", "win32")
    message = _open_failure_hint(
        "COM3", FakeSerialException(errno.EACCES, "denied")
    )
    assert "dialout" not in message
    assert "COM3" in message


def test_port_occupe():
    message = _open_failure_hint(
        "/dev/ttyACM0", FakeSerialException(errno.EBUSY, "busy")
    )
    assert "autre programme" in message


def test_port_absent():
    message = _open_failure_hint(
        "/dev/ttyACM0", FakeSerialException(errno.ENOENT, "no such file")
    )
    assert "n'existe pas" in message


def test_cause_inconnue_reste_lisible():
    """Sans cause identifiée, l'erreur d'origine doit rester visible plutôt
    que d'être remplacée par un message vague."""
    message = _open_failure_hint("/dev/ttyACM0", RuntimeError("boum"))
    assert "boum" in message
    assert "/dev/ttyACM0" in message


@pytest.mark.parametrize(
    "code",
    [errno.EACCES, errno.EBUSY, errno.ENOENT, errno.EIO, None],
)
def test_le_port_est_toujours_nomme(code):
    exc = FakeSerialException(code, "erreur") if code else RuntimeError("erreur")
    assert "/dev/ttyACM0" in _open_failure_hint("/dev/ttyACM0", exc)
