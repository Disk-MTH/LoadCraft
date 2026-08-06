"""Tests des courbes côté hôte.

Reprennent les propriétés vérifiées dans tests/test_hb_core.c. L'aperçu
affiché dans l'app doit correspondre à ce que la carte calcule, sinon le
réglage se fait sur une courbe qui n'est pas celle qui pilotera l'axe.
"""

import pytest

from handbrake_tuner import protocol

CURVES = protocol.CURVES
GAMMAS = [0.2, 0.5, 1.0, 2.0, 4.0]


def test_lineaire():
    assert protocol.apply_curve("LINEAR", 1.0, 0.37) == pytest.approx(0.37)
    # gamma est ignoré en linéaire
    assert protocol.apply_curve("LINEAR", 3.0, 0.5) == pytest.approx(0.5)


def test_puissance():
    assert protocol.apply_curve("POWER", 2.0, 0.5) == pytest.approx(0.25)
    assert protocol.apply_curve("POWER", 0.5, 0.25) == pytest.approx(0.5)


def test_courbe_en_s_points_fixes():
    for gamma in GAMMAS:
        assert protocol.apply_curve("SCURVE", gamma, 0.0) == pytest.approx(0.0)
        assert protocol.apply_curve("SCURVE", gamma, 0.5) == pytest.approx(0.5)
        assert protocol.apply_curve("SCURVE", gamma, 1.0) == pytest.approx(1.0)


def test_courbe_en_s_symetrique():
    for gamma in GAMMAS:
        for t in (0.1, 0.3, 0.45):
            somme = protocol.apply_curve("SCURVE", gamma, t) + protocol.apply_curve(
                "SCURVE", gamma, 1.0 - t
            )
            assert somme == pytest.approx(1.0)


def test_courbe_en_s_sens_du_gamma():
    # gamma > 1 : douce aux extrémités, donc sous la diagonale avant 0,5
    assert protocol.apply_curve("SCURVE", 2.0, 0.25) < 0.25
    assert protocol.apply_curve("SCURVE", 2.0, 0.75) > 0.75
    # gamma < 1 : comportement inverse
    assert protocol.apply_curve("SCURVE", 0.5, 0.25) > 0.25
    assert protocol.apply_curve("SCURVE", 0.5, 0.75) < 0.75


@pytest.mark.parametrize("curve", CURVES)
def test_gamma_un_neutralise_les_courbes(curve):
    """gamma = 1 rend les trois courbes identiques : c'est le repère neutre
    annoncé à l'utilisateur dans l'app."""
    for i in range(11):
        t = i / 10
        assert protocol.apply_curve(curve, 1.0, t) == pytest.approx(t, abs=1e-9)


@pytest.mark.parametrize("curve", CURVES)
@pytest.mark.parametrize("gamma", GAMMAS)
def test_monotone_et_bornee(curve, gamma):
    previous = -1.0
    for i in range(101):
        value = protocol.apply_curve(curve, gamma, i / 100)
        assert 0.0 <= value <= 1.0
        assert value >= previous - 1e-9
        previous = value


@pytest.mark.parametrize("curve", CURVES)
def test_entree_bornee(curve):
    assert protocol.apply_curve(curve, 2.0, -1.0) == pytest.approx(0.0)
    assert protocol.apply_curve(curve, 2.0, 5.0) == pytest.approx(1.0)


def test_courbe_inconnue_retombe_en_lineaire():
    assert protocol.apply_curve("PARABOLE", 2.0, 0.42) == pytest.approx(0.42)


def test_gamma_hors_bornes_est_rattrape():
    """apply_curve applique les mêmes bornes que le firmware, sinon l'aperçu
    montrerait une courbe que la carte refuserait d'appliquer."""
    assert protocol.apply_curve("POWER", 99.0, 0.5) == pytest.approx(
        0.5**protocol.GAMMA_MAX
    )
    assert protocol.apply_curve("POWER", float("nan"), 0.5) == pytest.approx(0.5)


def test_curve_points():
    points = protocol.curve_points("LINEAR", 1.0, count=5)
    assert len(points) == 5
    assert points[0] == [0.0, 0.0]
    assert points[-1] == [1.0, 1.0]


def test_curve_points_bornes_le_nombre_de_points():
    assert len(protocol.curve_points("LINEAR", 1.0, count=0)) == 2
    assert len(protocol.curve_points("LINEAR", 1.0, count=99999)) == 512
