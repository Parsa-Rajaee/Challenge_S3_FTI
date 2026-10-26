# Human review status

**Status: pending human approval.** The analysis and offline replay were
prepared with AI assistance, as disclosed in `report.md`. This file records
checks that still require the project owner; automated tests are not a
substitute for these decisions.

## Review before submission

- [ ] Inspect representative raw and quarantined records and approve the
  cleaning, duplicate, and quarantine rules.
- [ ] Approve the 2024 ACS ZCTA population source and the land-area borough
  assignment approximation documented in `data/reference/README.md`.
- [ ] Review the unmatched ZIPs, borough disagreements, and interpretation of
  per-10,000 rates in `report.md`.
- [ ] Review closure-duration outliers and confirm that long valid cases should
  remain in the analytical dataset.
- [ ] Open `solution.ipynb` in a fresh Jupyter kernel, run all cells, and inspect
  the rendered charts and interpretations.
- [ ] When the API is reachable, run the online factory and compare its schema
  validation and request count with the offline manifest.

Reviewer: ____________________

Date: ____________________

Notes / decisions: ______________________________________________________
