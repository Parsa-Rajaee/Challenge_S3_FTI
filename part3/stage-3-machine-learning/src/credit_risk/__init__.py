"""Credit Risk Modeling Package - Stage 3 Challenge.

Provides relational database loading, credit bureau sentinel value handling,
cost-sensitive loss evaluation (12:1 FN:FP), feature engineering with leak audits,
and reproducible machine learning pipelines.
"""

from .cost import (
    DEFAULT_COST_FN,
    DEFAULT_COST_FP,
    calculate_expected_cost_per_thousand,
    calculate_total_cost,
    find_optimal_threshold,
)
from .db import get_db_engine, load_clean_borrowers, load_raw_borrowers
from .sentinel import (
    SENTINEL_CODES,
    SentinelAuditor,
    clean_sentinel_values,
)

__all__ = [
    "DEFAULT_COST_FN",
    "DEFAULT_COST_FP",
    "calculate_total_cost",
    "calculate_expected_cost_per_thousand",
    "find_optimal_threshold",
    "get_db_engine",
    "load_clean_borrowers",
    "load_raw_borrowers",
    "SENTINEL_CODES",
    "SentinelAuditor",
    "clean_sentinel_values",
]
