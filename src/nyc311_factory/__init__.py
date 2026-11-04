"""Tools for a reproducible data factory."""

# Shown by `--version` and written into the run manifest.
__version__ = "0.1.0"

from .credit_factory import load_credit_to_database, run_credit_factory

__all__ = ["__version__", "run_credit_factory", "load_credit_to_database"]
