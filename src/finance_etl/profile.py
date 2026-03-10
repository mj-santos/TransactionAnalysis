"""
Stage 3 — Profile.

Detect delimiter, encoding, headers for each registered file.
Store profile JSON in data/profiles/<file_hash>.json.
Update raw_files record.
"""
from __future__ import annotations

import json
from pathlib import Path

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore

from finance_etl.utils.csv_sniff import sniff_csv
from finance_etl.utils.log import get_logger

log = get_logger(__name__)


def profile_file(
    conn,
    file_hash: str,
    ingested_path: str,
    profiles_dir: Path,
) -> dict:
    """
    Profile a single CSV file and persist results.

    Returns the profile dict.
    """
    profile_path = profiles_dir / f"{file_hash}.json"
    profiles_dir.mkdir(parents=True, exist_ok=True)

    if profile_path.exists():
        log.info("Profile already exists for %s, loading from disk.", file_hash[:12])
        with open(profile_path) as f:
            return json.load(f)

    profile = sniff_csv(ingested_path)
    profile["file_hash"] = file_hash

    with open(profile_path, "w") as f:
        json.dump(profile, f, indent=2)

    conn.execute(
        """
        UPDATE raw_files
        SET delimiter    = ?,
            encoding     = ?,
            header_json  = ?,
            profile_path = ?
        WHERE file_hash = ?
        """,
        [
            profile["delimiter"],
            profile["encoding"],
            json.dumps(profile["headers"]),
            str(profile_path.resolve()),
            file_hash,
        ],
    )

    log.info(
        "Profiled %s: delimiter=%r  encoding=%s  cols=%d  rows~=%d",
        file_hash[:12],
        profile["delimiter"],
        profile["encoding"],
        len(profile["headers"]),
        profile["row_count_estimate"],
    )

    return profile
