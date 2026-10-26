# NYC ZIP/ZCTA population reference

Generated with `python scripts/build_zip_population.py` on 2026-10-26.
The resulting `zip_population.csv` has the schema required by the analysis
code: `zip_code`, `population`, and `borough`.

## Sources

- 2024 ACS 5-year Detailed Table B01003 (Total Population), table-based
  summary file: [ACS estimate file](https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b01003.dat).
  `B01003_E001` is the ZCTA total-population estimate.
- NYC Department of City Planning, [ZIP Code Tabulation Areas dataset](https://data.cityofnewyork.us/City-Government/ZIP-Code-Tabulation-Areas/35j5-n34v),
  used to define the NYC ZCTA candidate list.
- U.S. Census Bureau, [2020 ZCTA-to-county relationship file](https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt)
  and its [record layout](https://www.census.gov/programs-surveys/geography/technical-documentation/records-layout/2020-zcta-record-layout.html).
  `AREALAND_PART` is the land area of each ZCTA/county overlap in square meters.

## Mapping method and limitations

The NYC dataset lists 221 ZCTAs. The generator retains the 215 listed ZCTAs
with positive land-area overlap in at least one of New York City's five borough
counties. For each retained ZCTA, it assigns the borough whose county has the
largest `AREALAND_PART` among the five borough counties (Bronx `36005`, Kings /
Brooklyn `36047`, New York / Manhattan `36061`, Queens `36081`, and Richmond /
Staten Island `36085`). An exact area tie is resolved by the lower county FIPS
code. Six NYC-list entries without land overlap in any borough county are
excluded because the crosswalk cannot defensibly assign them to a borough.

The population is the full 2020 ZCTA's 2020-2024 ACS five-year estimate; it is
not clipped to the portion of a ZCTA inside the assigned borough. ZCTAs
approximate USPS ZIP codes, and assigning a cross-borough ZCTA's full population
to one borough is therefore an approximation. The ACS estimate and the
2020-vintage geographic crosswalk are public and reproducible, but this table
should not be interpreted as exact USPS ZIP populations or exact borough
population totals.
