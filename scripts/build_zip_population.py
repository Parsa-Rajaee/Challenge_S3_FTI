"""Build the NYC ZIP/ZCTA population reference from public Census sources.

Run from the project root with:
    python scripts/build_zip_population.py
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path
from typing import Any

import pandas as pd
import requests

NYC_ZCTA_URL = (
    "https://data.cityofnewyork.us/api/v3/views/35j5-n34v/"
    "export.csv?accessType=DOWNLOAD"
)
COUNTY_CROSSWALK_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
    "tab20_zcta520_county20_natl.txt"
)
ACS_B01003_URL = (
    "https://www2.census.gov/programs-surveys/acs/summary_file/2024/"
    "table-based-SF/data/5YRData/acsdt5y2024-b01003.dat"
)

BOROUGH_COUNTIES = {
    "36005": "BRONX",
    "36047": "BROOKLYN",
    "36061": "MANHATTAN",
    "36081": "QUEENS",
    "36085": "STATEN ISLAND",
}


def _download(url: str) -> bytes:
    response = requests.get(
        url,
        headers={"User-Agent": "nyc311-data-factory/1.0"},
        timeout=180,
    )
    response.raise_for_status()
    return response.content


def build_reference() -> pd.DataFrame:
    """Return one ACS population estimate and borough per NYC ZCTA."""
    city_zctas = pd.read_csv(
        io.BytesIO(_download(NYC_ZCTA_URL)),
        dtype=str,
    )
    city_zctas = city_zctas.loc[:, ["Zip Code"]]
    zcta_codes = set(city_zctas["Zip Code"].str.strip().str.zfill(5))
    if not zcta_codes or any(len(code) != 5 or not code.isdigit() for code in zcta_codes):
        raise ValueError("NYC ZCTA source contains an invalid ZIP/ZCTA code")

    crosswalk = pd.read_csv(
        io.BytesIO(_download(COUNTY_CROSSWALK_URL)),
        sep="|",
        dtype=str,
        encoding="utf-8-sig",
    )
    crosswalk = crosswalk.loc[
        :, ["GEOID_ZCTA5_20", "GEOID_COUNTY_20", "AREALAND_PART"]
    ]
    overlap = crosswalk.loc[
        crosswalk["GEOID_ZCTA5_20"].isin(zcta_codes)
        & crosswalk["GEOID_COUNTY_20"].isin(BOROUGH_COUNTIES)
    ].copy()
    overlap["land_area_overlap"] = pd.to_numeric(
        overlap["AREALAND_PART"], errors="coerce"
    )
    overlap = overlap.loc[overlap["land_area_overlap"].gt(0)]
    if overlap.empty:
        raise ValueError("No NYC ZCTAs have land-area overlap with a borough county")

    # Choose the borough county containing the greatest land area for each ZCTA.
    # County FIPS is a deterministic tie-breaker if two overlaps are equal.
    borough_mapping = (
        overlap.sort_values(
            ["GEOID_ZCTA5_20", "land_area_overlap", "GEOID_COUNTY_20"],
            ascending=[True, False, True],
            kind="stable",
        )
        .drop_duplicates("GEOID_ZCTA5_20")
        .loc[:, ["GEOID_ZCTA5_20", "GEOID_COUNTY_20"]]
        .rename(
            columns={
                "GEOID_ZCTA5_20": "zip_code",
                "GEOID_COUNTY_20": "county_fips",
            }
        )
    )
    borough_mapping["borough"] = borough_mapping["county_fips"].map(BOROUGH_COUNTIES)

    estimates = pd.read_csv(
        io.BytesIO(_download(ACS_B01003_URL)),
        sep="|",
        dtype=str,
    )
    estimates = estimates.loc[:, ["GEO_ID", "B01003_E001"]]
    estimates["zip_code"] = estimates["GEO_ID"].str.extract(
        r"^860Z200US(\d{5})$", expand=False
    )
    estimates = estimates.loc[
        estimates["zip_code"].isin(set(borough_mapping["zip_code"])),
        ["zip_code", "B01003_E001"],
    ].rename(columns={"B01003_E001": "population"})
    if estimates["zip_code"].duplicated().any():
        raise ValueError("ACS table contains duplicate ZCTA population rows")

    reference = borough_mapping.merge(
        estimates,
        on="zip_code",
        how="left",
        validate="one_to_one",
    )
    population: Any = pd.to_numeric(reference["population"], errors="coerce")
    invalid_population = (
        population.isna() | population.lt(0) | population.mod(1).ne(0)
    )
    if invalid_population.any():
        invalid_zctas = reference.loc[invalid_population, "zip_code"].tolist()
        raise ValueError(
            f"Missing or invalid ACS population estimates for: {invalid_zctas}"
        )
    reference["population"] = population.astype("int64")

    reference = reference.loc[:, ["zip_code", "population", "borough"]]
    reference = reference.sort_values("zip_code", kind="stable").reset_index(drop=True)
    if reference["zip_code"].duplicated().any():
        raise ValueError("Generated population reference has duplicate ZCTAs")
    return reference


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/reference/zip_population.csv"),
        help="Destination CSV path (default: data/reference/zip_population.csv)",
    )
    args = parser.parse_args()

    reference = build_reference()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = args.output.with_name(f"{args.output.name}.tmp")
    try:
        reference.to_csv(temporary_path, index=False)
        temporary_path.replace(args.output)
    finally:
        temporary_path.unlink(missing_ok=True)

    print(f"Wrote {len(reference)} ZCTA rows to {args.output}")
    print("Borough row counts:")
    print(reference["borough"].value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
