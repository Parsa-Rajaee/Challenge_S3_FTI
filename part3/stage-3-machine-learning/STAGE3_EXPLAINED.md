# How the credit-risk project works

The training data contains one row per applicant. The model estimates whether that person will experience serious delinquency within two years. A separate decision rule turns that probability into a prediction.

## Follow a borrower from CSV to model input

1. The factory reads the CSV, converts each field to its declared type, and checks the target, age, and account counts. It records rejected rows and their reasons in `quarantine.jsonl`.
2. It loads accepted records into `credit.borrowers`. The applicant ID is the primary key, so loading the same applicant again updates that row. The quality report counts accepted and rejected records. The run manifest records the source and output hashes.
3. The notebook requests `credit.vw_borrowers_clean` through SQLAlchemy. The view keeps the original late-payment values for auditing and adds cleaned values for modeling.

[CSV loader](../../src/nyc311_factory/credit_factory.py) · [Table definition](../../src/nyc311_factory/sql/credit_schema.sql) · [View definition](../../src/nyc311_factory/sql/credit_view.sql)

## Why the late-payment fields need special handling

In the 150,000-row training set, 264 borrowers have 98 in all three late-payment fields and five have 96 in all three. For those 269 borrowers, the observed default rate was 54.65%. For the remaining borrowers it was 6.60%.

Treating 98 as a count of late payments would give it a misleading numerical weight. The view replaces each special code with SQL `NULL` in the cleaned count and sets `has_sentinel_late_code`. This lets the model distinguish a flagged record from one with an ordinary payment history.

The view also flags missing income and dependent counts, ages below 18, and cases where income is missing and the debt ratio exceeds one. The training data contains 29,731 records with missing income and one record with age zero.

[Sentinel audit](src/credit_risk/sentinel.py) · [Feature calculations](src/credit_risk/features.py)

## How a probability becomes a decision

A false positive costs one unit in the challenge. A false negative costs 12. For example, missing two defaults and flagging three borrowers who repay costs 27 units. The analysis tries a range of probability thresholds, counts both types of error, and reports cost per 1,000 applicants so results are comparable across samples.

The prediction command reads a saved model and threshold. The executed notebook contains the model comparison, threshold curve, and subgroup results. The README has commands for running the demo, scoring a file, and testing the package.

[Cost calculation](src/credit_risk/cost.py) · [Executed notebook](solution.ipynb) · [Setup and commands](README.md)
