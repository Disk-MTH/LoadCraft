"""CLI flag tests (the browser/webview themselves are not tested here)."""

from __future__ import annotations

import pytest

from loadcraft.__main__ import build_parser


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
