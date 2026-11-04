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
    y_t = np.asarray(y_true).astype(int)
    y_p = np.asarray(y_pred).astype(int)
    cm = confusion_matrix(y_t, y_p, labels=[0, 1])
    # cm layout: [[TN, FP], [FN, TP]]
    tn, fp, fn, tp = cm.ravel()
    return float(fp * cost_fp + fn * cost_fn)


def calculate_expected_cost_per_thousand(
    y_true: Any,
    y_pred: Any,
    *,
    cost_fp: float = DEFAULT_COST_FP,
    cost_fn: float = DEFAULT_COST_FN,
) -> float:
    """Normalize total business cost per 1,000 applicants."""
    y_t = np.asarray(y_true)
    n = len(y_t)
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
    y_t = np.asarray(y_true).astype(int)
    probs = np.asarray(y_probs)

    thresholds = np.linspace(0.01, 0.99, num_grid_points)
    best_threshold = 0.5
    min_cost_per_thousand = float("inf")
    best_cm = None

    history: list[dict[str, float]] = []

    for th in thresholds:
        preds = (probs >= th).astype(int)
        cost_th = calculate_expected_cost_per_thousand(y_t, preds, cost_fp=cost_fp, cost_fn=cost_fn)
        history.append({"threshold": float(th), "expected_cost_per_thousand": cost_th})
        if cost_th < min_cost_per_thousand:
            min_cost_per_thousand = cost_th
            best_threshold = float(th)
            best_cm = confusion_matrix(y_t, preds, labels=[0, 1])

    # Also evaluate default 0.5 threshold for comparison
    pred_default = (probs >= 0.5).astype(int)
    default_cost_per_thousand = calculate_expected_cost_per_thousand(
        y_t, pred_default, cost_fp=cost_fp, cost_fn=cost_fn
    )

    details = {
        "best_threshold": best_threshold,
        "min_cost_per_thousand": min_cost_per_thousand,
        "default_0_5_cost_per_thousand": default_cost_per_thousand,
        "cost_reduction_vs_default_pct": (
            ((default_cost_per_thousand - min_cost_per_thousand) / default_cost_per_thousand) * 100.0
            if default_cost_per_thousand > 0
            else 0.0
        ),
        "confusion_matrix_at_optimal": best_cm.tolist() if best_cm is not None else None,
        "history": history,
    }
    return best_threshold, min_cost_per_thousand, details
