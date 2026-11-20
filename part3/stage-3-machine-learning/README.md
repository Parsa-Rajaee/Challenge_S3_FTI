# Stage 3 · Credit default risk

A missed default costs 12 units in this challenge. Rejecting a borrower who would repay costs one unit. The [analysis notebook](solution.ipynb) compares two models and finds the probability threshold with the lowest measured cost. The [report](report.md) explains the results in Persian.

For a worked example of the cost calculation and the treatment of missing payment history, read the [credit-risk walkthrough](STAGE3_EXPLAINED.md).

## Follow one application through the code

| Step | What happens | Source |
| --- | --- | --- |
| Prepare the data | The factory validates the credit CSV and loads the accepted rows into PostgreSQL. The database view flags missing values and special late-payment codes. | [Ingestion](../../src/nyc311_factory/credit_factory.py) · [Database reader](src/credit_risk/db.py) |
| Build features | Convert application-time income, debt, and payment history into model inputs. | [Features](src/credit_risk/features.py) · [Late-payment codes](src/credit_risk/sentinel.py) |
| Train and evaluate | Fit the classifier and measure the cost of different decision thresholds. | [Pipeline](src/credit_risk/pipeline.py) · [Cost functions](src/credit_risk/cost.py) |
| Score new applications | Load the saved model and use its threshold to produce decisions. | [Prediction CLI](src/credit_risk/predict.py) |

## Run from the repository root

Activate the project environment, then install the packages and test dependencies.

```sh
python -m pip install -e ".[database]" -e ./part3/stage-3-machine-learning
python -m pip install -r part3/stage-3-machine-learning/requirements.txt
python -m pytest part3/stage-3-machine-learning/tests
```

To prepare training data, set `DATABASE_URL` to your PostgreSQL database and run the factory.

```sh
python -m nyc311_factory --load-credit-csv part3/stage-3-machine-learning/data/raw/cs-training.csv
```

To score applications with the saved model, run the demo or supply your own CSV.

```sh
python -m credit_risk.predict --demo
python -m credit_risk.predict --input applicants.csv --output decisions.csv
```

## Edit the analysis

Read the saved results in [solution.ipynb](solution.ipynb). Edit [stage3_analysis.py](stage3_analysis.py) to change the analysis. Lines beginning with `# %%` mark code cells and `# %% [markdown]` marks narrative cells. With the notebook dependencies from Stage 2 installed, rebuild and execute the notebook with:

```sh
python part3/stage-3-machine-learning/build_stage3_notebook.py
```

[generate_visualizations.py](generate_visualizations.py) writes the standalone report figures to [reports/figures](reports/figures).
