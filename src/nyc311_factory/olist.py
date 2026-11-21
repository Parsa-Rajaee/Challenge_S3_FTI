"""Olist source adapter for the Stage 1 ingestion package."""
from datetime import UTC, datetime
from pathlib import Path
from .factory import _sha256, _write_json_atomic

def ingest_orders(engine, raw_dir, output):
    from database_performance.loader import load_olist
    from database_performance.schema import DATASETS

    started = datetime.now(UTC)
    raw_dir = Path(raw_dir)
    hashes = {table.filename: _sha256(raw_dir / table.filename) for table in DATASETS}
    result = load_olist(engine, raw_dir)
    manifest = dict(result)
    manifest.update({
        "run_started_at_utc": started.isoformat(),
        "run_finished_at_utc": datetime.now(UTC).isoformat(),
        "source_sha256": hashes,
        "raw_records": result["source_rows"],
        "accepted_records": result["loaded_rows"],
        "quarantined_records": result["source_rows"] - result["loaded_rows"],
        "quarantine_by_reason": result["quarantined_by_reason"],
        "outputs_sha256": {"quarantine": _sha256(Path(result["quarantine_file"]))},
    })
    _write_json_atomic(Path(output) / "run_manifest.json", manifest)
    return manifest
