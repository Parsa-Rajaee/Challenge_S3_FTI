"""Public calendar interface shared by training and raw scoring."""
from nyc311_factory.holidays import acquire_holidays

__all__ = ["acquire_holidays"]
