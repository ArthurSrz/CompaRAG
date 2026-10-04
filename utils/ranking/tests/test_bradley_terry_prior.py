"""Prior Bradley-Terry : notes finies pour un moteur à 0 victoire."""
import numpy as np

from utils.ranking.bradley_terry import (
    bootstrap_confidence_intervals,
    fit_bradley_terry,
)

FLOOR = 400.0 * np.log10(1e-12) + 1000.0  # -3800


def _battles():
    # Reconstitution du cas prod : PageIndex 0/7, les autres moteurs équilibrés.
    b = [("PageIndex", other, other) for other in ["LlamaIndex"] * 3 + ["txtai"] * 2 + ["LangChain"] * 2]
    for _ in range(6):
        b += [("LlamaIndex", "txtai", "LlamaIndex"), ("txtai", "LangChain", "txtai"),
              ("LangChain", "LlamaIndex", "LangChain"), ("LlamaIndex", "LangChain", "LlamaIndex")]
    return b


def test_without_prior_zero_win_engine_collapses_to_the_floor():
    # La normalisation (moyenne géométrique = 1) décale un peu le plancher.
    assert fit_bradley_terry(_battles())["PageIndex"] < -3000


def test_prior_keeps_zero_win_engine_finite_and_last():
    elo = fit_bradley_terry(_battles(), prior=1.0)
    assert elo["PageIndex"] > 500
    assert elo["PageIndex"] == min(elo.values())


def test_prior_bootstrap_interval_is_not_collapsed():
    ci = bootstrap_confidence_intervals(_battles(), n_samples=50, prior=1.0)
    _, lo, hi = ci["PageIndex"]
    assert lo > 0 and hi > lo


def test_prior_barely_moves_engines_with_real_data():
    plain = fit_bradley_terry(_battles())
    prior = fit_bradley_terry(_battles(), prior=1.0)
    assert prior["LlamaIndex"] > prior["txtai"]  # ordre conservé
    assert abs(plain["LlamaIndex"] - plain["LangChain"]) >= abs(prior["LlamaIndex"] - prior["LangChain"])


def test_default_is_plain_mle():
    """Le classement LLM (compute.py) n'est pas modifié : prior=0 par défaut."""
    assert fit_bradley_terry(_battles()) == fit_bradley_terry(_battles(), prior=0.0)
