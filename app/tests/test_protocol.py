"""Host-side protocol tests.

The expectations must stay aligned with tests/test_hb_protocol.c: it is the
only guard against a silent drift between the two implementations.
"""

import math

import pytest

from loadcraft import protocol
from loadcraft.protocol import Ack, Config, Err, Telemetry


# --- Reply parsing -----------------------------------------------------------


def test_parse_config():
    message = protocol.parse_line(
        "CFG min=12345 max=987654 curve=POWER gamma=1.800 alpha=0.750 "
        "calibrated=1"
    )
    assert message == Config(
        raw_min=12345, raw_max=987654, curve="POWER", gamma=1.8,
        alpha=0.75, calibrated=True,
    )


def test_parse_config_not_calibrated():
    message = protocol.parse_line(
        "CFG min=0 max=8000000 curve=LINEAR gamma=1.000 alpha=0.500 "
        "calibrated=0"
    )
    assert message.calibrated is False


def test_parse_config_negative_values():
    message = protocol.parse_line(
        "CFG min=-8388608 max=-1 curve=SCURVE gamma=5.000 alpha=1.000 "
        "calibrated=1"
    )
    assert message.raw_min == -8388608
    assert message.raw_max == -1
    assert message.alpha == 1.0


def test_parse_telemetry():
    assert protocol.parse_line("T raw=123456 out=0.750 axis=767") == Telemetry(
        raw=123456, out=0.75, axis=767
    )


def test_parse_ok_and_err():
    assert protocol.parse_line("OK SAVE") == Ack("SAVE")
    assert protocol.parse_line("OK SET MIN 1234") == Ack("SET MIN 1234")
    assert protocol.parse_line("ERR unknown command") == Err("unknown command")


@pytest.mark.parametrize(
    "line",
    [
        "",
        "   ",
        "noise",
        "CFG",
        "CFG min=abc max=1 curve=LINEAR gamma=1.0 alpha=0.5 calibrated=0",
        "CFG min=1 curve=LINEAR gamma=1.0 alpha=0.5 calibrated=0",  # missing max
        "CFG min=1 max=2 curve=PARABOLE gamma=1.0 alpha=0.5 calibrated=0",
        "CFG min=1 max=2 curve=LINEAR gamma=1.0 calibrated=0",  # missing alpha
        "T raw=1 out=x axis=2",
        "T raw=1",
    ],
)
def test_unreadable_lines_ignored(line):
    """The port emits stray bytes on open and during the board's restart:
    ignoring them is better than crashing the read thread."""
    assert protocol.parse_line(line) is None


# --- Command building ----------------------------------------------------------


def test_simple_commands():
    assert protocol.cmd_ping() == "PING"
    assert protocol.cmd_get() == "GET"
    assert protocol.cmd_save() == "SAVE"
    assert protocol.cmd_load() == "LOAD"
    assert protocol.cmd_reset() == "RESET"
    assert protocol.cmd_stream(True) == "STREAM 1"
    assert protocol.cmd_stream(False) == "STREAM 0"


def test_calibration_commands():
    assert protocol.cmd_set_min() == "SET MIN"
    assert protocol.cmd_set_max() == "SET MAX"
    assert protocol.cmd_set_min(1234) == "SET MIN 1234"
    assert protocol.cmd_set_max(-9876) == "SET MAX -9876"


def test_curve_commands():
    assert protocol.cmd_set_curve("POWER") == "SET CURVE POWER"
    assert protocol.cmd_set_curve("power") == "SET CURVE POWER"
    assert protocol.cmd_set_curve("SCURVE", 1.8) == "SET CURVE SCURVE 1.800"
    assert protocol.cmd_set_gamma(2.5) == "SET GAMMA 2.500"
    assert protocol.cmd_set_alpha(0.75) == "SET ALPHA 0.750"
    assert protocol.cmd_set_alpha(1.0) == "SET ALPHA 1.000"


def test_unknown_curve_rejected():
    with pytest.raises(ValueError):
        protocol.cmd_set_curve("PARABOLE")


def test_commands_readable_by_the_firmware():
    """Every command produced here must match the grammar tested in
    tests/test_hb_protocol.c."""
    commands = [
        protocol.cmd_ping(),
        protocol.cmd_get(),
        protocol.cmd_save(),
        protocol.cmd_load(),
        protocol.cmd_reset(),
        protocol.cmd_stream(True),
        protocol.cmd_set_min(),
        protocol.cmd_set_min(42),
        protocol.cmd_set_max(-42),
        protocol.cmd_set_curve("LINEAR"),
        protocol.cmd_set_curve("POWER", 1.5),
        protocol.cmd_set_gamma(0.5),
        protocol.cmd_set_alpha(0.5),
    ]
    for command in commands:
        assert "\n" not in command
        assert command == command.strip()
        assert len(command) < 64  # HB_LINE_MAX


# --- Gamma bounds ---------------------------------------------------------------


def test_clamp_gamma():
    assert protocol.clamp_gamma(1.0) == 1.0
    assert protocol.clamp_gamma(99.0) == protocol.GAMMA_MAX
    assert protocol.clamp_gamma(0.0) == protocol.GAMMA_MIN
    assert protocol.clamp_gamma(-5.0) == protocol.GAMMA_MIN
    assert protocol.clamp_gamma(float("nan")) == 1.0
    assert protocol.clamp_gamma("noise") == 1.0


def test_clamp_alpha():
    assert protocol.clamp_alpha(0.5) == 0.5
    assert protocol.clamp_alpha(2.0) == protocol.ALPHA_MAX
    assert protocol.clamp_alpha(0.0) == protocol.ALPHA_MIN
    assert protocol.clamp_alpha(-5.0) == protocol.ALPHA_MIN
    assert protocol.clamp_alpha(float("nan")) == protocol.ALPHA_DEFAULT
    assert protocol.clamp_alpha("noise") == protocol.ALPHA_DEFAULT


# --- Normalization --------------------------------------------------------------


def test_normalize():
    assert protocol.normalize(1500, 1000, 2000) == pytest.approx(0.5)
    assert protocol.normalize(500, 1000, 2000) == 0.0
    assert protocol.normalize(9999, 1000, 2000) == 1.0


def test_normalize_inverted_range():
    """Same behavior as hb_normalize: a cell wired with opposite polarity
    stays usable without an inversion option."""
    assert protocol.normalize(1500, 2000, 1000) == pytest.approx(0.5)
    assert protocol.normalize(1000, 2000, 1000) == 1.0
    assert protocol.normalize(2000, 2000, 1000) == 0.0


def test_normalize_zero_range():
    assert protocol.normalize(1000, 1000, 1000) == 0.0


def test_parse_telemetry_with_sensor_flag():
    message = protocol.parse_line("T raw=123456 out=0.750 axis=767 s=0")
    assert message == Telemetry(
        raw=123456, out=0.75, axis=767, sensor=False
    )


def test_parse_telemetry_sensor_defaults_to_present():
    """The field is optional on the wire: a board that predates it still
    parses, treated as having a valid sample."""
    message = protocol.parse_line("T raw=123456 out=0.750 axis=767")
    assert message.sensor is True


# --- Optional firmware version -------------------------------------------------

CFG_NO_VER = (
    "CFG min=100 max=900 curve=LINEAR gamma=1.000 alpha=0.500 calibrated=1"
)


def test_config_ver_parsed():
    msg = protocol.parse_line(CFG_NO_VER + " ver=1.0.0")
    assert msg.ver == "1.0.0"


def test_config_ver_absent_is_none():
    msg = protocol.parse_line(CFG_NO_VER)
    assert msg.ver is None


def test_config_as_dict_includes_ver():
    msg = protocol.parse_line(CFG_NO_VER + " ver=2.1.0")
    assert msg.as_dict()["ver"] == "2.1.0"


def test_config_unknown_fields_ignored():
    msg = protocol.parse_line(CFG_NO_VER + " ver=1.0.0 extra=42")
    assert msg is not None
    assert msg.ver == "1.0.0"
