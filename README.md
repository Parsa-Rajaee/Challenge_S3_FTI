# FTI Season 3

This repository follows four stages. Start with the question you want to answer.

| Stage | Question | Where to start |
| --- | --- | --- |
| 1 · NYC 311 | Where and when do New Yorkers report heating problems? | [Factory walkthrough](PROJECT_EXPLAINED.md) · [Analysis notebook](solution.ipynb) |
| 2 · Database performance | How quickly can PostgreSQL answer five questions about Olist orders? | [Setup and benchmark](part2/stage-2-database-performance/README.md) · [Results](part2/stage-2-database-performance/report.md) |
| 3 · Credit risk | What decision threshold balances missed defaults against rejected borrowers? | [Training and prediction](part3/stage-3-machine-learning/README.md) · [Model report](part3/stage-3-machine-learning/report.md) |
| 4 · Olist capstone | Which newly approved orders should support contact within its capacity? | [Setup and scoring](part4/README.md) · [Results and decisions](part4/report.md) |

## Run the NYC 311 factory

The factory downloads one page at a time, records its progress, and validates each service request. It writes accepted records to CSV and records rejected rows with their reasons. The analysis joins accepted requests to ZIP-code population estimates.

Run these commands from the repository root. After creating the environment, activate it with `source .venv/bin/activate` on macOS or Linux, or `.\.venv\Scripts\Activate.ps1` in PowerShell.

```bash
python -m venv .venv
python -m pip install -r requirements.txt
python -m pip install -e .
nyc311-factory --count-only
nyc311-factory
nyc311-factory --curate-only
nyc311-factory --offline         # full local replay; requires a complete checkpoint
python -m unittest discover -s tests -v
```

`--count-only` checks the configured slice
without downloading the records. A download can be safely rerun with the same
configuration; its checkpoint and page files are stored under `data/raw/311`.
After a successful download, `--curate-only` validates those pages and writes
`data/curated/curated_records.csv`, `quarantine.jsonl`, and
`quality_report.json`. `--offline` reruns curation, analysis, and manifest
creation from a completed local checkpoint without source requests; the manifest
marks schema validation as skipped. Archive or remove the raw directory before
starting a different slice.

The current scope is fixed to NYC 311 `HEAT/HOT WATER` requests created from
2024-01-01 (inclusive) through 2025-07-01 (exclusive). A live count query on
2026-10-22 returned 427,458 matching requests; this is a source-count check,
not a count of validated or curated records. The minimum is configuration,
not a claim that all downloaded records will pass later quality checks.

## Optional API credentials

The NYC Open Data API works without a key but has a lower request quota. To
use a Socrata key ID and secret, set them as environment variables for the
terminal session instead of storing them in the project:

```powershell
$env:NYC311_API_KEY_ID = "<key id>"
$env:NYC311_API_KEY_SECRET = "<key secret>"
```

Do not commit credential files; `credential.md` is listed in `.gitignore`.

## Recorded run and follow-up checks

1. Done for the initial reference: `data/reference/zip_population.csv` uses
   2024 ACS ZCTA estimates and the documented land-overlap borough rule.
2. Local curation and the population join have been rerun from the complete
   raw checkpoint. Review ZIP/ZCTA matches and schema/quarantine rules; the live
   schema metadata request returned HTTP 403 during the full run.
3. `nyc311-factory --offline` now generates a manifest with output hashes and
   `source_schema_validation: skipped_offline`. Re-run online when the schema
   endpoint is reachable to capture a live validation and request count.
4. Execute `solution.ipynb` in a fresh Jupyter kernel and review its EDA charts
   and findings against the freshly generated outputs.
5. Review live schema validation when API access is available; rolling-window
   state and schema-drift responses already have offline tests.
