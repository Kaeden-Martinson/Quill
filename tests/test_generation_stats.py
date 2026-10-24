"""Checks the generator-evaluation statistics against values computed by hand or published examples."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training" / "generation_eval"))
import stats  # noqa: E402


def test_wilson_matches_known_interval():
    p, lo, hi = stats.wilson(10, 100)
    assert p == 0.1
    assert lo == pytest.approx(0.0552, abs=1e-4)
    assert hi == pytest.approx(0.1744, abs=1e-4)
    assert stats.wilson(0, 0) is None


def test_clopper_pearson_zero_is_about_three_over_n():
    lo, hi = stats.clopper_pearson(0, 200)
    assert lo == 0.0
    assert hi == pytest.approx(1 - 0.025 ** (1 / 200), abs=1e-6)   # 0.01828; the rule of three gives 0.015
    lo, hi = stats.clopper_pearson(5, 10)
    assert lo == pytest.approx(0.1871, abs=1e-3) and hi == pytest.approx(0.8129, abs=1e-3)


def test_mcnemar_exact():
    assert stats.mcnemar_exact(0, 0) is None
    assert stats.mcnemar_exact(1, 9) == pytest.approx(0.02148, abs=1e-4)
    assert stats.mcnemar_exact(5, 5) == 1.0


def test_auroc_and_ties():
    assert stats.auroc([3, 4], [1, 2]) == 1.0
    assert stats.auroc([1, 2], [3, 4]) == 0.0
    assert stats.auroc([1], [1]) == 0.5
    assert stats.auroc([], [1]) is None


def test_spearman():
    assert stats.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert stats.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert stats.spearman([1, 1, 1], [1, 2, 3]) is None


def test_fleiss_kappa_perfect_and_wikipedia_example():
    assert stats.fleiss_kappa([["ai", "ai"], ["human", "human"]]) == pytest.approx(1.0)
    # Wikipedia's worked example: 10 subjects, 14 raters, 5 categories, kappa 0.210
    counts = [[0, 0, 0, 0, 14], [0, 2, 6, 4, 2], [0, 0, 3, 5, 6], [0, 3, 9, 2, 0], [2, 2, 8, 1, 1],
              [7, 7, 0, 0, 0], [3, 2, 6, 3, 0], [2, 5, 3, 2, 2], [6, 5, 2, 1, 0], [0, 2, 2, 3, 7]]
    items = [[c for c, k in enumerate(row) for _ in range(k)] for row in counts]
    assert stats.fleiss_kappa(items) == pytest.approx(0.210, abs=1e-3)


def test_krippendorff_alpha():
    assert stats.krippendorff_alpha([[1, 1], [2, 2], [3, 3]]) == pytest.approx(1.0)
    # Krippendorff (2011) example, nominal: 4 coders, 12 units with missing values, alpha 0.743
    data = [[1, 1, None, 1], [2, 2, 3, 2], [3, 3, 3, 3], [3, 3, 3, 3], [2, 2, 2, 2], [1, 2, 3, 4],
            [4, 4, 4, 4], [1, 1, 2, 1], [2, 2, 2, 2], [None, 5, 5, 5], [None, None, 1, 1], [None, None, 3, None]]
    assert stats.krippendorff_alpha(data, "nominal") == pytest.approx(0.743, abs=1e-3)
    assert stats.krippendorff_alpha(data, "ordinal") == pytest.approx(0.815, abs=1e-3)
    assert stats.krippendorff_alpha([[1], [2, None]]) is None


def test_cluster_bootstrap_brackets_estimate():
    clusters = [[1, 1, 0], [0, 0, 0], [1, 1, 1], [0, 1, 0]]
    est, lo, hi = stats.cluster_bootstrap(clusters, stats.mean, resamples=2000)
    assert est == pytest.approx(0.5)
    assert lo <= est <= hi
    assert stats.cluster_bootstrap([[], []], stats.mean) is None
