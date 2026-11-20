"""Build and execute the complete, publication-grade solution.ipynb for Stage 3."""

from __future__ import annotations

import re
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT_DIR = Path(__file__).resolve().parent
NOTEBOOK_PATH = ROOT_DIR / "solution.ipynb"


def create_cells() -> list[nbformat.NotebookNode]:
    """Read the analysis in order, splitting at standard Python notebook markers."""
    source = ROOT_DIR.joinpath("stage3_analysis.py").read_text(encoding="utf-8")
    cells = []
    for section in re.split(r"(?=^# %%(?: \[markdown\])?$)", source, flags=re.MULTILINE)[1:]:
        marker, _, body = section.partition("\n")
        body = body.rstrip("\n")
        if marker == "# %% [markdown]":
            lines = [line.removeprefix("#").removeprefix(" ") for line in body.split("\n")]
            cells.append(nbformat.v4.new_markdown_cell("\n".join(lines)))
        else:
            cells.append(nbformat.v4.new_code_cell(body))
    return cells


def main():
    print("Building Stage 3 notebook with Continuous Variables Grid...")
    nb = nbformat.v4.new_notebook()
    nb.metadata = {
        "kernelspec": {
            "display_name": "Python 3 (ipykernel)",
            "language": "python",
            "name": "python3",
        },
        "language_info": {
            "codemirror_mode": {"name": "ipython", "version": 3},
            "file_extension": ".py",
            "mimetype": "text/x-python",
            "name": "python",
            "nbconvert_exporter": "python",
            "pygments_lexer": "ipython3",
            "version": "3.12.0",
        },
    }
    nb.cells = create_cells()

    print("Executing notebook with NotebookClient...")
    client = NotebookClient(nb, timeout=600, kernel_name="python3")
    client.execute(cwd=str(ROOT_DIR))

    print(f"Writing executed notebook to {NOTEBOOK_PATH}...")
    with open(NOTEBOOK_PATH, "w", encoding="utf-8") as f:
        nbformat.write(nb, f)
    print("Notebook built and executed successfully with Continuous Variables Grid!")


if __name__ == "__main__":
    main()
