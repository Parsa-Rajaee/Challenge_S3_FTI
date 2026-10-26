"""Project exceptions with stable CLI exit-code semantics."""


# Each subclass sets its own exit_code; the CLI returns it as the process exit code,
# so scripts can tell error types apart.
class FactoryError(Exception):
    """Base class for expected factory failures."""

    exit_code = 1


class ConfigurationError(FactoryError):
    """The project configuration is missing or invalid."""

    exit_code = 2


class NetworkError(FactoryError):
    """An HTTP request failed or returned an unsuccessful status."""

    exit_code = 3


class DataValidationError(FactoryError):
    """A source response or dataset violates its declared contract."""

    exit_code = 4


class CheckpointError(FactoryError):
    """A resume checkpoint is corrupt or incompatible with this run."""

    exit_code = 5
