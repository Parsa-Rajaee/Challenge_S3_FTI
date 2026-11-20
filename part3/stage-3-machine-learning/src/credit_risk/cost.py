"""Cost-sensitive evaluation and decision threshold optimization for Stage 3 Challenge.

Business Cost Matrix:
- True Negative (Predict 0, Actual 0): Cost = 0
- False Positive (Predict 1, Actual 0): Cost = 1 unit (rejected creditworthy borrower, loss of interest margin)
- False Negative (Predict 0, Actual 1): Cost = 12 units (defaulted loan, loss of principal)
- True Positive (Predict 1, Actual 1): Cost = 0
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import confusion_matrix

DEFAULT_COST_FP: float = 1.0
DEFAULT_COST_FN: float = 12.0


def calculate_total_cost(
    y_true: Any,
    y_pred: Any,
    *,
    cost_fp: float = DEFAULT_COST_FP,
    cost_fn: float = DEFAULT_COST_FN,
) -> float:
    """Calculate the total business cost based on binary predictions."""
    actual = np.asarray(y_true).astype(int)
    predicted = np.asarray(y_pred).astype(int)
    matrix = confusion_matrix(actual, predicted, labels=[0, 1])
    # matrix layout: [[TN, FP], [FN, TP]]
    _, false_positives, false_negatives, _ = matrix.ravel()
    return float(false_positives * cost_fp + false_negatives * cost_fn)


def calculate_expected_cost_per_thousand(
    y_true: Any,
    y_pred: Any,
    *,
    cost_fp: float = DEFAULT_COST_FP,
    cost_fn: float = DEFAULT_COST_FN,
) -> float:
    """Normalize total business cost per 1,000 applicants."""
    actual = np.asarray(y_true)
    n = len(actual)
    if n == 0:
        return 0.0
    total = calculate_total_cost(y_true, y_pred, cost_fp=cost_fp, cost_fn=cost_fn)
    return float((total / n) * 1000.0)


def find_optimal_threshold(
    y_true: Any,
    y_probs: Any,
    *,
    cost_fp: float = DEFAULT_COST_FP,
    cost_fn: float = DEFAULT_COST_FN,
    num_grid_points: int = 200,
) -> tuple[float, float, dict[str, Any]]:
    """Scan candidate probability thresholds to find the threshold minimizing business cost."""
    actual = np.asarray(y_true).astype(int)
    probabilities = np.asarray(y_probs)

    thresholds = np.linspace(0.01, 0.99, num_grid_points)
    best_threshold = 0.5
    min_cost_per_thousand = float("inf")
    best_matrix = None

    history: list[dict[str, float]] = []

    for threshold in thresholds:
        predicted = (probabilities >= threshold).astype(int)
        cost_per_thousand = calculate_expected_cost_per_thousand(
            actual, predicted, cost_fp=cost_fp, cost_fn=cost_fn
        )
        history.append(
            {"threshold": float(threshold), "expected_cost_per_thousand": cost_per_thousand}
        )
        if cost_per_thousand < min_cost_per_thousand:
            min_cost_per_thousand = cost_per_thousand
            best_threshold = float(threshold)
            best_matrix = confusion_matrix(actual, predicted, labels=[0, 1])

    # Also evaluate default 0.5 threshold for comparison
    pred_default = (probabilities >= 0.5).astype(int)
    default_cost_per_thousand = calculate_expected_cost_per_thousand(
        actual, pred_default, cost_fp=cost_fp, cost_fn=cost_fn
    )

    details = {
        "best_threshold": best_threshold,
        "min_cost_per_thousand": min_cost_per_thousand,
        "default_0_5_cost_per_thousand": default_cost_per_thousand,
        "cost_reduction_vs_default_pct": (
            ((default_cost_per_thousand - min_cost_per_thousand) / default_cost_per_thousand)
            * 100.0
            if default_cost_per_thousand > 0
            else 0.0
        ),
        "confusion_matrix_at_optimal": best_matrix.tolist() if best_matrix is not None else None,
        "history": history,
    }
    return best_threshold, min_cost_per_thousand, details
