"""Brazil public-holiday adapter for the Stage 1 source, quarantine and manifest contract."""
from datetime import date, datetime, UTC
import json
from pathlib import Path
from urllib.request import Request, urlopen
from .factory import _sha256, _write_json_atomic

def acquire_holidays(years, destination: Path, offline=False):
    destination.mkdir(parents=True, exist_ok=True)
    events = {}
    for year in sorted(set(int(year) for year in years)):
        cache = destination / f"holidays_br_{year}.json"
        url = f"https://date.nager.at/api/v3/PublicHolidays/{year}/BR"
        if cache.is_file():
            rows = json.loads(cache.read_text(encoding="utf-8"))
        else:
            if offline:
                raise FileNotFoundError(f"Missing offline holiday cache: {cache}")
            request = Request(url, headers={"User-Agent":"FTI-capstone/1"})
            with urlopen(request, timeout=25) as response:
                rows = json.load(response)
            if not isinstance(rows, list) or not rows:
                raise ValueError(f"Empty or invalid calendar for {year}")
            _write_json_atomic(cache, rows)
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"Empty or invalid calendar for {year}")
        rejected = []
        accepted = 0
        for line, row in enumerate(rows, 1):
            try:
                day = date.fromisoformat(row["date"])
                if day.year != year or row["countryCode"] != "BR":
                    raise ValueError("country or year mismatch")
                name = row.get("localName") or row["name"]
                if not isinstance(name, str) or not name.strip():
                    raise ValueError("empty holiday name")
                if row.get("global", True):
                    events[day.isoformat()] = (day.isoformat(), name, "Nager.Date")
                accepted += 1
            except (ValueError, KeyError, TypeError) as error:
                rejected.append({"line":line, "reason":str(error), "record":row})
        _write_json_atomic(destination / f"quarantine_{year}.json", rejected)
        _write_json_atomic(destination / f"manifest_{year}.json", {
            "source":url, "source_sha256":_sha256(cache), "raw_records":len(rows),
            "accepted_records":accepted, "quarantined_records":len(rejected),
            "validated_at_utc":datetime.now(UTC).isoformat(),
        })
        if not accepted:
            raise ValueError(f"No valid holiday rows for {year}")
    return list(events.values())
