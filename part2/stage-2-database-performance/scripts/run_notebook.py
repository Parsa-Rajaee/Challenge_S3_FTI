"""Execute and save the notebook with a fresh kernel; credentials stay in the environment."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from sqlalchemy.engine import make_url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", help="override DATABASE_URL's database name (use a disposable database)")
    parser.add_argument("--kernel", default="python3", help="installed Jupyter kernel using the pinned environment")
    args = parser.parse_args()
    if not os.environ.get("DATABASE_URL"):
        parser.error("Set DATABASE_URL; the experiment replaces olist and analytics schemas")
    if args.database:
        url = make_url(os.environ["DATABASE_URL"]).set(database=args.database)
        os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    stage = Path(__file__).resolve().parents[1]
    path = stage / "solution.ipynb"
    notebook = nbformat.read(path, as_version=4)
    print("Running Stage 2 in a fresh kernel; olist/analytics schemas will be replaced.", flush=True)
    NotebookClient(
        notebook, timeout=900, kernel_name=args.kernel,
        resources={"metadata": {"path": str(stage)}},
    ).execute()
    counts = [cell.execution_count for cell in notebook.cells if cell.cell_type == "code"]
    if counts != list(range(1, len(counts) + 1)):
        raise RuntimeError("Notebook execution counts are not consecutive")
    nbformat.write(notebook, path)
    print(f"Saved {len(counts)} executed cells with outputs in solution.ipynb", flush=True)


if __name__ == "__main__":
    main()
