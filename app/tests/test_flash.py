"""Tests of the flasher with a fake avrdude and a fake port list.

No hardware, no avrdude binary: the runner, the port scanner, the sleeper,
and the 1200-baud touch are all injected.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from loadcraft import flash
from loadcraft.flash import FlashError

PORT_BOARD = {"device": "/dev/ttyACM0", "usb": True, "vid": 0x2341, "pid": 0x8036}
PORT_BOOTLOADER = {"device": "/dev/ttyACM1", "usb": True, "vid": 0x2341, "pid": 0x0043}


def ok_log() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout="Writing flash: 18112 bytes written, verified.",
        stderr="",
    )


def fail_log() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=1,
        stdout="avrdude: no device in expected position",
        stderr="",
    )


def run_flash(list_ports_fn, runner, touch=lambda port: None):
    return flash.flash(
        "/dev/ttyACM0",
        avrdude="/fake/avrdude",
        hexfile="/fake/handbrake.hex",
        list_ports_fn=list_ports_fn,
        runner=runner,
        sleeper=lambda s: None,
        touch=touch,
    )


# --- flash() -----------------------------------------------------------------


def test_flash_success_on_the_same_port():
    touched = []
    log = run_flash(
        lambda: [PORT_BOARD],
        lambda cmd: ok_log(),
        touch=lambda port: touched.append(port),
    )
    assert "verified" in log
    assert touched == ["/dev/ttyACM0"]


def test_flash_command_uses_avr11_and_flash_w():
    cmds = []
    run_flash(lambda: [PORT_BOARD],
              lambda cmd: (cmds.append(list(cmd)), ok_log())[1])
    cmd = cmds[0]
    assert cmd[0] == "/fake/avrdude"
    assert cmd[cmd.index("-p") + 1] == "m32u4"
    assert cmd[cmd.index("-c") + 1] == "avr11"
    assert cmd[cmd.index("-P") + 1] == "/dev/ttyACM0"
    assert cmd[-1] == "flash:w:/fake/handbrake.hex"


def test_flash_falls_back_to_the_new_bootloader_port():
    state = {"touched": False}

    def runner(cmd):
        port = cmd[cmd.index("-P") + 1]
        return ok_log() if port == "/dev/ttyACM1" else fail_log()

    def ports():
        if state["touched"]:
            return [PORT_BOARD, PORT_BOOTLOADER]
        return [PORT_BOARD]

    log = run_flash(ports, runner,
                    touch=lambda port: state.__setitem__("touched", True))
    assert "verified" in log


def test_flash_no_candidate_raises():
    with pytest.raises(FlashError):
        run_flash(lambda: [], lambda cmd: ok_log())


def test_flash_all_candidates_fail_raises_with_log():
    with pytest.raises(FlashError) as excinfo:
        run_flash(lambda: [PORT_BOARD, PORT_BOOTLOADER], lambda cmd: fail_log())
    assert "no device in expected position" in str(excinfo.value)


# --- Path resolution -----------------------------------------------------------


def test_avrdude_path_prefers_the_bundled_binary(tmp_path, monkeypatch):
    avrdude_dir = tmp_path / "loadcraft" / "data" / "avrdude"
    avrdude_dir.mkdir(parents=True)
    bundled = avrdude_dir / ("avrdude.exe" if os.name == "nt" else "avrdude")
    bundled.write_text("fake")
    monkeypatch.setattr(flash, "_data_dir", lambda: tmp_path / "loadcraft" / "data")
    assert flash.avrdude_path() == str(bundled)


def test_avrdude_path_falls_back_to_the_system(tmp_path, monkeypatch):
    monkeypatch.setattr(flash, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(flash.shutil, "which", lambda name: "/usr/bin/avrdude")
    assert flash.avrdude_path() == "/usr/bin/avrdude"


def test_avrdude_path_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(flash, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(flash.shutil, "which", lambda name: None)
    with pytest.raises(FlashError):
        flash.avrdude_path()


def test_hex_path_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(flash, "_data_dir", lambda: tmp_path)
    with pytest.raises(FlashError):
        flash.hex_path()


# --- Single-flight ---------------------------------------------------------------


def test_flasher_rejects_a_concurrent_flash():
    import threading

    release = threading.Event()

    def blocking_flash(port):
        release.wait(timeout=5.0)
        return "log"

    flasher = flash.Flasher(flash_fn=blocking_flash)
    first = threading.Thread(target=flasher.run, args=("/dev/ttyACM0",))
    first.start()
    try:
        with pytest.raises(FlashError, match="in progress"):
            flasher.run("/dev/ttyACM0")
    finally:
        release.set()
        first.join()


def test_flasher_reports_busy_while_running():
    import threading

    release = threading.Event()
    flasher = flash.Flasher(flash_fn=lambda port: release.wait(timeout=5.0) or "log")
    first = threading.Thread(target=flasher.run, args=("/dev/ttyACM0",))
    first.start()
    try:
        assert flasher.busy is True
    finally:
        release.set()
        first.join()
    assert flasher.busy is False
