"""FastAPI service — uploads, async runs, preview/commit, reports, and web UI."""
import json
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# In-memory tracking for async background runs
# Keys: run_id  Values: {"status": "pending"|"running"|"success"|"failed", ...}
# ---------------------------------------------------------------------------
_async_runs: dict[str, dict] = {}

# ---------------------------------------------------------------------------
# Whitelisted fields + buckets for safe custom report SQL generation
# ---------------------------------------------------------------------------
_REPORT_FIELDS = frozenset({
    "transaction_date", "description", "merchant", "category",
    "amount", "currency", "bank_name", "account_name", "account_id",
    "statement_type",  # Feature 1: allow filtering by statement type
})
# Fields that may be used in ORDER BY
_SORT_FIELDS = frozenset({
    "transaction_date", "amount", "description", "merchant",
    "category", "bank_name", "account_name",
})
_REPORT_BUCKETS = frozenset({"day", "week", "month", "year"})

# ---------------------------------------------------------------------------
# Pydantic models — these power the /docs schema and enforce types at runtime
# ---------------------------------------------------------------------------
try:
    from pydantic import BaseModel, Field

    class UploadResponse(BaseModel):
        filename:              str             = Field(..., description="Original filename as uploaded")
        path:                  str             = Field(..., description="Server-side path to pass as input to POST /runs")
        size:                  int             = Field(..., description="File size in bytes")
        headers:               list[str]       = Field(default_factory=list, description="Detected CSV column headers")
        sample_rows:           list[dict]      = Field(default_factory=list, description="First few data rows for preview")
        encoding:              Optional[str]   = Field(None, description="Detected file encoding")
        delimiter:             Optional[str]   = Field(None, description="Detected CSV delimiter character")
        row_count_estimate:    Optional[int]   = Field(None, description="Estimated data row count (excludes header)")
        suggestions:           Optional[dict]  = Field(None, description="Fuzzy-matched canonical-field suggestions {field: csv_header}")
        suggested_date_format: Optional[str]   = Field(None, description="Inferred strptime date format for the transaction date column")
        matched_profile:       Optional[dict]  = Field(None, description="Auto-detected wizard profile (if score ≥ threshold)")
        preprocess_banner:     Optional[str]   = Field(None, description="Dismissible UI info text when non-standard format was auto-cleaned")
        preprocess_metadata:   Optional[dict]  = Field(None, description="Statement metadata extracted from pre-header rows (Pattern 2)")

    class MappingInfo(BaseModel):
        name:    str  = Field(..., description="Mapping key (YAML stem)")
        label:   str  = Field(..., description="Human-readable label")
        path:    str  = Field(..., description="Absolute path on the server")
        example: bool = Field(..., description="True for bundled example files")

    class MappingsResponse(BaseModel):
        mappings: list[MappingInfo]

    class StartRunRequest(BaseModel):
        inputs: list[str] = Field(
            ...,
            description="Server-side file paths returned by POST /upload.",
            examples=[["data/uploads/abc12345_transactions.csv"]],
        )
        mapping_path: Optional[str] = Field(
            None,
            description="Absolute path to a bank mapping YAML (from GET /mappings). "
                        "Provide this OR bank_key or mapping_dict, not multiple.",
        )
        bank_key: Optional[str] = Field(
            None,
            description="Bank key (YAML stem) to auto-locate a mapping. "
                        "Alternative to mapping_path or mapping_dict.",
        )
        mapping_dict: Optional[dict] = Field(
            None,
            description="Inline pipeline mapping dict produced by the wizard. "
                        "Alternative to mapping_path and bank_key.",
        )
        preview_only: bool = Field(
            False,
            description="When true the pipeline stops after validation — data is staged "
                        "but NOT written to the ledger. Call POST /runs/{run_id}/commit "
                        "to finalise, or simply discard.",
        )
        # Feature 1: required to separate credit-card from bank ledger entries
        statement_type: Optional[str] = Field(
            None,
            description="Source type: 'credit_card' or 'bank'. "
                        "Determines which aggregations this data contributes to.",
        )

    # ---- Wizard Pydantic models ------------------------------------------------

    class WizardDetectRequest(BaseModel):
        file_path: str = Field(..., description="Server-side file path returned by POST /upload")

    class WizardValidateRequest(BaseModel):
        canonical_map: dict = Field(
            ...,
            description="Mapping from canonical field names to selected CSV header names. "
                        "Use null/empty-string for unmapped fields.",
        )

    class WizardSaveAndRunRequest(BaseModel):
        file_paths:        list[str]    = Field(..., description="Server-side file paths to process")
        canonical_map:     dict         = Field(..., description="canonical_field → csv_header selections")
        institution:       str          = Field(..., description="Institution name (e.g. 'chase')")
        account_id:        str          = Field(..., description="Account identifier (e.g. 'checking_1234')")
        account_name:      str          = Field("",  description="Human-readable account name")
        bank_name:         str          = Field("",  description="Bank display name")
        profile_name:      str          = Field("default", description="Profile variant name")
        date_format:       Optional[str]= Field(None, description="strptime format, e.g. '%m/%d/%Y'")
        currency_default:  str          = Field("USD")
        drop_columns:      list[str]    = Field(default_factory=list)
        preview_only:      bool         = Field(False)
        custom_headers:    list[str]    = Field(default_factory=list, description="Non-canonical CSV column names to persist in the profile")
        # Feature 1
        statement_type:    Optional[str]= Field(None, description="'credit_card' or 'bank'")

    class RunStartedResponse(BaseModel):
        run_id:  str = Field(..., description="Unique run identifier — poll GET /runs/{run_id} for progress")
        status:  str = Field(..., description="Always 'pending' immediately after creation")

    class RunCounts(BaseModel):
        rows_in:         Optional[int] = None
        rows_staged:     Optional[int] = None
        rows_normalized: Optional[int] = None
        rows_loaded:     Optional[int] = None
        errors_count:    Optional[int] = None

    class RunStatusResponse(BaseModel):
        run_id:      str
        status:      str = Field(
            ...,
            description="One of: pending | running | staged | committing | success | failed | fail",
        )
        started_at:  Optional[str] = None
        finished_at: Optional[str] = None
        files_count: Optional[int] = None
        counts:      Optional[RunCounts] = None
        error:       Optional[str] = None
        staged:      Optional[bool] = Field(
            None,
            description="True when the run is staged in memory and awaiting commit",
        )

    class PreviewRow(BaseModel):
        source_row:            int
        bank_name:             Optional[str] = None
        account_name:          Optional[str] = None
        account_id:            Optional[str] = None
        transaction_date_raw:  Optional[str] = None
        description_raw:       Optional[str] = None
        amount_raw:            Optional[str] = None
        currency_raw:          Optional[str] = None
        merchant:              Optional[str] = None
        category:              Optional[str] = None
        notes:                 Optional[str] = None

    class PreviewResponse(BaseModel):
        run_id:    str
        rows:      list[PreviewRow]
        count:     int  = Field(..., description="Number of rows returned")
        truncated: bool = Field(..., description="True when the result was capped at the limit")

    class CommitResponse(BaseModel):
        run_id:  str
        status:  str

    class ReportsResponse(BaseModel):
        reports: list[str] = Field(..., description="CSV filenames available for download")

    class ChartResponse(BaseModel):
        name: str
        rows: list[dict[str, Any]]

    class CustomReportRequest(BaseModel):
        filters:   list[dict]  = Field(default_factory=list, description="[{field, op, value}]")
        group_by:  list[str]   = Field(default_factory=list, description="Fields to group by")
        bucket:    Optional[str] = Field(None, description="Time bucket for transaction_date: day|week|month|year")
        date_from: Optional[str] = Field(None, description="ISO date lower bound (inclusive)")
        date_to:   Optional[str] = Field(None, description="ISO date upper bound (inclusive)")
        limit:     int           = Field(500, le=2000, description="Max rows (capped at 2000)")

    class SettingsResponse(BaseModel):
        verbose_logs: bool = Field(..., description="Enable verbose API error details in responses")
        show_logs: bool = Field(..., description="Whether the UI should auto-show backend logs panel")

    class SettingsUpdateRequest(BaseModel):
        verbose_logs: Optional[bool] = Field(None, description="Set verbose API error details")
        show_logs: Optional[bool] = Field(None, description="Set UI preference to auto-show logs panel")

    class LogsResponse(BaseModel):
        file: Optional[str] = None
        lines: list[str]

    _PYDANTIC_OK = True

except ImportError:
    _PYDANTIC_OK = False


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

_ALL_DATA_DIRS = [
    "data/db",
    "data/raw",
    "data/uploads",
    "data/reports",
    "data/master",
    "data/profiles",
    "data/validation",
    "data/logs",
]


def _isoformat(v: Any) -> str:
    """Convert date/datetime to ISO string for JSON serialisation."""
    return v.isoformat() if hasattr(v, "isoformat") else v


def _build_report_sql(payload: Any) -> tuple[list, list, list[str]]:
    """
    Build a safe, parameterised SQL query from a custom-report payload.

    Returns (sql, params, column_names).
    Raises ValueError for any unknown field or operator name.
    """
    params: list = []
    where: list[str] = []

    for f in (payload.filters or []):
        field = f.get("field", "")
        op    = f.get("op", "")
        value = f.get("value")
        if field not in _REPORT_FIELDS:
            raise ValueError(f"Invalid filter field: {field!r}")
        if op == "=":
            where.append(f"{field} = ?"); params.append(value)
        elif op == "contains":
            where.append(f"LOWER(CAST({field} AS VARCHAR)) LIKE ?")
            params.append(f"%{str(value).lower()}%")
        elif op == ">=":
            where.append(f"{field} >= ?"); params.append(value)
        elif op == "<=":
            where.append(f"{field} <= ?"); params.append(value)
        elif op == "is_null":
            where.append(f"{field} IS NULL")
        elif op == "not_null":
            where.append(f"{field} IS NOT NULL")
        elif op == "in":
            vals = value if isinstance(value, list) else [value]
            if not vals:
                raise ValueError("'in' operator requires a non-empty list")
            where.append(f"{field} IN ({', '.join('?' * len(vals))})"); params.extend(vals)
        elif op == "between":
            if not isinstance(value, list) or len(value) != 2:
                raise ValueError("'between' operator requires [from, to]")
            where.append(f"{field} BETWEEN ? AND ?"); params.extend(value)
        else:
            raise ValueError(f"Invalid operator: {op!r}")

    if payload.date_from:
        where.append("transaction_date >= ?"); params.append(payload.date_from)
    if payload.date_to:
        where.append("transaction_date <= ?"); params.append(payload.date_to)

    group_fields = [f for f in (getattr(payload, "group_by", None) or []) if f in _REPORT_FIELDS]
    safe_bucket  = (getattr(payload, "bucket", None) or "")
    safe_bucket  = safe_bucket if safe_bucket in _REPORT_BUCKETS else None

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    if group_fields:
        sel, grp, col_names = [], [], []
        for field in group_fields:
            if field == "transaction_date" and safe_bucket:
                expr = f"date_trunc('{safe_bucket}', transaction_date)"
                sel.append(f"{expr} AS transaction_date")
                grp.append(expr)
            else:
                sel.append(field); grp.append(field)
            col_names.append(field)
        # Feature 3: Replaced definitions (old sign-filtered versions deleted)
        # total_spend  = gross signed sum of ALL amounts (no sign filtering)
        # total_income = sum of inflows only (bank context; always >= 0)
        # net_amount   = total_income − |outflows|  (null-safe via COALESCE)
        _ns = "COALESCE(amount, 0)"
        sel += [
            "COUNT(*) AS row_count",
            f"SUM({_ns}) AS total_spend",
            f"SUM(CASE WHEN {_ns} > 0 THEN {_ns} ELSE 0 END) AS total_income",
            (f"SUM(CASE WHEN {_ns} > 0 THEN {_ns} ELSE 0 END)"
             f" - ABS(SUM(CASE WHEN {_ns} < 0 THEN {_ns} ELSE 0 END)) AS net_amount"),
        ]
        col_names += ["row_count", "total_spend", "total_income", "net_amount"]
        sql = (f"SELECT {', '.join(sel)} FROM transactions_norm{where_sql}"
               f" GROUP BY {', '.join(grp)} ORDER BY 1")
    else:
        col_names = [
            "transaction_date", "description", "merchant", "category",
            "amount", "currency", "bank_name", "account_name", "account_id",
        ]
        sql = f"SELECT {', '.join(col_names)} FROM transactions_norm{where_sql} ORDER BY transaction_date DESC"

    limit = max(1, min(int(getattr(payload, "limit", 500)), 2000))
    sql += f" LIMIT {limit}"
    return sql, params, col_names


def create_app(
    db_path:            str = "data/db/finance.duckdb",
    mappings_dir:       str = "config/mappings",
    reports_dir:        str = "data/reports",
    upload_dir:         str = "data/uploads",
    wizard_profiles_dir: str = "config/wizard_profiles",
):
    try:
        from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import FileResponse, HTMLResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as e:
        raise RuntimeError("fastapi is required for API mode. Install finance_etl.") from e

    # Verify python-multipart is installed — fail fast with a clear message
    try:
        import multipart  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "python-multipart is required for file uploads. "
            "Rebuild the Docker image or run: pip install python-multipart"
        )

    from finance_etl.db import get_connection
    from finance_etl.pipeline import (
        chart_from_report_csv,
        commit_run,
        get_run_status,
        run_with_options,
    )

    # -----------------------------------------------------------------------
    # Lifespan — runs on startup to guarantee the DB and all dirs exist
    # -----------------------------------------------------------------------

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Create every data directory the app will ever write to
        for d in _ALL_DATA_DIRS:
            Path(d).mkdir(parents=True, exist_ok=True)
        Path(upload_dir).mkdir(parents=True, exist_ok=True)
        Path(reports_dir).mkdir(parents=True, exist_ok=True)
        Path(mappings_dir).mkdir(parents=True, exist_ok=True)
        Path(wizard_profiles_dir).mkdir(parents=True, exist_ok=True)

        # ------------------------------------------------------------------
        # Attach a persistent file handler to the API logger so that upload
        # errors and other API-level events are captured in data/logs/api.log
        # and become visible via GET /logs even before any pipeline run.
        # ------------------------------------------------------------------
        import logging as _logging
        _api_log_path = Path("data/logs") / "api.log"
        _api_logger = _logging.getLogger("finance_etl.api")
        _api_logger.setLevel(_logging.DEBUG)
        if not any(
            isinstance(h, _logging.FileHandler) and
            getattr(h, "baseFilename", None) == str(_api_log_path.resolve())
            for h in _api_logger.handlers
        ):
            _fmt = _logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            # Stream handler (INFO+) for console output
            if not any(isinstance(h, _logging.StreamHandler) and not isinstance(h, _logging.FileHandler)
                       for h in _api_logger.handlers):
                _ch = _logging.StreamHandler()
                _ch.setLevel(_logging.INFO)
                _ch.setFormatter(_fmt)
                _api_logger.addHandler(_ch)
            # File handler (DEBUG+) writes every API event to api.log
            _fh = _logging.FileHandler(_api_log_path, encoding="utf-8")
            _fh.setLevel(_logging.DEBUG)
            _fh.setFormatter(_fmt)
            _api_logger.addHandler(_fh)
            _api_logger.info("finance_etl API started — log file: %s", _api_log_path)

        # Bootstrap the DB schema so the first GET /runs never fails
        try:
            conn = get_connection(db_path)
            conn.close()
        except Exception as exc:
            import logging
            logging.getLogger("finance_etl.api").warning("DB bootstrap warning: %s", exc)

        yield  # app is running
        # (nothing to clean up on shutdown)

    # -----------------------------------------------------------------------
    # App + metadata
    # -----------------------------------------------------------------------

    app = FastAPI(
        title="finance_etl",
        version="2.0.0",
        description="""
## finance_etl API

A **fully local, deterministic** ETL pipeline for bank and credit-card transaction CSVs.
No cloud services, no external dependencies — all data stays on your machine.

---

### Typical import workflow

| Step | Endpoint | Description |
|------|----------|-------------|
| 1 | `POST /upload` | Upload your bank CSV |
| 2 | `GET /mappings` | Find your bank's column mapping |
| 3 | `POST /runs` | Start the pipeline (set `preview_only: true` to review first) |
| 4 | `GET /runs/{run_id}` | Poll for status until `success` or `staged` |
| 5 | `GET /runs/{run_id}/preview` | Inspect staged rows before committing *(optional)* |
| 6 | `POST /runs/{run_id}/commit` | Load staged data to the ledger *(if preview_only was used)* |
| 7 | `GET /reports` | List generated analytics reports |
| 8 | `GET /charts/{name}` | Get a report as JSON rows for display |

---

### Run status values

| Status | Meaning |
|--------|---------|
| `pending` | Queued, not yet started |
| `running` | Pipeline is processing |
| `staged` | Validated and ready — awaiting `POST /runs/{id}/commit` |
| `committing` | Commit in progress |
| `success` | Fully loaded to ledger, analytics generated |
| `failed` | Pipeline or commit error — check the `error` field |
""",
        contact={
            "name": "finance_etl on GitHub",
            "url": "https://github.com/mj-santos/TransactionAnalysis",
        },
        license_info={
            "name": "MIT",
        },
        openapi_tags=[
            {"name": "files",    "description": "Upload CSV files before starting a run."},
            {"name": "wizard",   "description": "Mapping wizard — detect headers, validate, save profiles, run."},
            {"name": "mappings", "description": "Bank column-mapping configurations (YAML files)."},
            {"name": "runs",     "description": "Import pipeline runs — create, monitor, preview, and commit."},
            {"name": "reports",  "description": "Analytics reports generated after each successful run."},
            {"name": "ui",       "description": "Web UI entry point."},
        ],
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.ui_settings = {
        "verbose_logs": False,
        "show_logs": False,
    }

    def _logs_path() -> Path:
        return Path("data/logs")

    def _tail_latest_log_lines(limit: int = 200) -> tuple[str | None, list[str]]:
        log_dir = _logs_path()
        if not log_dir.exists():
            return None, []
        files = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return None, []
        latest = files[0]
        with open(latest, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return latest.name, [ln.rstrip("\n") for ln in lines[-max(1, min(limit, 1000)):]]

    # -----------------------------------------------------------------------
    # Background task helpers
    # -----------------------------------------------------------------------

    def _run_bg(run_id: str, inputs: list, mapping_path, bank_key, preview_only: bool,
                mapping_dict=None, statement_type=None):
        _async_runs[run_id] = {"status": "running", "run_id": run_id}
        try:
            result = run_with_options(
                inputs=inputs,
                db_path=db_path,
                mappings_dir=mappings_dir,
                mapping_path=mapping_path,
                bank_key=bank_key,
                mapping_dict=mapping_dict,
                reports_dir=reports_dir,
                preview_only=preview_only,
                run_id=run_id,
                statement_type=statement_type,  # Feature 1
            )
            status = "staged" if preview_only else "success"
            _async_runs[run_id] = {
                "status": status,
                "run_id": result.run_id,
                "counts": result.counts,
            }
        except Exception as exc:
            _async_runs[run_id] = {"status": "failed", "run_id": run_id, "error": str(exc)}

    def _commit_bg(run_id: str):
        _async_runs[run_id] = {"status": "committing", "run_id": run_id}
        try:
            result = commit_run(run_id)
            _async_runs[run_id] = {
                "status": "success",
                "run_id": result.run_id,
                "counts": result.counts,
            }
        except Exception as exc:
            _async_runs[run_id] = {"status": "failed", "run_id": run_id, "error": str(exc)}

    # -----------------------------------------------------------------------
    # Files
    # -----------------------------------------------------------------------

    @app.post(
        "/upload",
        tags=["files"],
        summary="Upload a CSV file",
        response_model=UploadResponse if _PYDANTIC_OK else None,
    )
    async def upload_file(file: UploadFile = File(..., description="Bank export CSV file")):
        """
        Upload a CSV file to the server.

        Returns the **server-side `path`** — pass this value as an item in `inputs`
        when calling `POST /runs`.

        Supported formats: any CSV dialect (comma, semicolon, tab-separated).
        Encoding is auto-detected (UTF-8, Latin-1, Windows-1252, etc.).
        """
        try:
            dest_dir = Path(upload_dir)
            dest_dir.mkdir(parents=True, exist_ok=True)
            safe_original = Path(file.filename or "uploaded.csv").name
            safe_name = f"{uuid.uuid4().hex[:8]}_{safe_original}"
            dest = dest_dir / safe_name
            content = await file.read()
            if not content:
                raise HTTPException(status_code=400, detail="Uploaded file is empty.")
            dest.write_bytes(content)

            # --- Smart CSV pre-processing (Pattern 1 + Pattern 2) ---
            preprocess_result: dict = {"patterns_applied": [], "metadata": {}, "banner": None}
            try:
                from finance_etl.utils.csv_preprocess import preprocess_csv
                preprocess_result = preprocess_csv(dest)
                if preprocess_result.get("patterns_applied"):
                    import logging as _logging
                    _logging.getLogger("finance_etl.api").info(
                        "CSV pre-processing applied to %s: %s",
                        safe_original, preprocess_result["patterns_applied"],
                    )
            except Exception as pp_exc:
                import logging as _logging
                _logging.getLogger("finance_etl.api").warning(
                    "CSV pre-processing failed (non-fatal) for %s: %s", safe_original, pp_exc
                )

            # --- Extract headers + suggestions (from the cleaned file) ---
            try:
                from finance_etl.wizard_mapping import extract_csv_headers, find_matching_profile
                header_info = extract_csv_headers(dest)
                matched = find_matching_profile(
                    header_info["headers"],
                    Path(wizard_profiles_dir),
                )
                # Omit full profile data from matched to keep response lean
                matched_summary = None
                if matched:
                    matched_summary = {
                        "score":        matched["score"],
                        "institution":  matched["institution"],
                        "account_id":   matched["account_id"],
                        "account_name": matched["account_name"],
                        "bank_name":    matched["bank_name"],
                        "profile_name": matched["profile_name"],
                        "suggested_mapping": matched.get("suggested_mapping"),
                    }
            except Exception:
                header_info = {"headers": [], "sample_rows": [], "encoding": None,
                               "delimiter": None, "row_count_estimate": None, "suggestions": None}
                matched_summary = None

            return {
                "filename":              safe_original,
                "path":                  str(dest),
                "size":                  len(content),
                "headers":               header_info.get("headers", []),
                "sample_rows":           header_info.get("sample_rows", []),
                "encoding":              header_info.get("encoding"),
                "delimiter":             header_info.get("delimiter"),
                "row_count_estimate":    header_info.get("row_count_estimate"),
                "suggestions":           header_info.get("suggestions"),
                "suggested_date_format": header_info.get("suggested_date_format"),
                "matched_profile":       matched_summary,
                "preprocess_banner":     preprocess_result.get("banner"),
                "preprocess_metadata":   preprocess_result.get("metadata") or {},
            }
        except HTTPException:
            raise
        except Exception as exc:
            import logging
            logging.getLogger("finance_etl.api").exception("Upload failed: %s", exc)
            detail = f"Upload failed: {exc}" if app.state.ui_settings.get("verbose_logs") else "Upload failed due to a server error. Enable verbose logs in Settings to see details."
            raise HTTPException(status_code=500, detail=detail) from exc

    # -----------------------------------------------------------------------
    # Mappings
    # -----------------------------------------------------------------------

    @app.get(
        "/mappings",
        tags=["mappings"],
        summary="List available bank mappings",
        response_model=MappingsResponse if _PYDANTIC_OK else None,
    )
    def list_mappings():
        """
        Return all bank mapping YAML files found in the mappings directory.

        Each mapping tells the pipeline how to interpret a specific bank's CSV export:
        which column is the date, which is the amount, what format the amounts use, etc.

        To add your own bank:
        1. Copy `config/mappings/example_signed_amount.yaml` to `config/mappings/mybank.yaml`
        2. Edit the column names and date format to match your bank's export
        3. Restart the API (or wait — mappings are re-read on each run)
        """
        base = Path(mappings_dir)
        if not base.exists():
            return {"mappings": []}
        results = []
        for f in sorted(base.rglob("*.yaml")):
            results.append({
                "name":    f.stem,
                "label":   f.stem.replace("_", " ").title(),
                "path":    str(f),
                "example": f.stem.startswith("example_"),
            })
        return {"mappings": results}

    # -----------------------------------------------------------------------
    # Runs
    # -----------------------------------------------------------------------

    @app.get(
        "/runs",
        tags=["runs"],
        summary="List all import runs",
    )
    def list_runs():
        """
        Return all import runs ordered by most recent first (up to 200).

        In-flight runs (pending/running/committing) show their live status from memory;
        completed runs are read from the database.
        """
        try:
            conn = get_connection(db_path, read_only=True)
            rows = conn.execute(
                """
                SELECT run_id, started_at, finished_at, status,
                       files_count, rows_in, rows_staged,
                       rows_normalized, rows_loaded, errors_count
                FROM runs
                ORDER BY started_at DESC
                LIMIT 200
                """
            ).fetchall()
            conn.close()
        except Exception:
            return {"runs": []}

        cols = [
            "run_id", "started_at", "finished_at", "status",
            "files_count", "rows_in", "rows_staged",
            "rows_normalized", "rows_loaded", "errors_count",
        ]
        runs = [dict(zip(cols, r)) for r in rows]

        for run in runs:
            live = _async_runs.get(run["run_id"])
            if live and live["status"] in ("pending", "running", "committing"):
                run["status"] = live["status"]

        return {"runs": runs}

    @app.post(
        "/runs",
        tags=["runs"],
        summary="Start an import run",
        response_model=RunStartedResponse if _PYDANTIC_OK else None,
        status_code=202,
    )
    async def start_run(payload: StartRunRequest, background_tasks: BackgroundTasks):
        """
        Start a new ETL pipeline run asynchronously.

        The endpoint returns immediately with a `run_id`.
        Poll `GET /runs/{run_id}` until status is `success`, `staged`, or `failed`.

        **Preview workflow** (`preview_only: true`):
        - Pipeline runs through ingest → profile → map → normalize → validate
        - Stops before writing to the ledger
        - Status becomes `staged`
        - Call `GET /runs/{run_id}/preview` to inspect the rows
        - Call `POST /runs/{run_id}/commit` to finalise

        **Direct workflow** (`preview_only: false`, default):
        - Full pipeline runs end-to-end
        - Status becomes `success` when done
        - Analytics reports are generated automatically
        """
        if not payload.inputs:
            raise HTTPException(status_code=400, detail="inputs must contain at least one file path.")
        if not payload.mapping_path and not payload.bank_key and not payload.mapping_dict:
            raise HTTPException(status_code=400, detail="Provide mapping_path, bank_key, or mapping_dict.")

        run_id = uuid.uuid4().hex[:16]
        _async_runs[run_id] = {"status": "pending", "run_id": run_id}

        background_tasks.add_task(
            _run_bg,
            run_id,
            payload.inputs,
            payload.mapping_path,
            payload.bank_key,
            payload.preview_only,
            payload.mapping_dict,
            getattr(payload, "statement_type", None),  # Feature 1
        )
        return {"run_id": run_id, "status": "pending"}

    @app.get(
        "/runs/{run_id}",
        tags=["runs"],
        summary="Get run status",
        response_model=RunStatusResponse if _PYDANTIC_OK else None,
    )
    def run_status(run_id: str):
        """
        Return the current status and row counts for a run.

        Check the `status` field:
        - **pending / running / committing** — still in progress, keep polling
        - **staged** — stopped before ledger load; call `POST /runs/{run_id}/commit`
        - **success** — fully complete, reports are available
        - **failed** — check the `error` field for the reason
        """
        live = _async_runs.get(run_id)
        if live and live["status"] in ("pending", "running", "committing"):
            return live

        try:
            return get_run_status(db_path, run_id)
        except KeyError:
            if live:
                return live
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")

    @app.get(
        "/runs/{run_id}/preview",
        tags=["runs"],
        summary="Preview staged transactions",
        response_model=PreviewResponse if _PYDANTIC_OK else None,
    )
    def run_preview(
        run_id: str,
        limit: int = Query(200, description="Maximum rows to return (default 200)"),
    ):
        """
        Return the raw staged rows for a run so you can review them before committing.

        Available for **any** run (not just `preview_only`) — useful for auditing what
        was processed in a completed run.

        Results are capped at `limit` rows. If `truncated: true` is returned, there are
        more rows than shown.
        """
        try:
            conn = get_connection(db_path, read_only=True)
            rows = conn.execute(
                """
                SELECT source_row, bank_name, account_name, account_id,
                       transaction_date_raw, description_raw,
                       amount_raw, currency_raw, extra_json
                FROM transactions_stage
                WHERE run_id = ?
                ORDER BY source_row
                LIMIT ?
                """,
                [run_id, limit],
            ).fetchall()
            conn.close()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        cols = [
            "source_row", "bank_name", "account_name", "account_id",
            "transaction_date_raw", "description_raw",
            "amount_raw", "currency_raw", "extra_json",
        ]
        row_dicts = []
        for r in rows:
            d = dict(zip(cols, r))
            try:
                extra = json.loads(d.pop("extra_json") or "{}")
            except Exception:
                extra = {}
                d.pop("extra_json", None)
            for k in ("merchant", "category", "notes"):
                v = (extra.get(k) or "").strip()
                if v:
                    d[k] = v
            row_dicts.append(d)
        return {
            "run_id":    run_id,
            "rows":      row_dicts,
            "count":     len(row_dicts),
            "truncated": len(row_dicts) == limit,
        }

    @app.post(
        "/runs/{run_id}/commit",
        tags=["runs"],
        summary="Commit a staged run to the ledger",
        response_model=CommitResponse if _PYDANTIC_OK else None,
        status_code=202,
    )
    async def commit_run_endpoint(run_id: str, background_tasks: BackgroundTasks):
        """
        Load a `staged` run's validated transactions into the ledger and
        generate analytics reports.

        Only valid when `GET /runs/{run_id}` returns `status: "staged"`.
        The commit runs asynchronously — poll `GET /runs/{run_id}` until
        status becomes `success` or `failed`.

        Returns `409 Conflict` if the run is not in staged state
        (already committed, never staged, or the server was restarted).
        """
        from finance_etl.pipeline import _staged_runs
        if run_id not in _staged_runs:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Run '{run_id}' is not in staged state. "
                    "It may have already been committed, never staged, or the server was restarted."
                ),
            )
        _async_runs[run_id] = {"status": "committing", "run_id": run_id}
        background_tasks.add_task(_commit_bg, run_id)
        return {"run_id": run_id, "status": "committing"}

    @app.delete(
        "/runs/{run_id}",
        tags=["runs"],
        summary="Delete an import run and its data",
    )
    def delete_run(
        run_id: str,
        keep_transactions: bool = Query(
            False,
            description="Set true to keep loaded transactions in transactions_norm; "
                        "by default they are also removed.",
        ),
    ):
        """
        Delete an import run record, its staged rows, and (by default) any
        transactions loaded from that run.

        Passing `keep_transactions=true` removes only the run record and staged
        rows while leaving transactions_norm untouched (useful when the same file
        was imported multiple times and you only want to remove one run entry).
        """
        conn = get_connection(db_path)
        try:
            if not keep_transactions:
                file_hashes = [
                    r[0] for r in conn.execute(
                        "SELECT DISTINCT file_hash FROM transactions_stage WHERE run_id = ?",
                        [run_id],
                    ).fetchall()
                ]
                if file_hashes:
                    placeholders = ", ".join("?" * len(file_hashes))
                    conn.execute(
                        f"DELETE FROM transactions_norm WHERE file_hash IN ({placeholders})",
                        file_hashes,
                    )
            conn.execute("DELETE FROM transactions_stage WHERE run_id = ?", [run_id])
            conn.execute("DELETE FROM runs WHERE run_id = ?", [run_id])
            _async_runs.pop(run_id, None)
            from finance_etl.pipeline import _staged_runs
            _staged_runs.pop(run_id, None)
            return {"deleted": True, "run_id": run_id}
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # Wizard — header detection, mapping validation, save-and-run
    # -----------------------------------------------------------------------

    @app.post(
        "/wizard/detect",
        tags=["wizard"],
        summary="Detect CSV headers and find matching mapping profile",
    )
    def wizard_detect(payload: WizardDetectRequest):
        """
        Given a server-side CSV file path, extract its headers and attempt to
        find an existing wizard mapping profile that matches them.

        Returns:
        - `headers`: list of detected column names
        - `sample_rows`: first 5 data rows
        - `encoding` / `delimiter`: detected CSV dialect
        - `suggestions`: fuzzy-matched {canonical_field: csv_header} hints
        - `matched_profile`: best-matching saved profile (score ≥ 0.6), or null
        - `canonical_fields`: ordered list of all mappable canonical field names
        - `canonical_labels`: human-readable label per canonical field
        """
        from finance_etl.wizard_mapping import (
            CANONICAL_FIELDS,
            CANONICAL_LABELS,
            extract_csv_headers,
            find_matching_profile,
        )
        file_path = Path(payload.file_path)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {payload.file_path}")
        try:
            info = extract_csv_headers(file_path)
            matched = find_matching_profile(info["headers"], Path(wizard_profiles_dir))
            matched_out = None
            if matched:
                matched_out = {
                    "score":             matched["score"],
                    "institution":       matched["institution"],
                    "account_id":        matched["account_id"],
                    "account_name":      matched["account_name"],
                    "bank_name":         matched["bank_name"],
                    "profile_name":      matched["profile_name"],
                    "suggested_mapping": matched.get("suggested_mapping"),
                    "custom_headers":    (matched.get("profile") or {}).get("custom_headers", []),
                }
            return {
                **info,
                "matched_profile":  matched_out,
                "canonical_fields": CANONICAL_FIELDS,
                "canonical_labels": CANONICAL_LABELS,
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post(
        "/wizard/validate",
        tags=["wizard"],
        summary="Validate a wizard mapping selection",
    )
    def wizard_validate(payload: WizardValidateRequest):
        """
        Validate that a canonical field mapping satisfies minimum pipeline requirements:
        - `transaction_date` must be mapped
        - At least one amount group must be fully covered

        Returns `{ok: true}` or `{ok: false, errors: [...]}`.
        """
        from finance_etl.wizard_mapping import validate_wizard_mapping
        errors = validate_wizard_mapping(payload.canonical_map)
        if errors:
            raise HTTPException(status_code=422, detail={"ok": False, "errors": errors})
        return {"ok": True, "errors": []}

    @app.post(
        "/wizard/save-and-run",
        tags=["wizard"],
        summary="Save wizard mapping profile and start the pipeline",
        status_code=202,
    )
    async def wizard_save_and_run(
        payload: WizardSaveAndRunRequest,
        background_tasks: BackgroundTasks,
    ):
        """
        1. Validate the canonical_map.
        2. Merge/append new header aliases into the wizard profile YAML (additive).
        3. Convert selections to a pipeline-compatible mapping dict.
        4. Start the pipeline run (preview_only or full).

        On subsequent uploads the merged YAML will auto-match and pre-fill the wizard.
        """
        from finance_etl.wizard_mapping import (
            infer_amount_mode,
            load_wizard_profile,
            merge_wizard_profile,
            save_wizard_profile,
            validate_wizard_mapping,
            wizard_to_pipeline_mapping,
        )

        if not payload.file_paths:
            raise HTTPException(status_code=400, detail="file_paths must contain at least one path.")

        # Validate mapping
        errors = validate_wizard_mapping(payload.canonical_map)
        if errors:
            raise HTTPException(status_code=422, detail={"ok": False, "errors": errors})

        # Resolve date_format: use the user-provided value, or auto-detect from
        # the first uploaded file's date column so ambiguous dates (e.g. 01/05/2024)
        # don't fail the pipeline when the user leaves the field blank.
        date_format = payload.date_format or None
        if not date_format and payload.file_paths:
            date_col = payload.canonical_map.get("transaction_date")
            if date_col:
                try:
                    from finance_etl.wizard_mapping import detect_date_format, extract_csv_headers
                    _info = extract_csv_headers(Path(payload.file_paths[0]))
                    _date_values = [
                        row.get(date_col, "") for row in _info.get("sample_rows", [])
                    ]
                    date_format = detect_date_format(_date_values)
                except Exception:
                    pass

        # Merge wizard profile (additive)
        try:
            profiles_path = Path(wizard_profiles_dir)
            existing = load_wizard_profile(profiles_path, payload.institution, payload.account_id)
            amount_mode = infer_amount_mode(payload.canonical_map)
            merged = merge_wizard_profile(
                existing=existing,
                institution=payload.institution,
                account_id=payload.account_id,
                account_name=payload.account_name,
                bank_name=payload.bank_name,
                profile_name=payload.profile_name,
                canonical_map=payload.canonical_map,
                amount_mode=amount_mode,
                date_format=date_format,
                currency_default=payload.currency_default,
                drop_columns=payload.drop_columns,
                custom_headers=payload.custom_headers or None,
            )
            saved_path = save_wizard_profile(profiles_path, merged)
        except Exception as exc:
            import logging
            logging.getLogger("finance_etl.api").exception("Wizard profile save failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to save mapping profile: {exc}") from exc

        # Build inline pipeline mapping dict
        bank_key = re.sub(r"[^a-z0-9_]", "_",
                          f"{payload.institution}_{payload.account_id}".lower())
        mapping_dict = wizard_to_pipeline_mapping(
            canonical_map=payload.canonical_map,
            bank_name=payload.bank_name or payload.institution,
            bank_key=bank_key,
            account_name=payload.account_name,
            account_id=payload.account_id,
            date_format=date_format,
            currency_default=payload.currency_default,
            drop_columns=payload.drop_columns,
        )

        # Kick off pipeline run
        run_id = uuid.uuid4().hex[:16]
        _async_runs[run_id] = {"status": "pending", "run_id": run_id}
        background_tasks.add_task(
            _run_bg,
            run_id,
            payload.file_paths,
            None,           # mapping_path
            None,           # bank_key
            payload.preview_only,
            mapping_dict,   # mapping_dict
            getattr(payload, "statement_type", None),  # Feature 1
        )
        return {
            "run_id":       run_id,
            "status":       "pending",
            "profile_path": str(saved_path),
        }

    @app.get(
        "/wizard/profiles",
        tags=["wizard"],
        summary="List saved wizard mapping profiles",
    )
    def wizard_list_profiles():
        """Return all saved wizard profile summaries for the UI profile picker."""
        from finance_etl.wizard_mapping import list_wizard_profiles
        return {"profiles": list_wizard_profiles(Path(wizard_profiles_dir))}

    # -----------------------------------------------------------------------
    # Settings + Logs
    # -----------------------------------------------------------------------

    @app.get(
        "/settings",
        tags=["ui"],
        summary="Get UI/debug settings",
        response_model=SettingsResponse if _PYDANTIC_OK else None,
    )
    def get_settings():
        return dict(app.state.ui_settings)

    @app.patch(
        "/settings",
        tags=["ui"],
        summary="Update UI/debug settings",
        response_model=SettingsResponse if _PYDANTIC_OK else None,
    )
    def patch_settings(payload: SettingsUpdateRequest):
        if payload.verbose_logs is not None:
            app.state.ui_settings["verbose_logs"] = bool(payload.verbose_logs)
        if payload.show_logs is not None:
            app.state.ui_settings["show_logs"] = bool(payload.show_logs)
        return dict(app.state.ui_settings)

    @app.get(
        "/logs",
        tags=["ui"],
        summary="Read latest backend log lines",
        response_model=LogsResponse if _PYDANTIC_OK else None,
    )
    def read_logs(limit: int = Query(200, description="Maximum log lines to return")):
        file_name, lines = _tail_latest_log_lines(limit)
        return {"file": file_name, "lines": lines}

    @app.get(
        "/logs/download",
        tags=["ui"],
        summary="Download the latest backend log file",
        include_in_schema=True,
    )
    def download_logs():
        """
        Download the most recently modified log file from data/logs/ as a
        plain-text attachment.  Useful for sharing error details for support.

        Returns 404 when no log files exist yet (i.e. before the first run
        or API startup with logging enabled).
        """
        file_name, _ = _tail_latest_log_lines(limit=1)
        if not file_name:
            raise HTTPException(status_code=404, detail="No log files available yet.")
        log_path = _logs_path() / file_name
        if not log_path.exists():
            raise HTTPException(status_code=404, detail="Log file not found on disk.")
        return FileResponse(
            path=str(log_path),
            media_type="text/plain",
            filename=file_name,
            headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
        )

    # -----------------------------------------------------------------------
    # Transactions — Feature 4: Credit Cards & Bank Transactions tabs
    # -----------------------------------------------------------------------

    @app.get(
        "/transactions/sources",
        tags=["transactions"],
        summary="List import sources (runs) for a given statement type",
    )
    def list_transaction_sources(
        type: Optional[str] = Query(None, description="'credit_card' or 'bank'"),
    ):
        """
        Return the distinct import runs that have committed transactions for the
        given statement type.  Used to populate the Import Source dropdown.

        Feature 1: type filter strictly scopes sources — credit_card runs never
        appear in bank results and vice versa.
        Only runs with status 'success' or 'staged' are returned.
        Ordered by started_at DESC (newest import first).

        Response: {"type": str, "sources": [{"id", "label", "date", "count"}]}
        """
        # BUG FIX: status filter must always be inside a WHERE clause.
        # Previously: {where_sql} followed by bare "AND r.status IN ..." which
        # produced invalid SQL when where_sql was empty (no type param given).
        # Fix: include status in the same where list so the clause is always valid.
        where, params = [], []
        where.append("r.status IN ('success', 'staged')")   # always required
        if type in ("bank", "credit_card"):
            where.append("tn.statement_type = ?"); params.append(type)

        where_sql = "WHERE " + " AND ".join(where)

        sql = f"""
            SELECT
                r.run_id AS id,
                COALESCE(r.run_label, r.run_id) AS label,
                r.started_at AS date,
                COUNT(tn.transaction_fingerprint) AS count
            FROM transactions_norm tn
            JOIN runs r ON tn.run_id = r.run_id
            {where_sql}
            GROUP BY r.run_id, r.run_label, r.started_at
            ORDER BY r.started_at DESC
        """
        try:
            conn = get_connection(db_path)
            rows = conn.execute(sql, params).fetchall()
            conn.close()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Sources query failed: {exc}") from exc

        sources = [
            {
                "id":    r[0],
                "label": r[1],
                "date":  _isoformat(r[2]) if r[2] and hasattr(r[2], "isoformat") else str(r[2] or ""),
                "count": int(r[3] or 0),
            }
            for r in rows
        ]
        return {"type": type, "sources": sources}

    def _build_txn_where(
        type, date_from, date_to, account, category, merchant, source
    ) -> tuple[list, list]:
        """Build shared WHERE clause + params for /transactions and /transactions/totals."""
        where, params = [], []
        # Feature 1: HARD isolation — credit_card ≠ bank, never mixed
        if type in ("bank", "credit_card"):
            where.append("statement_type = ?"); params.append(type)

        if date_from:
            where.append("transaction_date >= ?"); params.append(date_from)
        if date_to:
            where.append("transaction_date <= ?"); params.append(date_to)
        if account:
            where.append("(account_name = ? OR account_id = ?)"); params.extend([account, account])
        if category:
            where.append("LOWER(COALESCE(category, '')) LIKE ?")
            params.append(f"%{category.lower()}%")
        if merchant:
            where.append("LOWER(COALESCE(merchant, description)) LIKE ?")
            params.append(f"%{merchant.lower()}%")
        # source filter: specific run_id; 'all' or absent → no additional filter
        if source and source != "all":
            where.append("run_id = ?"); params.append(source)
        return where, params

    @app.get("/transactions", tags=["transactions"], summary="List transactions with filters")
    def list_transactions(
        type:      Optional[str] = Query(None,  description="'credit_card' or 'bank'"),
        limit:     int           = Query(50,    le=500,  description="Max rows"),
        offset:    int           = Query(0,              description="Pagination offset"),
        date_from: Optional[str] = Query(None,           description="ISO date lower bound"),
        date_to:   Optional[str] = Query(None,           description="ISO date upper bound"),
        account:   Optional[str] = Query(None,           description="Account name or ID filter"),
        category:  Optional[str] = Query(None,           description="Category substring filter"),
        merchant:  Optional[str] = Query(None,           description="Merchant/description substring"),
        source:    Optional[str] = Query(None,           description="run_id to filter by import source; 'all' = no filter"),
        group_by:  Optional[str] = Query(None,           description="Comma-separated field(s) to group"),
        sort_by:   str           = Query("transaction_date", description="Column to sort by"),
        sort_dir:  str           = Query("desc",          description="'asc' or 'desc'"),
    ):
        """
        Filtered transaction list.

        Feature 1: Credit-card aggregations never include bank rows and vice versa.
        Pass `type=credit_card` or `type=bank` to scope.
        Pass `source=<run_id>` to filter by a specific import; omit or pass `source=all`
        to show all rows for the given type.
        """
        where, params = _build_txn_where(type, date_from, date_to, account, category, merchant, source)

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        group_fields = [f.strip() for f in (group_by or "").split(",")
                        if f.strip() in _REPORT_FIELDS]
        safe_sort  = sort_by  if sort_by  in _SORT_FIELDS else "transaction_date"
        safe_dir   = sort_dir if sort_dir in ("asc", "desc") else "desc"
        safe_limit = max(1, min(int(limit), 500))

        _ns = "COALESCE(amount, 0)"
        try:
            conn = get_connection(db_path)
            if group_fields:
                # Feature 3 aggregations
                sel = list(group_fields) + [
                    "COUNT(*) AS row_count",
                    f"SUM({_ns}) AS total_spend",
                    f"SUM(CASE WHEN {_ns} > 0 THEN {_ns} ELSE 0 END) AS total_income",
                    (f"SUM(CASE WHEN {_ns} > 0 THEN {_ns} ELSE 0 END)"
                     f" - ABS(SUM(CASE WHEN {_ns} < 0 THEN {_ns} ELSE 0 END)) AS net_amount"),
                ]
                grp_sql = ", ".join(group_fields)
                sql = (f"SELECT {', '.join(sel)} FROM transactions_norm{where_sql}"
                       f" GROUP BY {grp_sql} ORDER BY 1 {safe_dir}"
                       f" LIMIT {safe_limit} OFFSET {offset}")
                col_names = group_fields + ["row_count", "total_spend", "total_income", "net_amount"]
            else:
                col_names = [
                    "transaction_date", "description", "merchant", "category",
                    "amount", "currency", "bank_name", "account_name", "account_id",
                    "statement_type",
                ]
                sql = (f"SELECT {', '.join(col_names)} FROM transactions_norm{where_sql}"
                       f" ORDER BY {safe_sort} {safe_dir}"
                       f" LIMIT {safe_limit} OFFSET {offset}")
            rows_raw = conn.execute(sql, params).fetchall()
            conn.close()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Query error: {exc}") from exc

        rows = [
            {col_names[i]: (_isoformat(r[i]) if hasattr(r[i], "isoformat") else r[i])
             for i in range(len(col_names))}
            for r in rows_raw
        ]
        return {"columns": col_names, "rows": rows, "count": len(rows), "offset": offset}

    @app.get(
        "/transactions/totals",
        tags=["transactions"],
        summary="Aggregated totals for a filtered transaction set",
    )
    def transaction_totals(
        type:      Optional[str] = Query(None,  description="'credit_card' or 'bank'"),
        date_from: Optional[str] = Query(None),
        date_to:   Optional[str] = Query(None),
        account:   Optional[str] = Query(None),
        category:  Optional[str] = Query(None),
        merchant:  Optional[str] = Query(None),
        source:    Optional[str] = Query(None,  description="run_id to filter by import source; 'all' = no filter"),
    ):
        """
        Return aggregate totals for the filtered set (without fetching all rows).

        Feature 1: type filter isolates credit_card from bank — never combined.
        Feature 3 definitions:
          total_spend   = gross signed sum (all amounts, no sign filter)
          total_income  = sum of inflows (bank context)
          total_outflow = absolute sum of outflows
          net_amount    = total_income − total_outflow
        Division-by-zero safety: SUM returns NULL for empty sets → COALESCE to 0.
        source: specific run_id to scope to one import; omit or 'all' for all rows.
        """
        where, params = _build_txn_where(type, date_from, date_to, account, category, merchant, source)

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        _ns = "COALESCE(amount, 0)"
        sql = f"""
            SELECT
              COUNT(*) AS row_count,
              SUM({_ns}) AS total_spend,
              SUM(CASE WHEN {_ns} > 0 THEN {_ns} ELSE 0 END) AS total_income,
              ABS(SUM(CASE WHEN {_ns} < 0 THEN {_ns} ELSE 0 END)) AS total_outflow,
              SUM(CASE WHEN {_ns} > 0 THEN {_ns} ELSE 0 END)
                - ABS(SUM(CASE WHEN {_ns} < 0 THEN {_ns} ELSE 0 END)) AS net_amount
            FROM transactions_norm{where_sql}
        """
        try:
            conn = get_connection(db_path)
            row = conn.execute(sql, params).fetchone()
            conn.close()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Totals query failed: {exc}") from exc

        if not row:
            return {"row_count": 0, "total_spend": 0.0, "total_income": 0.0,
                    "total_outflow": 0.0, "net_amount": 0.0}
        return {
            "row_count":     int(row[0] or 0),
            "total_spend":   float(row[1] or 0),   # signed gross sum
            "total_income":  float(row[2] or 0),   # bank: inflows only
            "total_outflow": float(row[3] or 0),   # bank: |outflows| (positive)
            "net_amount":    float(row[4] or 0),   # bank: income − outflow
        }

    # -----------------------------------------------------------------------
    # Reports
    # -----------------------------------------------------------------------

    @app.get(
        "/reports",
        tags=["reports"],
        summary="List analytics reports",
        response_model=ReportsResponse if _PYDANTIC_OK else None,
    )
    def list_reports():
        """
        Return the names of all analytics CSV reports generated by the last successful run.

        Use `GET /reports/{name}` to download a file or
        `GET /charts/{name}` to get the data as JSON rows.
        """
        base = Path(reports_dir)
        base.mkdir(parents=True, exist_ok=True)
        return {"reports": sorted(p.name for p in base.glob("*.csv"))}

    @app.get(
        "/reports/{name}",
        tags=["reports"],
        summary="Download a report CSV",
    )
    def download_report(name: str):
        """
        Download a named analytics report as a CSV file.

        Available report names (returned by `GET /reports`):
        - `spend_by_month_category.csv` — monthly spend per category
        - `cashflow_by_month.csv` — monthly inflow, outflow, and net
        - `spend_by_merchant.csv` — total spend per merchant
        - `totals_by_account.csv` — net balance per account
        - `top_merchants.csv` — top 50 merchants by total spend
        """
        path = Path(reports_dir) / name
        if path.suffix.lower() != ".csv" or not path.exists():
            raise HTTPException(status_code=404, detail=f"Report '{name}' not found. Run an import first.")
        return FileResponse(path, media_type="text/csv", filename=path.name)

    @app.post(
        "/reports/query",
        tags=["reports"],
        summary="Run a custom parameterized report query",
    )
    def custom_report_query(payload: CustomReportRequest):
        """
        Execute a safe, parameterized SQL query against the ledger (transactions_norm).

        Supported operators: `=`, `contains`, `>=`, `<=`, `is_null`, `in`, `between`.
        When `group_by` is set the result is aggregated with row_count, net_amount,
        total_spend, and total_income columns.  The `bucket` parameter (day/week/month/year)
        controls how `transaction_date` is truncated in grouped queries.
        """
        try:
            sql, params, col_names = _build_report_sql(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            conn = get_connection(db_path)
            rows_raw = conn.execute(sql, params).fetchall()
            conn.close()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Query failed: {exc}") from exc
        rows = [
            {col_names[i]: (_isoformat(r[i]) if hasattr(r[i], "isoformat") else r[i])
             for i in range(len(col_names))}
            for r in rows_raw
        ]
        return {"columns": col_names, "rows": rows, "count": len(rows)}

    @app.get(
        "/charts/{name}",
        tags=["reports"],
        summary="Get a report as JSON rows (optionally re-grouped)",
        response_model=ChartResponse if _PYDANTIC_OK else None,
    )
    def chart_json(
        name: str,
        group_by: str = "",
        bucket: str = "",
    ):
        """
        Return a report CSV as a JSON array.  Pass `group_by=field1,field2` and
        optionally `bucket=month` to re-aggregate directly from the ledger instead of
        the pre-built CSV.  Numeric totals columns are added automatically when grouping.
        """
        path = Path(reports_dir) / name
        if path.suffix.lower() != ".csv" or not path.exists():
            raise HTTPException(status_code=404, detail=f"Report '{name}' not found. Run an import first.")
        if group_by.strip():
            fields = [f.strip() for f in group_by.split(",") if f.strip() in _REPORT_FIELDS]
            if not fields:
                raise HTTPException(status_code=400, detail="No valid group_by fields provided.")
            safe_bucket = bucket.strip() if bucket.strip() in _REPORT_BUCKETS else None

            class _P:  # lightweight payload for _build_report_sql
                filters = []; date_from = None; date_to = None; limit = 2000

            _p = _P(); _p.group_by = fields; _p.bucket = safe_bucket
            try:
                sql, params, col_names = _build_report_sql(_p)
                conn = get_connection(db_path)
                rows_raw = conn.execute(sql, params).fetchall()
                conn.close()
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Grouping query failed: {exc}") from exc
            rows = [
                {col_names[i]: (_isoformat(r[i]) if hasattr(r[i], "isoformat") else r[i])
                 for i in range(len(col_names))}
                for r in rows_raw
            ]
            return {"name": path.name, "rows": rows}
        return {"name": path.name, "rows": chart_from_report_csv(path)}

    # -----------------------------------------------------------------------
    # Metric docs — slug-based documentation pages for report columns
    # -----------------------------------------------------------------------

    _METRIC_DOCS: dict[str, dict] = {
        "net_amount": {
            "title": "Net Amount",
            "summary": "Signed total: income minus spend. Positive means net income.",
            "body": (
                "<p><strong>Net Amount</strong> is the algebraic sum of all transaction amounts "
                "within a group.</p>"
                "<ul>"
                "<li><strong>Positive</strong> — net inflow (received more than spent)</li>"
                "<li><strong>Negative</strong> — net outflow (spent more than received)</li>"
                "</ul>"
                "<p>Formula: <code>SUM(amount)</code> where inflows are positive, outflows negative.</p>"
                "<p>Use this to assess overall financial position for any period, category, or account.</p>"
            ),
        },
        "total_spend": {
            "title": "Total Spend",
            "summary": "Sum of outflows (negative amounts), displayed as positive.",
            "body": (
                "<p><strong>Total Spend</strong> aggregates all outgoing transactions in a group.</p>"
                "<ul>"
                "<li>Only negative-amount transactions contribute</li>"
                "<li>Displayed as a <em>positive</em> number (absolute value) for readability</li>"
                "</ul>"
                "<p>Formula: <code>SUM(amount) FILTER (WHERE amount &lt; 0)</code>, multiplied by −1.</p>"
                "<p>Use alongside <em>Total Income</em> to compute manual cash-flow figures.</p>"
            ),
        },
        "total_income": {
            "title": "Total Income",
            "summary": "Sum of inflows (positive amounts) for this group.",
            "body": (
                "<p><strong>Total Income</strong> aggregates all incoming transactions in a group.</p>"
                "<ul>"
                "<li>Only positive-amount transactions contribute</li>"
                "<li>Covers salary, refunds, transfers in, and other credits</li>"
                "</ul>"
                "<p>Formula: <code>SUM(amount) FILTER (WHERE amount &gt; 0)</code>.</p>"
                "<p>Pair with <em>Total Spend</em> to derive net cash-flow without using Net Amount.</p>"
            ),
        },
        "row_count": {
            "title": "Row Count",
            "summary": "Number of transactions counted in this group.",
            "body": (
                "<p><strong>Row Count</strong> is the number of individual transactions in an "
                "aggregated row.</p>"
                "<ul>"
                "<li>High count + low Net Amount → many small transactions</li>"
                "<li>Useful for spotting high-frequency spending categories</li>"
                "</ul>"
                "<p>Formula: <code>COUNT(*)</code> over the grouped rows.</p>"
            ),
        },
    }

    _DOCS_STYLE = (
        "<style>"
        "body{font-family:system-ui,sans-serif;background:#f8fafc;color:#1e293b;margin:0;padding:24px 16px}"
        ".wrap{max-width:620px;margin:0 auto;background:#fff;border-radius:8px;padding:32px;box-shadow:0 1px 4px rgba(0,0,0,.08)}"
        "h1{margin:0 0 6px;font-size:22px}"
        ".summary{color:#64748b;font-size:14px;margin:0 0 20px;font-style:italic}"
        "hr{border:none;border-top:1px solid #e2e8f0;margin:20px 0}"
        "ul{padding-left:20px;line-height:1.75}"
        "code{background:#f1f5f9;padding:2px 6px;border-radius:4px;font-size:13px}"
        ".back{font-size:13px;color:#3b82f6;text-decoration:none;display:inline-block;margin-bottom:20px}"
        ".back:hover{text-decoration:underline}"
        ".index a{display:block;padding:6px 0;color:#3b82f6;text-decoration:none;border-bottom:1px solid #f1f5f9}"
        ".index a:hover{text-decoration:underline}"
        "</style>"
    )

    @app.get("/metric-docs/{topic}", tags=["ui"], include_in_schema=False)
    def metric_docs(topic: str):
        """Slug-based documentation page for a named report metric."""
        doc = _METRIC_DOCS.get(topic)
        if doc is None:
            index_links = "".join(
                f"<a href='/metric-docs/{k}'>{v['title']}</a>"
                for k, v in _METRIC_DOCS.items()
            )
            html = (
                "<!doctype html><html><head><meta charset=utf-8>"
                f"<title>Metric not found — finance_etl</title>{_DOCS_STYLE}</head>"
                f"<body><div class='wrap'>"
                f"<a class='back' href='javascript:history.back()'>← Back</a>"
                f"<h1>Unknown metric: <code>{topic}</code></h1>"
                f"<p style='color:#64748b;margin-top:8px'>Available metrics:</p>"
                f"<div class='index'>{index_links}</div>"
                "</div></body></html>"
            )
            return HTMLResponse(content=html, status_code=404)

        html = (
            "<!doctype html><html><head><meta charset=utf-8>"
            f"<title>{doc['title']} — finance_etl docs</title>{_DOCS_STYLE}</head>"
            f"<body><div class='wrap'>"
            f"<a class='back' href='javascript:history.back()'>← Back</a>"
            f"<h1>{doc['title']}</h1>"
            f"<p class='summary'>{doc['summary']}</p>"
            "<hr>"
            f"<div class='detail'>{doc['body']}</div>"
            "</div></body></html>"
        )
        return HTMLResponse(content=html)

    # -----------------------------------------------------------------------
    # Web UI — always registered last so all API routes take precedence
    # -----------------------------------------------------------------------

    web_dir = Path(__file__).parent / "web"
    if (web_dir / "static").exists():
        app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")

    @app.get("/", tags=["ui"], summary="Web UI", include_in_schema=False)
    def serve_ui():
        """Serve the built-in web UI."""
        index = web_dir / "index.html"
        if index.exists():
            return HTMLResponse(content=index.read_text(encoding="utf-8"))
        return HTMLResponse(content="<h1>finance_etl API</h1><p>UI not installed.</p>")

    return app
