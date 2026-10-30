"""Run a command with DATABASE_URL derived from the local Docker PostgreSQL container.

Usage: python with_local_db.py <command> [args...]

The password is read from the container configuration at run time and is only
placed in the child process environment; it is never printed or written to disk.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from urllib.parse import quote

CONTAINER = os.environ.get("POSTGRES_CONTAINER", "season3-postgres")


def local_database_url() -> str:
    inspected = subprocess.run(
        ["docker", "inspect", CONTAINER, "--format", "{{json .Config.Env}}"],
        check=True, capture_output=True, text=True,
    ).stdout
    env = dict(item.split("=", 1) for item in json.loads(inspected) if "=" in item)
    user, password, database = env["POSTGRES_USER"], env["POSTGRES_PASSWORD"], env["POSTGRES_DB"]
    return f"postgresql+psycopg2://{quote(user)}:{quote(password)}@127.0.0.1:5432/{quote(database)}"


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    child_env = dict(os.environ, DATABASE_URL=local_database_url())
    return subprocess.run(argv, env=child_env).returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
