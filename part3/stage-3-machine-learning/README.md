# Stage 3: Cost-Sensitive Machine Learning for Credit Default Risk

Production-grade cost-sensitive credit risk classification system built for the Give Me Some Credit challenge.

---

## Architecture Overview

```
part3/stage-3-machine-learning/
├── data/
│   ├── raw/                 # cs-training.csv, Data Dictionary.xls (Source files)
│   └── curated/             # curated_records.csv, quality_report.json, run_manifest.json
├── sql/
│   ├── 001_credit_schema.sql # PostgreSQL DDL for credit.borrowers
│   └── 002_credit_views.sql  # Database data preparation view (credit.vw_borrowers_clean)
├── src/
│   └── credit_risk/
│       ├── __init__.py
│       ├── db.py            # SQLAlchemy relational data extraction
│       ├── sentinel.py      # Credit bureau sentinel codes (96, 98) auditing & masking
│       ├── cost.py          # Cost matrix evaluation (12:1 FN:FP) & threshold optimization
│       └── features.py      # Feature engineering with pre-decision leakage audit
├── tests/
│   └── test_credit_risk.py  # 8 comprehensive unit tests
├── requirements.txt         # Pinned dependencies
├── pyproject.toml           # Editable package definition
├── report.md                # Comprehensive business and engineering report
├── solution.ipynb           # Precomputed narrative Jupyter notebook
└── README.md
```

---

## Quickstart

### 1. Environment Setup
Activate the Season 3 virtual environment and install dependencies:
```powershell
.venv\Scripts\Activate.ps1
python -m pip install -e part3/stage-3-machine-learning
```

### 2. Database Ingestion via Factory
Run the Stage 1 package factory to ingest, validate, and load all 150,000 records into PostgreSQL:
```powershell
python -m nyc311_factory --load-credit-csv part3/stage-3-machine-learning/data/raw/cs-training.csv
```

### 3. Run Unit Tests
Run the 8 required unit tests:
```powershell
pytest part3/stage-3-machine-learning/tests
```

### 4. Open Solution Notebook
Launch Jupyter to inspect or run `solution.ipynb`:
```powershell
jupyter lab part3/stage-3-machine-learning/solution.ipynb
```
*(The notebook contains precomputed sequential cell executions reading directly from PostgreSQL view `credit.vw_borrowers_clean`)*.
