"""Valeurs de reference calculees a la main : ces fonctions notent le benchmark."""

from __future__ import annotations

import pytest

from council.benchmark.stats import (
    brier_score,
    mcnemar_exact,
    phi_coefficient,
    reliability_bins,
    wilson_interval,
)


def test_wilson_valeur_de_reference() -> None:
    # 50 succes sur 100 : intervalle connu (0,4038 ; 0,5962).
    low, high = wilson_interval(50, 100)
    assert low == pytest.approx(0.4038, abs=1e-3)
    assert high == pytest.approx(0.5962, abs=1e-3)


def test_wilson_reste_dans_zero_un_aux_extremes() -> None:
    assert wilson_interval(0, 10)[0] == 0.0
    assert wilson_interval(10, 10)[1] == pytest.approx(1.0)


def test_wilson_illustre_le_probleme_de_puissance_a_45() -> None:
    """La raison d'etre du test apparie : +/- 13 points sur 45 observations."""
    low, high = wilson_interval(32, 45)  # 71,1 %
    assert (high - low) / 2 == pytest.approx(0.13, abs=0.02)


def test_mcnemar_valeur_de_reference() -> None:
    # 10 paires toutes dans le meme sens : p = 2 * 0,5^10.
    assert mcnemar_exact(10, 0) == pytest.approx(2 * 0.5**10)
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(5, 5) == 1.0


def test_mcnemar_est_symetrique() -> None:
    assert mcnemar_exact(9, 2) == mcnemar_exact(2, 9)


def test_mcnemar_sur_peu_de_paires_ne_conclut_pas() -> None:
    """Regle posee dans le plan : moins de 10 paires discordantes, pas de conclusion."""
    assert mcnemar_exact(6, 1) > 0.05


def test_phi() -> None:
    assert phi_coefficient(10, 0, 0, 10) == pytest.approx(1.0)
    assert phi_coefficient(5, 5, 5, 5) == pytest.approx(0.0)


def test_brier() -> None:
    assert brier_score([(1.0, True), (0.0, False)]) == 0.0
    assert brier_score([(0.5, True), (0.5, False)]) == pytest.approx(0.25)
    # Sur-confiance : annonce 0,9, se trompe une fois sur deux.
    assert brier_score([(0.9, True), (0.9, False)]) == pytest.approx(0.41)


def test_bins_detectent_la_sur_confiance() -> None:
    bins = reliability_bins([(0.9, False)] * 8 + [(0.9, True)] * 2, n_bins=5)
    last = bins[-1]
    assert last.count == 10
    assert last.accuracy == pytest.approx(0.2)
    assert last.gap == pytest.approx(0.7)


def test_bins_couvrent_la_confiance_maximale() -> None:
    bins = reliability_bins([(1.0, True)], n_bins=5)
    assert sum(b.count for b in bins) == 1
