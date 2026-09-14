"""CLI flag tests (the browser/webview themselves are not tested here)."""

from __future__ import annotations

import io

import pytest

from loadcraft.__main__ import _Tee, build_parser


def test_default_is_browser():
    args = build_parser().parse_args([])
    assert args.window is False
    assert args.no_window is False
    assert args.port == 0


def test_window_flag():
    args = build_parser().parse_args(["--window"])
    assert args.window is True
    assert args.no_window is False


def test_no_window_flag_with_port():
    args = build_parser().parse_args(["--no-window", "--port", "8123"])
    assert args.no_window is True
    assert args.port == 8123


def test_browser_flag_removed():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--browser"])


def test_tee_with_no_console():
    # Packaged GUI builds (PyInstaller --windowed) have sys.stdout/sys.stderr
    # set to None: a _Tee built from them must not crash and still logs.
    log = io.StringIO()
    tee = _Tee(None, log)
    tee.write("hello\n")
    tee.flush()
    assert log.getvalue() == "hello\n"


def test_tee_with_console():
    console = io.StringIO()
    log = io.StringIO()
    tee = _Tee(console, log)
    tee.write("hi")
    assert console.getvalue() == "hi"
    assert log.getvalue() == "hi"
