# Project PDF Requirements and Completion Checklist

**Source documents**

- `00_Delivery_Guide.pdf` — shared delivery requirements for all stages (4 pages).
- `01_Challenge_Data_Factory.pdf` — Stage 1 requirements (6 pages).

This is an English-language extraction and status review of the two PDFs, not a
replacement for them. Statuses reflect the files, code, and tests present in this
workspace on **2026-10-26**. A feature is not treated as fully done merely
because it is described in a report or has code: live-data and end-to-end
requirements need run evidence, and code that cannot be imported is not done.

**Extraction note:** in the PDF text, multi-digit Persian numbers appear with
their digits reversed (for example `۸۱` means 18 months, `۵۱` means 15 minutes,
and `۰۰۸ تا ۰۰۵۱` means 800 to 1,500 words). The values below use the corrected
reading.

## Status key

- `[x] Done` — implemented and supported by workspace evidence.
- `[ ] Partial` — some implementation exists, but a requirement or its proof is
  missing, untested, or not runnable.
- `[ ] Open` — not implemented or not verified.
- `[ ] Review` — a human choice or sign-off is required.

## Resolved blocker

- [x] **Done** — `src/nyc311_factory/analytics.py` was an empty file (0 bytes),
  which broke CLI imports. It now provides `load_population` and
  `build_analysis_outputs`. `nyc311_factory.cli` imports, and `--analyze-only`
  exits with code 2 with a clear message when the population reference is
  missing. The offline tests still do not import `cli`, `factory`, or
  `analytics`, so a similar break would not be caught by the suite.

## 1. Shared delivery guide

### Stage sequence and project continuity

- [x] **Done** — Stage 1 is the Data Factory challenge; its package and data
  design are intended to feed Stage 2 (PostgreSQL performance), Stage 3
  (machine learning), and the final capstone. Do not treat the stages as
  independent projects or throw away reusable Stage 1 code.
- [ ] **Partial** — Keep the factory extensible for later sources and targets.
  Current code has a Socrata client and local file outputs; the shared
  validation/quarantine/manifest logic is not yet separated behind reusable
  source and destination interfaces.
- [ ] **Review** — Stage 2 will load this output into PostgreSQL. Column types,
  uniqueness keys, and table structure chosen in Stage 1 carry forward; record
  these choices in `report.md` with the reason for each.

### Required notebook (`solution.ipynb`)

- [ ] **Partial** — The main response is a Jupyter notebook. `solution.ipynb`
  exists (6 cells), but contains only an initial scope/API preflight and a
  placeholder that says the raw download has not started. The full factory run
  and required EDA are missing.
- [ ] **Open** — A fresh-kernel **Restart Kernel & Run All** must complete
  without errors and without manually prepared state. The population reference
  now exists, but the completed analysis and notebook run are not yet available.
- [x] **Done for the current notebook** — Saved code-cell execution counts are
  consecutive (`1`, `2`, `3`) and outputs are present. Re-run the final notebook
  before delivery so the full completed notebook has consecutive counts and
  saved outputs.
- [x] **Done for current notebook paths** — Notebook paths are relative (for
  example, `config/project.json`); no machine-specific `C:\Users\...` path is
  used in the notebook.
- [x] **Done** — A fixed seed (`2026`) is declared near the beginning of the
  notebook and applied to Python and NumPy random generators.
- [x] **Done** — The heavy ingestion and curation logic lives in the Python
  package rather than being implemented as long notebook cells.
- [ ] **Open** — The guide says a notebook with about 400 lines of straight-line
  code loses marks. Keep the notebook short and move logic into `src/`. Recheck
  once the EDA is added.
- [ ] **Partial** — Notebook sections have Persian Markdown introductions and
  the existing saved results are narrated, but the required analytical story,
  plots, and findings have not been added. Each section must start with a
  Markdown cell that says what is examined and why.
- [ ] **Open** — Language rule: Markdown cells are in Persian; variable names,
  function names, commit messages, and docstrings are in English. Check every
  notebook cell and module against this rule.
- [ ] **Open** — Keep the notebook within the **15-minute** runtime cap on an
  ordinary laptop, excluding the initial download. No complete-run timing or
  over-budget explanation is available yet.
- [ ] **Partial** — Dependencies are pinned exactly in `requirements.txt`, but
  the notebook directly imports NumPy and NumPy is not pinned there
  (`requirements.txt` lists `requests==2.32.5`, `pandas==2.3.3`,
  `matplotlib==3.10.8`). Pin NumPy as well.
- [ ] **Partial** — Existing notebook outputs are saved, but they only show the
  preliminary count/configuration results; the final deliverable outputs are
  not yet present.

### Decision report (`report.md`)

- [x] **Done** — Explain the problem in the author's own words and state
  assumptions not specified by the prompt.
- [x] **Done in the current draft** — Include at least five key decisions and,
  for each, alternatives, the chosen option, evidence/reasoning, and trade-offs.
  The draft has a decision table; re-check that every final decision has
  adequate evidence after a full run.
- [x] **Done** — Record at least one failed or abandoned approach and why. The
  draft records the Census ACS trial that returned `Missing Key`.
- [x] **Done** — Describe limitations and risks if the source data changes.
- [x] **Done** — Include a short “if I had two more days” paragraph.
- [x] **Done** — `report.md` has an `AI usage` section and discloses the
  PDF-requirements checklist work. Keep it accurate as further AI-assisted work
  is added, and ensure the author can explain every delivered code decision.
- [ ] **Partial** — Every number in the report must be traceable to notebook
  output. The source-count figure is in the notebook, but page-size and
  quarantine-threshold decisions also need to be traceable in the final
  notebook/run evidence.
- [ ] **Open** — Report length: the guide suggests **800–1,500 words**; the
  report is not yet confirmed to be in this range. Keep the report focused on
  decisions rather than restating code. Longer reports earn no extra marks.
- [ ] **Open** — Every decision must be defensible from the code. A sentence
  that the reader can work out from the code alone is in the wrong place in the
  report.

### Files, paths, Git, and reproducibility

- [x] **Done** — The expected project components exist: `README.md`,
  `requirements.txt`, `report.md`, `solution.ipynb`, `src/`, `tests/`, and
  `data/raw/` / `data/curated/`.
- [ ] **Open** — Deliver the folder under the name `stage-<n>-<your-name>/`
  (for Stage 1, `stage-1-<your-name>/`). The current project folder is named
  `Season_3_project`.
- [x] **Done** — README run instructions use project-relative paths and include
  setup, count, download, curation, and test commands.
  - [ ] **Open** — The guide asks for a one-line README run instruction. Check
    the current README against this limit.
- [x] **Done** — `.gitignore` excludes raw source files and generated outputs.
- [ ] **Review** — `.gitignore` also excludes all files under `data/curated/`.
  The PDF explicitly says raw data must not be in Git but expects curated
  deliverables; decide whether curated deliverables should be retained or
  published separately.
- [ ] **Open** — Deliver the folder as a real Git repository with history. No
  `.git` directory is present in this workspace.
- [ ] **Open** — Create at least **10 meaningful English-language commits**;
  one final “everything” commit is not acceptable.
- [ ] **Open** — Use a separate feature branch and merge it through a Pull
  Request or Merge Request with an explanation.
- [ ] **Open** — Ensure no raw data file appears anywhere in Git history, not
  just in the latest tree. If raw data was committed accidentally, purge it
  from history; deleting it only from the latest checkout is insufficient.
- [ ] **Review** — Preserve these design decisions for later stages; later work
  should reuse the package and database rather than rebuilding the pipeline.

### Process, tools, AI disclosure, and grading

- [x] **Done as project guidance** — The PDFs intentionally provide no starter
  code and do not prescribe a solution or implementation path. The author must
  choose and justify architecture, libraries, assumptions, and ordering rather
  than asking for a prescribed algorithm. Questions should clarify the stated
  problem, not request the solution choice itself.
- [x] **Done** — Current dependencies use exact versions for `requests`,
  `pandas`, and `matplotlib`; the project does not use an orchestration
  framework or AutoML tool.
- [ ] **Partial** — Keep all tools within the allowed scope (Python/venv/pip,
  modules/packages, `unittest`, Git, pandas, requests, JSON, PostgreSQL,
  SQLAlchemy, scikit-learn, and one charting library). NumPy is used in the
  notebook but is not in the guide's list or in `requirements.txt`; decide
  whether to remove the import or justify NumPy in `report.md`.
- [x] **Done as reference** — The shared evaluation weights are: correctness
  **30%**, engineering quality **25%**, evidence/reasoning **25%**, and
  reproducibility **20%**. Reproducibility is a prerequisite: if the project
  cannot run on the evaluator's machine, other categories cannot be assessed.

Stage 1 — NYC 311 Data Factory

**Planning guidance:** the PDF suggests **5–7 working days** for the challenge.
The notebook runtime cap is **15 minutes**, excluding the initial data download;
record an explanation if a completed notebook exceeds that cap.

### Purpose, source, scope, and source limitation

- [x] **Done** — The task is to build a dependable data factory, not to answer
  the city's policy question about closure performance.
- [x] **Done** — The configured primary source is the NYC 311 Socrata API at
  `https://data.cityofnewyork.us/resource/erm2-nwe9.json`; it can be used
  without an API key but has a more limited request quota.
- [x] **Done in configuration** — Select a continuous **18-month** time window
  and a narrowing criterion, and keep both configurable rather than
  hard-coded. Current selection: `HEAT/HOT WATER`, 2024-01-01 inclusive to
  2025-07-01 exclusive (`config/project.json`).
- [x] **Done for the current source snapshot** — The selected slice exceeds
  the **300,000** minimum: raw pages contain 427,458 records, and the curated
  output and quality report both show 427,458 accepted records and zero
  quarantined records (verified 2026-10-26). A future live-source run may differ.
- [ ] **Partial** — Record the selection criterion in `run_manifest.json`.
  It is present in `config/project.json`. The manifest code writes
  `selection_scope` from the settings, but no manifest has been produced.
- [x] **Done for the initial reference** — Selected the public 2024 ACS
  five-year B01003 ZCTA estimates and documented their source, retrieval date,
  and approximate borough assignment in `report.md` and
  `data/reference/README.md`. The generated reference contains 215 ZCTAs;
  review its approximation before interpreting borough rates.
- [ ] **Partial** — Join population data into the factory and compare the
  reference-derived area/borough mapping against the borough supplied by NYC
  311. Report disagreements as data-quality findings. The join code is in
  `analytics.py` and has only been tested on synthetic data; the new real
  reference has not yet been used in an analysis run.

### Package, configuration, and error model

- [x] **Done** — The code is an installable Python package under `src/`, with a
  CLI entry point (`nyc311-factory`) defined in `pyproject.toml`.
- [x] **Done** — The CLI imports after restoring `analytics.py`. `--analyze-only`
  exits with code 2 when `data/reference/zip_population.csv` is missing. The
  other modes have not been run end-to-end.
- [ ] **Partial** — One command must run the **entire** factory from an empty
  output directory, while parameters allow running individual stages. `factory.py`
  orchestrates download, curation, population join, summaries, and the manifest.
  The CLI exposes `--count-only`, `--download-only`, `--curate-only`,
  `--analyze-only`, and `--rolling-window-days`. The full path has not been run;
  it now stops at the population reference step until that file exists.
- [ ] **Partial** — Keep all runtime settings outside logic. Date range, filter,
  page size, paths, retry attempts, HTTP method, target count, quarantine
  ceiling, population path, and rolling window days are in `config/project.json`.
  The HTTP timeout and some source/schema rules are still fixed in code and
  should be reviewed as possible magic values.
- [x] **Done** — A project exception hierarchy distinguishes configuration,
  network, data-validation, and checkpoint failures with distinct exit codes.
- [x] **Done** — The scope filter is escaped and sent to Socrata; the client has
  a count-only preflight mode.

### Incremental HTTP ingestion and memory

- [x] **Done and unit-tested** — Fetch records in pages rather than loading the
  entire API result at once.
- [x] **Done and unit-tested** — Write each page and checkpoint atomically;
  validate checkpoint signature and page presence; resume from the saved
  offset after interruption.
- [x] **Done and unit-tested** — A completed raw download can be rerun without
  refetching pages; output pages are named deterministically by offset.
- [ ] **Partial** — Define and verify behavior for non-2xx, invalid JSON,
  non-array/oversized pages, and incomplete responses. The client retries
  network errors, HTTP 429, and 5xx; it fails on other non-2xx responses and
  rejects malformed JSON/invalid page shapes. However, a valid but unexpectedly
  short page is treated as end-of-data, and no live-source end-to-end run has
  verified this failure mode.
- [x] **Done and unit-tested** — Support both GET and POST; tests use mocked
  HTTP sessions and do not require the network.
- [ ] **Partial** — Explain why GET and POST differ for API compatibility in
  `report.md`. The report notes that API policies vary, but does not yet give a
  sufficiently direct rationale. The guide requires one sentence on why one
  API accepts a method and another does not.
- [ ] **Partial** — Do not hold the entire raw dataset in memory. Download and
  curation code operate page by page; curation retains a set of seen IDs, and
  there is no measured memory profile or explicit demonstration yet.

### Schema contract, quarantine, and cleaning

- [x] **Done as an initial contract** — `report.md` documents output field
  types, nullability, domains, uniqueness, timestamp normalization, ZIP
  handling, and open/closed case treatment.
- [x] **Done and unit-tested** — Invalid rows are written to
  `data/curated/quarantine.jsonl` with a reason code and the original record;
  they are not silently dropped.
- [x] **Done and unit-tested** — `quality_report.json` reports rejected rows
  by reason code. It does not yet report per-column metrics (see Added
  complexities).
- [x] **Done in configuration and code** — A maximum quarantine ratio is
  configurable (currently 5%); curation fails if it is exceeded.
- [ ] **Review** — A human must inspect representative raw and quarantined
  records and approve the current invalidity, duplicate, missing-value, ZIP,
  borough, and 5% threshold rules. They have only been tested with fixtures,
  not reviewed against the downloaded source.
- [x] **Done as initial policy** — Date fields are parsed and normalized to
  UTC; `closure_days` is derived; blank optional values become missing; ZIP+4
  reduces to a five-digit join key; `N/A`, `00000`, and malformed ZIP values
  become missing; `Unspecified` borough becomes missing
  (`curation.py`).
- [x] **Done as initial policy** — A close timestamp before creation is
  quarantined. The report defines the first valid `unique_key` occurrence as
  retained and later occurrences as duplicates.
- [ ] **Partial** — The duplicate definition and all cleaning/missing-value
  choices need a rationale grounded in real records, not only unit tests.
  Per-column rationale is required by the guide: a single policy applied to all
  columns without justification is a weak decision.
- [ ] **Open** — Join the population table and explain pre/post join row counts,
  including any rows that multiply, disappear, or lack a population match.

### Required outputs and reproducibility

- [x] **Done for existing curated artifacts** — `curated_records.csv` includes
  `closure_days`; the real 427,458-row join wrote `analytical_records.csv` with
  the same row count. A new end-to-end run is still needed to reproduce these
  artifacts from raw source pages.
- [x] **Done for existing curated artifacts** — `monthly_summary_wide.csv` was
  generated from the real records with counts, median closure days, and rates
  per 10,000 residents. The borough population remains an approximate ZCTA
  assignment; a fresh full-factory run has not been completed.
- [ ] **Partial** — `run_manifest.json` was generated from an offline replay and
  contains real row counts, timing, and output hashes. It records zero requests
  and explicitly marks live schema validation as skipped; a live manifest is
  still blocked by HTTP 403.
- [ ] **Partial** — Fixture tests confirm repeated offline factory runs produce
  identical output hashes. Determinism across an online source re-download is
  still unverified because the live endpoint is inaccessible from this network.
- [ ] **Partial** — Offline replay is deterministic for the cached source pages.
  A live API can change while offset pagination is running, so online re-download
  equivalence remains unverified; `run_manifest.json` documents the snapshot risk.

### Offline tests

- [x] **Done** — The workspace has 46 `unittest` tests and the discovery command
  `python -m unittest discover -s tests -v` passes in the current environment.
- [x] **Done** — Tests are offline and cover HTTP errors/retries, invalid API
  responses, GET and POST, quarantine reasons and valid records, quarantine
  threshold failures, resume offsets, checkpoint validation, curation output,
  duplicates, open cases, and a derived closure duration.
- [ ] **Partial** — The PDF requires tests for derived-column boundary cases.
  New offline tests cover CLI modes, analytics, factory/manifest, rolling-window
  state, and schema-drift responses; some date-boundary cases remain open.
- [x] **Done** — Reviewed the suite: HTTP calls use mocks, offline replay uses a
  complete local checkpoint, and assertions check concrete outputs and errors.

### Git requirements

- [ ] **Open** — At least 10 meaningful commits with readable English messages.
- [ ] **Open** — A separate feature branch merged through a Pull Request or
  Merge Request with an explanation.
- [x] **Done for the published commits** — Credentials, downloaded source pages,
  generated analytical outputs, and supplied Census extracts are excluded from
  Git. The population reference is a derived 215-row project input.

### Mandatory added complexities

- [ ] **Partial** — The parameterized rolling-window mode is implemented, and
  offline tests cover initial lookback, resume date, invalid state, and atomic
  state writes. Live incremental downloads remain unverified.
- [ ] **Partial** — Schema drift checks are implemented and offline tests cover
  matching fields, missing fields, and changed types. Live metadata validation
  remains unverified because the source endpoint returns HTTP 403.
- [ ] **Partial** — `report.md` documents a minimum of nine data-page requests
  plus one schema request for a fresh 427,458-row run, absent retries. The cached
  checkpoint does not preserve the historical request count, and live requests
  remain blocked; the offline manifest correctly records zero replay requests.
- [x] **Done for current data** — `quality_report.json` contains per-column null
  count/percentage, exact distinct count, and observed min/max; fixture tests
  cover the metrics, and the full local curation regenerated the report.

### Required EDA in the notebook

- [ ] **Partial** — `solution.ipynb` now contains descriptive closure statistics,
  five charts, category comparisons, a numeric relationship check, and findings
  from the existing real analytical outputs. Its cells were executed for
  validation, but saved notebook outputs and a fresh-kernel notebook execution
  still need review.
- [ ] **Partial** — The notebook identifies the IQR outlier rule and retains
  long-duration records; confirm the interpretation against raw examples.

### Stage 1 acceptance criteria

The PDF says Stage 1 passes only if all these hold:

- [ ] **Open** — One command runs the complete factory from an empty workspace
  through final outputs on the evaluator's machine. The population reference
  now exists, but a full end-to-end run has not yet been completed.
- [x] **Done for offline replay** — Replaying the complete cached 427,458-row
  slice twice produced identical hashes across all 14 output files, with no
  duplicate request keys. A second online download remains unverified.
- [x] **Done for raw-page ingestion** — Interrupting and resuming raw download
  uses the saved checkpoint without rewriting earlier pages; offline tests
  cover this. End-to-end interruption through all final outputs remains open.
- [x] **Done** — Offline test discovery passes with one command (46 tests),
  including CLI and factory manifest coverage.
- [ ] **Partial** — `run_manifest.json` was generated by an offline replay with
  real file hashes and counts. It records zero HTTP requests and
  `source_schema_validation: skipped_offline`; a live schema-validated run is
  still blocked by HTTP 403.
- [x] **Done in the current report** — Duplicate and invalid-record definitions
  are documented; review them against raw records before final submission.

### Architecture warning for later stages

- [ ] **Partial** — Future file/API sources and database/file destinations
  should plug into the factory without rewriting shared validation,
  quarantine, and manifest logic. Current implementation is still specifically
  shaped around Socrata JSON pages and local CSV/JSON outputs.

## 3. Current blockers and next actions

0. Done — `src/nyc311_factory/analytics.py` imports and the real population join
   ran on the existing curated records; see the match and disagreement totals
   recorded in `report.md`.
1. Done for the initial reference — selected and documented the 2024 ACS
   five-year ZCTA estimates and the Census land-overlap borough mapping; the
   generated file is at `data/reference/zip_population.csv`. Review its
   approximation before treating the population-derived borough as exact.
2. Curation and analysis have been rerun from the complete local raw checkpoint.
   Have a human approve the schema, cleaning rules, duplicate definition, and
   quarantine threshold against representative records.
3. Done — population join, monthly summary, per-column quality metrics, and an
   offline-replay `run_manifest.json` were generated from local data. Live
   request-budget and schema evidence remain unavailable because the endpoint
   returned HTTP 403.
4. Done in part — offline tests cover CLI mode validation, factory/manifest,
   population join, and checkpoint replay. Add rolling-window and schema-drift
   tests.
5. Verify rolling-window and schema-drift behavior against the live source.
6. EDA code and findings are now in `solution.ipynb`, and corresponding
   observations are in `report.md`. Execute in a fresh Jupyter kernel, save and
   review chart outputs, and confirm actual findings against a fresh factory
   run. Keep code in `src/` and the notebook language rule.
7. NumPy import removed from the notebook; keep the report within 800–1,500
   words. Rename the delivery folder to `stage-1-<your-name>/`.
8. The Git repository exists but has no commits. Create the required history and
   feature-branch merge, and audit history for raw data.
9. Run a clean-environment end-to-end check and record the wall-clock time
   against the 15-minute cap.

## 4. Evidence checked

- Project configuration and package files: `config/project.json`,
  `pyproject.toml`, `requirements.txt`.
- Implementation: `src/nyc311_factory/` — `api.py` (request counter, schema
  drift check), `cli.py` (modes and rolling window), `config.py`,
  `curation.py` (validation and BOROUGHS rule), `factory.py` (orchestration and
  manifest), `pipeline.py`, and `exceptions.py`.
- `src/nyc311_factory/analytics.py` — restored and covered by offline tests.
  The real `--analyze-only` run succeeded on 427,458 records; 427,405 matched
  the reference and 53 did not.
- Offline tests: `tests/test_api.py`, `tests/test_config.py`,
  `tests/test_pipeline.py`, `tests/test_curation.py`, `tests/test_analytics.py`,
  `tests/test_factory.py`, and `tests/test_cli.py`. Discovery run: 46 tests, OK.
  CLI compatibility, offline manifest, analytics, curation metrics,
  rolling-state behavior, and schema drift are covered offline.
- Documentation and notebook: `README.md`, `report.md`, `HUMAN_REVIEW.md`,
  and `solution.ipynb` (EDA code cells validated programmatically; saved
  notebook outputs and a Jupyter-kernel execution remain pending).
- Data folders: `data/raw/311/` contains nine pages and a complete checkpoint
  (427,458 rows). `data/curated/` contains regenerated curation, analysis,
  quality outputs, and an offline-replay `run_manifest.json` that marks live
  schema validation as skipped.
  `data/reference/` contains the generated population CSV and methodology note.
- Git: repository initialized, but the current branch has no commits.
- Source PDFs: `00_Delivery_Guide.pdf` and `01_Challenge_Data_Factory.pdf`
  (text extracted with `pypdf`).
