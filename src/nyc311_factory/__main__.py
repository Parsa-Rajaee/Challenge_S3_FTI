"""Run the package with ``python -m nyc311_factory``."""

from .cli import main

# main() returns the exit code (0 on success), which SystemExit passes to the shell.
raise SystemExit(main())
