"""Population join and wide monthly summaries for curated NYC 311 records."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from .config import Settings
from .curation import BOROUGHS
from .exceptions import ConfigurationError, DataValidationError

# Columns the population CSV must contain.
POPULATION_COLUMNS: tuple[str, ...] = ("zip_code", "population", "borough")
# A ZIP code is exactly five digits, such as 10001.
POPULATION_ZIP_PATTERN = r"\d{5}"
# Label used for records that have no borough.
MISSING_AREA = "MISSING_BOROUGH"
# Rates are expressed per 10,000 residents, e.g. 5 complaints per 10k people.
RATE_PER_RESIDENTS = 10_000


def load_population(path: str | Path | None) -> pd.DataFrame:
    """Load and validate the ZIP-to-population reference table.

    The reference must provide one row per 5-digit ZIP with a non-negative
    integer population and a borough from the same set used by curation. Its
    borough is kept separately so it can be compared with the borough supplied
    by NYC 311.
    """
    if path is None or not Path(path).is_file():
        raise ConfigurationError(
            f"Population reference not found: {path}. Place the ZIP-to-population "
            "CSV at population_path in the project configuration."
        )
    # Read everything as text first, so ZIP codes keep leading zeros and nothing is guessed.
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
    missing_columns = set(POPULATION_COLUMNS) - set(frame.columns)
    if missing_columns:
        raise DataValidationError(
            f"Population reference {path} is missing columns: {sorted(missing_columns)}"
        )
    # Keep only the three expected columns, in a fixed order, and work on a copy.
    frame = frame.loc[:, list(POPULATION_COLUMNS)].copy()
    if frame.isna().any().any():
        raise DataValidationError(f"Population reference {path} contains blank values")

    # Trim spaces so " 10001" and "10001" match during the join.
    frame["zip_code"] = frame["zip_code"].str.strip()
    if not frame["zip_code"].str.fullmatch(POPULATION_ZIP_PATTERN, na=False).all():
        raise DataValidationError("Population reference ZIP codes must be 5 digits")
    if frame["zip_code"].duplicated().any():
        raise DataValidationError("Population reference contains duplicate ZIP codes")

    # errors="coerce" turns non-numeric text into NaN so it fails the check below.
    population = pd.to_numeric(frame["population"], errors="coerce")
    if population.isna().any() or (population < 0).any() or (population % 1 != 0).any():
        raise DataValidationError(
            "Population reference populations must be non-negative whole numbers"
        )
    frame["population"] = population.astype("int64")

    # Normalize case and spacing so "brooklyn " matches "BROOKLYN".
    frame["borough"] = frame["borough"].str.strip().str.upper()
    if not frame["borough"].isin(BOROUGHS).all():
        raise DataValidationError(f"Population reference boroughs must be one of {sorted(BOROUGHS)}")
    return frame.reset_index(drop=True)


def build_analysis_outputs(
    settings: Settings,
    curated_path: str | Path,
    population: pd.DataFrame,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Join curated records to population and write the analytical outputs.

    The left join uses ``validate="many_to_one"``, so the row count cannot
    change. Rows without a matching ZIP keep missing population values and are
    counted as unmatched. Areas in the monthly summary are the NYC 311 borough;
    rates use the summed reference population of the same borough.
    """
    curated_file = Path(curated_path)
    if not curated_file.is_file():
        raise DataValidationError(
            f"Curated records not found: {curated_file}; run curation first"
        )
    curated = pd.read_csv(curated_file, dtype=str, keep_default_na=False, na_values=[""])
    if curated.empty:
        raise DataValidationError(f"Curated records {curated_file} contain no rows")
    # closure_days was read as text; convert it back to numbers for the calculations.
    curated["closure_days"] = pd.to_numeric(curated["closure_days"])
    source_rows = len(curated)

    # Rename the reference columns to match the curated table, so the join key is the same name.
    # The reference borough gets its own name so it can be compared with the record's borough.
    reference = population.rename(
        columns={"zip_code": "incident_zip", "borough": "reference_borough"}
    )
    joined = curated.merge(
        reference,
        on="incident_zip",
        how="left",
        validate="many_to_one",
    )
    if len(joined) != source_rows:
        raise DataValidationError("Population join changed the number of curated rows")
    # Nullable integer type keeps unmatched ZIPs as <NA> rather than a float NaN.
    joined["population"] = joined["population"].astype("Int64")

    # A row is matched when its ZIP found a row in the population reference.
    matched = joined["population"].notna()
    # Only compare boroughs when both sources provide one; missing values are not disagreements.
    disagreement = (
        joined["borough"].notna()
        & joined["reference_borough"].notna()
        & (joined["borough"] != joined["reference_borough"])
    )
    joined["population_matched"] = matched

    # Output 1: one row per curated record, with its population attached.
    destination = Path(output_dir)
    analytical_path = destination / "analytical_records.csv"
    _write_csv_atomic(joined, analytical_path, index=False)

    # Output 2: monthly summary. created_date looks like 2024-01-05T..., so the first
    # 7 characters give the month (YYYY-MM). Records without a borough go into MISSING_AREA.
    summary_source = joined.assign(
        month=joined["created_date"].str.slice(0, 7),
        area=joined["borough"].fillna(MISSING_AREA),
    )
    monthly_wide = _build_monthly_wide(summary_source, population, settings.complaint_type)
    monthly_path = destination / "monthly_summary_wide.csv"
    _write_csv_atomic(monthly_wide, monthly_path, index=True)

    return {
        "source_records": source_rows,
        "analytical_records": len(joined),
        "population_matched_records": int(matched.sum()),
        "population_unmatched_records": int((~matched).sum()),
        "borough_disagreements": int(disagreement.sum()),
        "monthly_summary_rows": len(monthly_wide),
        "analytical_path": str(analytical_path),
        "monthly_summary_path": str(monthly_path),
    }


def _build_monthly_wide(
    records: pd.DataFrame,
    population: pd.DataFrame,
    complaint_type: str,
) -> pd.DataFrame:
    # Complaint counts for each (area, month). unstack moves months into columns;
    # months with no complaints become 0.
    counts = records.groupby(["area", "month"]).size().unstack("month", fill_value=0)
    # Median closure time per (area, month). The median is less distorted by a few
    # very long closures than the average would be.
    medians = (
        records.groupby(["area", "month"])["closure_days"].median().unstack("month")
    )
    # Total population of each borough, summed over all of its ZIP codes.
    borough_population = population.groupby("borough")["population"].sum()
    # Population for each area. Zero becomes NaN so the rate is blank rather than a division by zero.
    area_population = borough_population.reindex(counts.index).where(
        lambda values: values > 0
    )
    # Complaints per 10,000 residents for each area and month.
    rates = counts.div(area_population, axis=0) * RATE_PER_RESIDENTS

    # Every month present in the data, in chronological order, used as column names.
    months = sorted(records["month"].unique())
    wide = pd.concat(
        {
            "count": counts.reindex(columns=months, fill_value=0),
            "median_closure_days": medians.reindex(columns=months),
            "rate_per_10k": rates.reindex(columns=months),
        },
        axis=1,
    )
    # Flatten the (metric, month) column pairs into names like count_2024-01.
    wide.columns = [f"{metric}_{month}" for metric, month in wide.columns]
    # Put the complaint type and borough population at the front of the table.
    wide.insert(0, "complaint_type", complaint_type)
    wide.insert(1, "borough_population", area_population)
    wide.index.name = "borough"
    return wide


def _write_csv_atomic(frame: pd.DataFrame, destination: Path, index: bool) -> None:
    # Write to a temporary file first, then swap it in. A failed write never leaves
    # a half-written file at the destination.
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        frame.to_csv(temporary, index=index, lineterminator="\n", encoding="utf-8")
        # Atomic rename: readers see either the old file or the complete new one.
        os.replace(temporary, destination)
    finally:
        # Delete the temp file if anything failed before the rename.
        temporary.unlink(missing_ok=True)
