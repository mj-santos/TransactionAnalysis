"""
Stage 2 — Ingest / Register (idempotent).

- Copies raw CSV to data/raw/<run_ts>/
- Computes SHA-256 (file_hash)
- Inserts into raw_files (skips if already seen)
- Creates / updates the run record in runs
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore

from finance_etl.utils.hashing import sha256_file
from finance_etl.utils.log import get_logger

log = get_logger(__name__)


def _build_ingested_filename(src: Path, file_hash: str) -> str:
    """Avoid same-name collisions within a single run timestamp directory."""
    return f"{src.stem}_{file_hash[:12]}{src.suffix}"


def register_files(
    conn,
    csv_paths: list[Path],
    run_id: str,
    raw_root: Path,
) -> list[dict]:
    """
    Register each CSV file in raw_files (idempotent).

    Returns a list of registration dicts (one per file), each containing:
      file_hash, original_path, ingested_path, file_size_bytes
    """
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    dest_dir = raw_root / run_ts
    dest_dir.mkdir(parents=True, exist_ok=True)

    registrations = []

    for src in csv_paths:
        src = Path(src)
        if not src.exists():
            raise FileNotFoundError(f"Input file not found: {src}")

        file_hash = sha256_file(src)
        file_size = src.stat().st_size
        dest = dest_dir / _build_ingested_filename(src, file_hash)

        # Copy only if not already there
        if not dest.exists():
            shutil.copy2(src, dest)

        # Check if already in raw_files
        existing = conn.execute(
            "SELECT file_hash FROM raw_files WHERE file_hash = ?", [file_hash]
        ).fetchone()

        if existing:
            log.info("File already registered (skipping): %s [%s]", src.name, file_hash[:12])
        else:
            conn.execute(
                """
                INSERT INTO raw_files
                  (file_hash, original_path, ingested_path, ingested_at, file_size_bytes)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    file_hash,
                    str(src.resolve()),
                    str(dest.resolve()),
                    datetime.now(timezone.utc),
                    file_size,
                ],
            )
            log.info("Registered: %s → %s [%s]", src.name, dest, file_hash[:12])

        registrations.append(
            {
                "file_hash": file_hash,
                "original_path": str(src.resolve()),
                "ingested_path": str(dest.resolve()),
                "file_size_bytes": file_size,
            }
        )

    return registrations


def create_run(
    conn,
    run_id: str,
    files_count: int,
) -> None:
    """Insert the initial run record with status='running'."""
    existing = conn.execute("SELECT 1 FROM runs WHERE run_id = ?", [run_id]).fetchone()
    if existing:
        raise ValueError(f"run_id already exists: {run_id}")

    conn.execute(
        """
        INSERT INTO runs (run_id, started_at, status, files_count,
                          rows_in, rows_staged, rows_normalized, rows_loaded, errors_count)
        VALUES (?, ?, 'running', ?, 0, 0, 0, 0, 0)
        """,
        [run_id, datetime.now(timezone.utc), files_count],
    )


def finalize_run(
    conn,
    run_id: str,
    status: str,
    counts: dict,
    notes: str = "",
) -> None:
    """Update the run record on completion or failure."""
    if status not in {"running", "success", "fail"}:
        raise ValueError(f"Invalid run status: {status}")

    conn.execute(
        """
        UPDATE runs SET
          finished_at       = ?,
          status            = ?,
          rows_in           = ?,
          rows_staged       = ?,
          rows_normalized   = ?,
          rows_loaded       = ?,
          errors_count      = ?,
          notes             = ?
        WHERE run_id = ?
        """,
        [
            datetime.now(timezone.utc),
            status,
            counts.get("rows_in", 0),
            counts.get("rows_staged", 0),
            counts.get("rows_normalized", 0),
            counts.get("rows_loaded", 0),
            counts.get("errors_count", 0),
            notes,
            run_id,
        ],
    )

    updated = conn.execute("SELECT changes()").fetchone()
    if not updated or updated[0] == 0:
        raise ValueError(f"Run not found for finalize_run: {run_id}")
