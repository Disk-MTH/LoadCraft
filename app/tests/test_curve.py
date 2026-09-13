"""Host-side curve tests.

They reuse the properties verified in tests/test_hb_core.c. The preview
shown in the app must match what the board computes, otherwise the tuning
is done on a curve that is not the one driving the axis.
"""

import pytest

from handbrake_tuner import protocol

CURVES = protocol.CURVES
GAMMAS = [0.2, 0.5, 1.0, 2.0, 4.0]


def test_linear():
    assert protocol.apply_curve("LINEAR", 1.0, 0.37) == pytest.approx(0.37)
    # gamma is ignored for LINEAR
    assert protocol.apply_curve("LINEAR", 3.0, 0.5) == pytest.approx(0.5)


def test_power():
    assert protocol.apply_curve("POWER", 2.0, 0.5) == pytest.approx(0.25)
    assert protocol.apply_curve("POWER", 0.5, 0.25) == pytest.approx(0.5)


def test_s_curve_fixed_points():
    for gamma in GAMMAS:
        assert protocol.apply_curve("SCURVE", gamma, 0.0) == pytest.approx(0.0)
        assert protocol.apply_curve("SCURVE", gamma, 0.5) == pytest.approx(0.5)
        assert protocol.apply_curve("SCURVE", gamma, 1.0) == pytest.approx(1.0)


def test_s_curve_symmetric():
    for gamma in GAMMAS:
        for t in (0.1, 0.3, 0.45):
            total = protocol.apply_curve("SCURVE", gamma, t) + protocol.apply_curve(
                "SCURVE", gamma, 1.0 - t
            )
            assert total == pytest.approx(1.0)


def test_s_curve_gamma_direction():
    # gamma > 1: soft at the extremes, so below the diagonal before 0.5
    assert protocol.apply_curve("SCURVE", 2.0, 0.25) < 0.25
    assert protocol.apply_curve("SCURVE", 2.0, 0.75) > 0.75
    # gamma < 1: the opposite behavior
    assert protocol.apply_curve("SCURVE", 0.5, 0.25) > 0.25
    assert protocol.apply_curve("SCURVE", 0.5, 0.75) < 0.75


@pytest.mark.parametrize("curve", CURVES)
def test_gamma_one_neutralizes_the_curves(curve):
    """gamma = 1 makes the three curves identical: it is the neutral
    reference announced to the user in the app."""
    for i in range(11):
        t = i / 10
        assert protocol.apply_curve(curve, 1.0, t) == pytest.approx(t, abs=1e-9)


@pytest.mark.parametrize("curve", CURVES)
@pytest.mark.parametrize("gamma", GAMMAS)
def test_monotone_and_bounded(curve, gamma):
    previous = -1.0
    for i in range(101):
        value = protocol.apply_curve(curve, gamma, i / 100)
        assert 0.0 <= value <= 1.0
        assert value >= previous - 1e-9
        previous = value


@pytest.mark.parametrize("curve", CURVES)
def test_input_bounded(curve):
    assert protocol.apply_curve(curve, 2.0, -1.0) == pytest.approx(0.0)
    assert protocol.apply_curve(curve, 2.0, 5.0) == pytest.approx(1.0)


def test_unknown_curve_falls_back_to_linear():
    assert protocol.apply_curve("PARABOLE", 2.0, 0.42) == pytest.approx(0.42)


def test_out_of_range_gamma_is_clamped():
    """apply_curve applies the same bounds as the firmware, otherwise the
    preview would show a curve the board would refuse to apply."""
    assert protocol.apply_curve("POWER", 99.0, 0.5) == pytest.approx(
        0.5**protocol.GAMMA_MAX
    )
    assert protocol.apply_curve("POWER", float("nan"), 0.5) == pytest.approx(0.5)


def test_curve_points():
    points = protocol.curve_points("LINEAR", 1.0, count=5)
    assert len(points) == 5
    assert points[0] == [0.0, 0.0]
    assert points[-1] == [1.0, 1.0]


def test_curve_points_clamps_the_point_count():
    assert len(protocol.curve_points("LINEAR", 1.0, count=0)) == 2
    assert len(protocol.curve_points("LINEAR", 1.0, count=99999)) == 512
