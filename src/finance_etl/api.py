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
    "category_normalized", "category_parent",
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
        # CC single-col polarity: 'format_a' (positive=spending) | 'format_b' (positive=payment)
        cc_polarity:       Optional[str]= Field(None, description="CC single-col polarity: 'format_a' or 'format_b'")
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

    # ---- Merchant rules models -----------------------------------------------

    class RuleCondition(BaseModel):
        pattern:    str
        match_type: str = "contains"
        negate:     bool = False

    class MerchantRuleRequest(BaseModel):
        pattern:    str = Field(..., description="Pattern to match against description")
        match_type: str = Field("contains", description="'contains' | 'startswith' | 'regex'")
        merchant:   str = Field(..., description="Normalized merchant name to assign")
        priority:   int = Field(0, description="Higher = applied first")
        conditions: Optional[list] = Field(None, description="Compound conditions [{pattern, match_type, negate}]")
        logic:      str = Field("AND", description="'AND' | 'OR' — how conditions are combined")

    class MerchantCategoryRequest(BaseModel):
        merchant:  str = Field(..., description="Merchant name (exact, case-sensitive)")
        category:  str = Field(..., description="Category to assign")

    class CategoryRuleRequest(BaseModel):
        raw_category: str = Field(..., description="Exact raw category string from bank")
        category:     str = Field(..., description="Normalized subcategory")
        parent:       str = Field(..., description="Parent group (e.g. 'Food & Dining')")

    class BudgetGoalRequest(BaseModel):
        parent:         str           = Field(..., description="Parent category group")
        category:       Optional[str] = Field(None, description="Specific subcategory (None = whole parent)")
        monthly_amount: float         = Field(..., description="Monthly budget in dollars")

    class NormalizeJobResponse(BaseModel):
        job_id:      str
        status:      str
        rows_total:  Optional[int] = None
        rows_done:   int = 0
        error:       Optional[str] = None
        started_at:  Optional[str] = None
        finished_at: Optional[str] = None

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
    "data/staged",
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
        title="Spendly",
        version="2.0.0",
        description="""
## Spendly API

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
            "name": "Spendly on GitHub",
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

    _UI_SETTINGS_PATH = Path("data/ui_settings.json")

    def _load_ui_settings() -> dict:
        defaults = {"verbose_logs": False, "show_logs": False}
        if _UI_SETTINGS_PATH.exists():
            try:
                saved = json.loads(_UI_SETTINGS_PATH.read_text(encoding="utf-8"))
                defaults.update(saved)
            except Exception:
                pass
        return defaults

    def _save_ui_settings(settings: dict) -> None:
        _UI_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _UI_SETTINGS_PATH.write_text(json.dumps(settings), encoding="utf-8")

    app.state.ui_settings = _load_ui_settings()

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
            # Auto-backup after successful commit (non-fatal on failure)
            try:
                _write_auto_backup(_create_export_payload())
            except Exception:
                pass
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

        Validation & normalisation applied on upload:
        - Extension must be `.csv` (case-insensitive)
        - Excel files disguised as `.csv` are rejected (magic-byte check)
        - Encoding auto-detected (UTF-8, Latin-1, UTF-16, Windows-1252, etc.)
        - BOM stripped (UTF-8-BOM, UTF-16 LE/BE)
        - Line endings normalised to `\\n`
        - File rewritten as clean UTF-8 for consistent downstream processing
        - Delimiter auto-detected (comma, semicolon, tab, pipe)
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

            # --- Validate file type (extension + magic bytes) ---
            from finance_etl.utils.csv_sniff import validate_uploaded_file, sanitize_csv_encoding
            try:
                validate_uploaded_file(dest, safe_original)
            except ValueError as val_err:
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail=str(val_err))

            # --- Normalise encoding, BOM, line endings → clean UTF-8 ---
            sanitize_csv_encoding(dest)

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
        Return all import runs and normalization jobs ordered by most recent first (up to 200).

        In-flight runs (pending/running/committing) show their live status from memory;
        completed runs are read from the database.  Normalization jobs are merged in with
        type='normalize'; import runs have type='import'.
        """
        try:
            conn = get_connection(db_path, read_only=True)
            run_rows = conn.execute(
                """
                SELECT run_id, started_at, finished_at, status,
                       files_count, rows_in, rows_staged,
                       rows_normalized, rows_loaded, errors_count, imported_file
                FROM runs
                ORDER BY started_at DESC
                LIMIT 200
                """
            ).fetchall()
            norm_rows = conn.execute(
                """
                SELECT job_id, created_at, finished_at, status,
                       rows_total, rows_done, error
                FROM normalization_jobs
                ORDER BY created_at DESC
                LIMIT 50
                """
            ).fetchall()
            conn.close()
        except Exception:
            return {"runs": []}

        run_cols = [
            "run_id", "started_at", "finished_at", "status",
            "files_count", "rows_in", "rows_staged",
            "rows_normalized", "rows_loaded", "errors_count", "imported_file",
        ]
        runs = []
        for r in run_rows:
            d = dict(zip(run_cols, r))
            d["type"] = "import"
            live = _async_runs.get(d["run_id"])
            if live and live["status"] in ("pending", "running", "committing"):
                d["status"] = live["status"]
            # Normalize datetime → ISO string so sort key is always str
            for k in ("started_at", "finished_at"):
                v = d.get(k)
                if v is not None and hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
            runs.append(d)

        norm_cols = ["run_id", "started_at", "finished_at", "status",
                     "rows_total", "rows_done", "error"]
        for r in norm_rows:
            d = dict(zip(norm_cols, r))
            d["type"] = "normalize"
            d["imported_file"] = None  # normalization jobs have no source file
            # finished_at may be a datetime too
            for k in ("started_at", "finished_at"):
                v = d.get(k)
                if v is not None and hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
            runs.append(d)

        # Re-sort merged list by started_at DESC (nulls last)
        # All started_at values are now ISO strings or None, so sort is safe.
        runs.sort(key=lambda x: x.get("started_at") or "", reverse=True)

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
                # Primary path: delete by run_id (works even after stage rows purged)
                conn.execute(
                    "DELETE FROM transactions_norm WHERE run_id = ?", [run_id]
                )
                # Fallback: also delete by file_hash from stage (covers rows with NULL run_id)
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
            from finance_etl.pipeline import _staged_runs, _remove_staged
            _staged_runs.pop(run_id, None)
            _remove_staged(run_id)
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

        # Validate mapping (pass statement_type for scoped group checks)
        _stmt_type_for_validation = getattr(payload, "statement_type", None)
        errors = validate_wizard_mapping(payload.canonical_map, statement_type=_stmt_type_for_validation)
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
            cc_polarity=getattr(payload, "cc_polarity", None),
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

    @app.get("/version", tags=["ui"], summary="Get application version")
    def get_version():
        try:
            from importlib.metadata import version as _pkg_version
            ver = _pkg_version("finance_etl")
        except Exception:
            ver = "unknown"
        return {"version": ver}

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
        _save_ui_settings(app.state.ui_settings)
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
        type, date_from, date_to, account, category, merchant, source, subtype=None,
        unreviewed_only=False, tag=None,
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
        if subtype and subtype in ("spending", "payment", "adjustment"):
            where.append("transaction_subtype = ?"); params.append(subtype)
        # source filter: specific run_id; 'all' or absent → no additional filter
        if source and source != "all":
            where.append("run_id = ?"); params.append(source)
        # review status filter
        # COALESCE handles pre-migration rows where unreviewed is NULL (treated as unreviewed)
        if unreviewed_only:
            where.append("COALESCE(unreviewed, TRUE) = TRUE")
        # tag filter: only transactions with a specific tag
        if tag:
            where.append(
                "transaction_fingerprint IN ("
                "SELECT transaction_fingerprint FROM transaction_tags WHERE tag_id = ?)"
            )
            params.append(int(tag))
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
        subtype:   Optional[str] = Query(None,           description="transaction_subtype filter: spending|payment|adjustment"),
        source:    Optional[str] = Query(None,           description="run_id to filter by import source; 'all' = no filter"),
        group_by:  Optional[str] = Query(None,           description="Comma-separated field(s) to group"),
        sort_by:   str           = Query("transaction_date", description="Column to sort by"),
        sort_dir:  str           = Query("desc",          description="'asc' or 'desc'"),
        unreviewed_only: bool    = Query(False,           description="Show only unreviewed transactions"),
        tag:       Optional[int] = Query(None,            description="Filter by tag ID"),
    ):
        """
        Filtered transaction list.

        Feature 1: Credit-card aggregations never include bank rows and vice versa.
        Pass `type=credit_card` or `type=bank` to scope.
        Pass `source=<run_id>` to filter by a specific import; omit or pass `source=all`
        to show all rows for the given type.
        """
        where, params = _build_txn_where(type, date_from, date_to, account, category, merchant, source, subtype, unreviewed_only=unreviewed_only, tag=tag)

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
                    "statement_type", "transaction_fingerprint",
                    "unreviewed",
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
        subtype:   Optional[str] = Query(None, description="transaction_subtype filter: spending|payment|adjustment"),
        source:    Optional[str] = Query(None,  description="run_id to filter by import source; 'all' = no filter"),
        unreviewed_only: bool    = Query(False, description="Show only unreviewed transactions"),
        tag:       Optional[int] = Query(None,  description="Filter by tag ID"),
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
        where, params = _build_txn_where(type, date_from, date_to, account, category, merchant, source, subtype, unreviewed_only=unreviewed_only, tag=tag)

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        _ns = "COALESCE(amount, 0)"
        _ra = "COALESCE(resolved_amount, 0)"
        sql = f"""
            SELECT
              COUNT(*) AS row_count,
              SUM({_ns}) AS total_spend,
              SUM(CASE WHEN {_ns} > 0 THEN {_ns} ELSE 0 END) AS total_income,
              ABS(SUM(CASE WHEN {_ns} < 0 THEN {_ns} ELSE 0 END)) AS total_outflow,
              SUM(CASE WHEN {_ns} > 0 THEN {_ns} ELSE 0 END)
                - ABS(SUM(CASE WHEN {_ns} < 0 THEN {_ns} ELSE 0 END)) AS net_amount,
              -- CC balance fields (subtype model)
              COALESCE(SUM(CASE WHEN transaction_subtype = 'spending'    THEN {_ra} ELSE 0 END), 0) AS cc_spending,
              COALESCE(SUM(CASE WHEN transaction_subtype = 'payment'     THEN {_ra} ELSE 0 END), 0) AS cc_payments,
              COALESCE(SUM(CASE WHEN transaction_subtype = 'adjustment'  THEN {_ra} ELSE 0 END), 0) AS cc_adjustments,
              -- Conflict rows: awaiting user resolution (not included in balance)
              COUNT(CASE WHEN transaction_subtype = 'conflict' THEN 1 END) AS cc_conflict_count,
              -- Legacy cc rows with NULL subtype: excluded from balance
              COUNT(CASE WHEN statement_type = 'credit_card' AND transaction_subtype IS NULL THEN 1 END) AS cc_legacy_count
            FROM transactions_norm{where_sql}
        """
        try:
            conn = get_connection(db_path)
            row = conn.execute(sql, params).fetchone()
            conn.close()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Totals query failed: {exc}") from exc

        if not row:
            return {
                "row_count": 0, "total_spend": 0.0, "total_income": 0.0,
                "total_outflow": 0.0, "net_amount": 0.0,
                "cc_spending": 0.0, "cc_payments": 0.0, "cc_adjustments": 0.0,
                "cc_balance": 0.0, "cc_conflict_count": 0, "cc_legacy_count": 0,
            }

        cc_spending    = float(row[5] or 0)
        cc_payments    = float(row[6] or 0)
        cc_adjustments = float(row[7] or 0)
        # Card Balance = Total Spending − Total Payments − Total Adjustments
        # Positive = amount still owed; Negative = overpaid (credit)
        cc_balance = cc_spending - cc_payments - cc_adjustments

        return {
            "row_count":          int(row[0]  or 0),
            "total_spend":        float(row[1] or 0),   # signed gross sum (legacy)
            "total_income":       float(row[2] or 0),   # bank: inflows only
            "total_outflow":      float(row[3] or 0),   # bank: |outflows|
            "net_amount":         float(row[4] or 0),   # bank: income − outflow
            # CC subtype balance model
            "cc_spending":        cc_spending,
            "cc_payments":        cc_payments,
            "cc_adjustments":     cc_adjustments,
            "cc_balance":         cc_balance,
            "cc_conflict_count":  int(row[8]  or 0),
            "cc_legacy_count":    int(row[9]  or 0),
        }

    # -----------------------------------------------------------------------
    # Transaction Review
    # -----------------------------------------------------------------------

    @app.get("/transactions/unreviewed-count", tags=["transactions"],
             summary="Count of unreviewed transactions")
    def unreviewed_count():
        """Return the total number of unreviewed transactions across all types."""
        try:
            conn = get_connection(db_path, read_only=True)
            row = conn.execute(
                "SELECT COUNT(*) FROM transactions_norm WHERE COALESCE(unreviewed, TRUE) = TRUE"
            ).fetchone()
            conn.close()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Count query failed: {exc}") from exc
        return {"unreviewed_count": int(row[0]) if row else 0}

    @app.post("/transactions/mark-reviewed", tags=["transactions"],
              summary="Mark specific transactions as reviewed")
    def mark_reviewed(body: dict):
        """
        Mark one or more transactions as reviewed.

        Body: {"fingerprints": ["fp1", "fp2", ...]}
        """
        fingerprints = body.get("fingerprints", [])
        if not fingerprints or not isinstance(fingerprints, list):
            raise HTTPException(status_code=400, detail="'fingerprints' must be a non-empty list.")
        try:
            conn = get_connection(db_path)
            placeholders = ", ".join(["?"] * len(fingerprints))
            conn.execute(
                f"UPDATE transactions_norm SET unreviewed = FALSE "
                f"WHERE transaction_fingerprint IN ({placeholders})",
                fingerprints,
            )
            row = conn.execute("SELECT changes()").fetchone()
            updated = int(row[0]) if row else 0
            conn.close()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Update failed: {exc}") from exc
        return {"updated": updated}

    @app.post("/transactions/mark-all-reviewed", tags=["transactions"],
              summary="Mark all filtered transactions as reviewed")
    def mark_all_reviewed(
        type:      Optional[str] = Query(None,  description="'credit_card' or 'bank'"),
        date_from: Optional[str] = Query(None),
        date_to:   Optional[str] = Query(None),
        account:   Optional[str] = Query(None),
        category:  Optional[str] = Query(None),
        merchant:  Optional[str] = Query(None),
        subtype:   Optional[str] = Query(None),
        source:    Optional[str] = Query(None),
    ):
        """Mark all transactions matching the current filters as reviewed."""
        where, params = _build_txn_where(type, date_from, date_to, account, category, merchant, source, subtype)
        # Only update unreviewed ones
        where.append("COALESCE(unreviewed, TRUE) = TRUE")
        where_sql = " WHERE " + " AND ".join(where) if where else ""
        try:
            conn = get_connection(db_path)
            conn.execute(
                f"UPDATE transactions_norm SET unreviewed = FALSE{where_sql}",
                params,
            )
            row = conn.execute("SELECT changes()").fetchone()
            updated = int(row[0]) if row else 0
            conn.close()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Bulk update failed: {exc}") from exc
        return {"updated": updated}

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
                f"<title>Metric not found — Spendly{_DOCS_STYLE}</head>"
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
    # Merchant rules CRUD
    # -----------------------------------------------------------------------

    from finance_etl.merchant_rules import (
        assign_category,
        batch_renormalize,
        create_normalization_job,
        load_category_map,
        load_rules,
    )

    @app.get("/merchant-rules", tags=["merchant"], summary="List merchant normalization rules")
    def get_merchant_rules():
        """Return all merchant rules ordered by priority DESC, id ASC."""
        import json as _json
        try:
            conn = get_connection(db_path, read_only=True)
            rows = conn.execute(
                "SELECT id, pattern, match_type, merchant, priority, created_at, updated_at, conditions, logic "
                "FROM merchant_rules ORDER BY priority DESC, id ASC"
            ).fetchall()
            conn.close()
        except Exception:
            return {"rules": []}
        cols = ["id", "pattern", "match_type", "merchant", "priority", "created_at", "updated_at", "conditions", "logic"]
        result = []
        for r in rows:
            d = dict(zip(cols, r))
            if d["conditions"]:
                try:
                    d["conditions"] = _json.loads(d["conditions"])
                except Exception:
                    d["conditions"] = None
            d["logic"] = d["logic"] or "AND"
            result.append(d)
        return {"rules": result}

    @app.post("/merchant-rules", tags=["merchant"], summary="Create a merchant rule", status_code=201)
    def create_merchant_rule(payload: MerchantRuleRequest):
        """Add a new merchant normalization rule."""
        import re as _re
        if payload.match_type not in ("contains", "startswith", "regex"):
            from fastapi import HTTPException
            raise HTTPException(400, "match_type must be 'contains', 'startswith', or 'regex'")
        if payload.match_type == "regex":
            try:
                _re.compile(payload.pattern)
            except _re.error as exc:
                from fastapi import HTTPException
                raise HTTPException(400, f"Invalid regex: {exc}")
        import json as _json
        conditions_json = _json.dumps(payload.conditions) if payload.conditions else None
        logic_val = payload.logic if payload.logic in ("AND", "OR") else "AND"
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        conn = get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO merchant_rules (pattern, match_type, merchant, priority, created_at, updated_at, conditions, logic) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [payload.pattern, payload.match_type, payload.merchant, payload.priority, now, now, conditions_json, logic_val],
            )
            row = conn.execute(
                "SELECT id FROM merchant_rules WHERE pattern=? AND merchant=? AND created_at=?",
                [payload.pattern, payload.merchant, now],
            ).fetchone()
        finally:
            conn.close()
        return {"id": row[0] if row else None, "status": "created"}

    @app.put("/merchant-rules/{rule_id}", tags=["merchant"], summary="Update a merchant rule")
    def update_merchant_rule(rule_id: int, payload: MerchantRuleRequest):
        """Update an existing merchant rule by ID."""
        import re as _re
        if payload.match_type not in ("contains", "startswith", "regex"):
            from fastapi import HTTPException
            raise HTTPException(400, "match_type must be 'contains', 'startswith', or 'regex'")
        if payload.match_type == "regex":
            try:
                _re.compile(payload.pattern)
            except _re.error as exc:
                from fastapi import HTTPException
                raise HTTPException(400, f"Invalid regex: {exc}")
        import json as _json
        conditions_json = _json.dumps(payload.conditions) if payload.conditions else None
        logic_val = payload.logic if payload.logic in ("AND", "OR") else "AND"
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        conn = get_connection(db_path)
        try:
            conn.execute(
                "UPDATE merchant_rules SET pattern=?, match_type=?, merchant=?, priority=?, updated_at=?, conditions=?, logic=? "
                "WHERE id=?",
                [payload.pattern, payload.match_type, payload.merchant, payload.priority, now, conditions_json, logic_val, rule_id],
            )
        finally:
            conn.close()
        return {"status": "updated"}

    @app.delete("/merchant-rules/{rule_id}", tags=["merchant"], summary="Delete a merchant rule")
    def delete_merchant_rule(rule_id: int):
        """Delete a merchant rule by ID."""
        conn = get_connection(db_path)
        try:
            conn.execute("DELETE FROM merchant_rules WHERE id=?", [rule_id])
        finally:
            conn.close()
        return {"status": "deleted"}

    @app.post("/merchant-rules/test", tags=["merchant"], summary="Test a rule against sample descriptions")
    def test_merchant_rule(payload: MerchantRuleRequest):
        """
        Test how a rule would match against transaction descriptions.
        Returns matching descriptions with transaction counts, ordered by frequency.
        """
        from finance_etl.merchant_rules import CompiledRule
        rule = CompiledRule(id=0, pattern=payload.pattern, match_type=payload.match_type,
                            merchant=payload.merchant, priority=payload.priority,
                            conditions=payload.conditions,
                            logic=payload.logic if payload.logic in ("AND", "OR") else "AND")
        try:
            conn = get_connection(db_path, read_only=True)
            rows = conn.execute(
                "SELECT description, COUNT(*) as cnt FROM transactions_norm "
                "GROUP BY description ORDER BY cnt DESC"
            ).fetchall()
            conn.close()
        except Exception:
            return {"matches": [], "total_matches": 0, "total_sampled": 0}
        all_matches = [
            {"description": r[0], "count": r[1]}
            for r in rows if rule.matches(r[0] or "")
        ]
        total_transactions = sum(m["count"] for m in all_matches)
        return {
            "matches": all_matches[:50],
            "total_matches": len(all_matches),
            "total_transactions": total_transactions,
            "total_sampled": len(rows),
        }

    @app.get("/merchant-rules/suggestions", tags=["merchant"],
             summary="Analyze descriptions and suggest normalization rules")
    def get_rule_suggestions(
        min_transactions: int = Query(3, description="Min transaction count for a suggestion to appear"),
    ):
        """
        Analyze all raw transaction descriptions and suggest merchant normalization rules.

        Groups similar descriptions by their stripped 'core' (after removing noise like
        transaction IDs, platform prefixes, state codes). Each group becomes a suggestion
        with an inferred match type (startswith or contains) and a cleaned merchant name.

        Already-covered descriptions (matched by existing rules) are excluded.
        Results are sorted by transaction count — highest-impact suggestions first.
        """
        from finance_etl.merchant_rules import analyze_descriptions
        try:
            conn = get_connection(db_path, read_only=True)
            suggestions = analyze_descriptions(conn, min_transactions=min_transactions)
            conn.close()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}") from exc
        return {"suggestions": suggestions, "count": len(suggestions)}

    @app.get("/merchant-categories/suggestions", tags=["merchant"],
             summary="Suggest categories for uncategorized merchants")
    def get_category_suggestions():
        """
        Suggest categories for merchants that have no category assignment yet.

        Uses keyword heuristics against ~10 common category buckets (Restaurants,
        Groceries, Gas, Shopping, Streaming, etc.).  Only merchants already present
        in transactions_norm are considered.

        Returns [{merchant, suggested_category, confidence}] where confidence is
        'high' (≥2 keyword matches) or 'medium' (1 match).
        """
        from finance_etl.merchant_rules import suggest_categories_for_merchants
        try:
            conn = get_connection(db_path, read_only=True)
            rows = conn.execute(
                """
                SELECT DISTINCT tn.merchant
                FROM transactions_norm tn
                WHERE tn.merchant IS NOT NULL
                  AND LOWER(tn.merchant) NOT IN (
                    SELECT LOWER(merchant) FROM merchant_category_map
                  )
                ORDER BY tn.merchant
                LIMIT 500
                """
            ).fetchall()
            conn.close()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Query failed: {exc}") from exc
        merchants = [r[0] for r in rows if r[0]]
        suggestions = suggest_categories_for_merchants(merchants)
        return {"suggestions": suggestions, "count": len(suggestions)}

    # -----------------------------------------------------------------------
    # Merchant category map
    # -----------------------------------------------------------------------

    @app.get("/merchant-categories", tags=["merchant"], summary="List all merchant→category mappings")
    def get_merchant_categories():
        """Return all entries in merchant_category_map."""
        try:
            conn = get_connection(db_path, read_only=True)
            rows = conn.execute(
                "SELECT merchant, category, source, updated_at FROM merchant_category_map ORDER BY merchant"
            ).fetchall()
            conn.close()
        except Exception:
            return {"categories": []}
        cols = ["merchant", "category", "source", "updated_at"]
        return {"categories": [dict(zip(cols, r)) for r in rows]}

    @app.get("/merchant-categories/uncategorized", tags=["merchant"],
             summary="List merchants with no category assignment")
    def get_uncategorized_merchants():
        """Return distinct merchants in transactions_norm that have no entry in merchant_category_map."""
        try:
            conn = get_connection(db_path, read_only=True)
            rows = conn.execute(
                """
                SELECT DISTINCT tn.merchant
                FROM transactions_norm tn
                WHERE tn.merchant IS NOT NULL
                  AND LOWER(tn.merchant) NOT IN (
                    SELECT LOWER(merchant) FROM merchant_category_map
                  )
                ORDER BY tn.merchant
                LIMIT 200
                """
            ).fetchall()
            conn.close()
        except Exception:
            return {"merchants": []}
        return {"merchants": [r[0] for r in rows]}

    @app.post("/merchant-categories", tags=["merchant"], summary="Assign a category to a merchant",
              status_code=201)
    def set_merchant_category(payload: MerchantCategoryRequest):
        """
        Assign a category to a merchant (source='user').
        Also backfills historical transactions_norm rows for this merchant.
        """
        conn = get_connection(db_path)
        try:
            assign_category(conn, payload.merchant, payload.category)
        finally:
            conn.close()
        return {"status": "saved"}

    @app.delete("/merchant-categories/{merchant}", tags=["merchant"],
                summary="Remove a merchant→category mapping")
    def delete_merchant_category(merchant: str):
        """Remove a merchant category entry (URL-encode the merchant name)."""
        conn = get_connection(db_path)
        try:
            conn.execute("DELETE FROM merchant_category_map WHERE merchant=?", [merchant])
        finally:
            conn.close()
        return {"status": "deleted"}

    # -----------------------------------------------------------------------
    # Batch re-normalization
    # -----------------------------------------------------------------------

    @app.post("/normalize/apply", tags=["merchant"],
              summary="Start a batch re-normalization job", status_code=202)
    async def start_renormalize(background_tasks: BackgroundTasks):
        """
        Apply all current merchant rules to every row in transactions_norm.
        Returns a job_id for polling via GET /normalize/{job_id}.
        Runs asynchronously in a background thread.
        """
        import threading
        conn = get_connection(db_path)
        try:
            job_id = create_normalization_job(conn)
        finally:
            conn.close()

        def _run():
            batch_renormalize(str(db_path), job_id)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return {"job_id": job_id, "status": "pending"}

    @app.get("/normalize/{job_id}", tags=["merchant"],
             summary="Get re-normalization job status")
    def get_normalize_job(job_id: str):
        """Poll re-normalization progress for a given job_id."""
        try:
            conn = get_connection(db_path, read_only=True)
            row = conn.execute(
                "SELECT job_id, status, rows_total, rows_done, error, started_at, finished_at "
                "FROM normalization_jobs WHERE job_id=?",
                [job_id],
            ).fetchone()
            conn.close()
        except Exception:
            from fastapi import HTTPException
            raise HTTPException(500, "DB error")
        if not row:
            from fastapi import HTTPException
            raise HTTPException(404, f"Job {job_id!r} not found")
        cols = ["job_id", "status", "rows_total", "rows_done", "error", "started_at", "finished_at"]
        return dict(zip(cols, row))

    # -----------------------------------------------------------------------
    # Merchant Intelligence
    # -----------------------------------------------------------------------

    @app.get("/merchant-analytics", tags=["merchant"],
             summary="Merchant intelligence: per-merchant spend, trends, frequency")
    def get_merchant_analytics(
        sort_by: str = Query(
            "total_spend",
            description="Sort by: total_spend, frequency, recent, trend",
        ),
        search: Optional[str] = Query(None, description="Filter merchants by name (case-insensitive)"),
        limit: int = Query(100, description="Max results"),
    ):
        """
        Return per-merchant analytics: total spend, monthly average, frequency,
        last transaction, 3-month trend, and acceleration flag.
        """
        import datetime as _dt

        today = _dt.date.today()
        # Last 3 full calendar months for trend calculation
        m3_end = today.replace(day=1) - _dt.timedelta(days=1)  # last day of prior month
        m3_start = (m3_end.replace(day=1) - _dt.timedelta(days=60)).replace(day=1)  # ~3 months back

        search_clause = ""
        params: list = []
        if search:
            search_clause = " AND LOWER(merchant) LIKE ?"
            params.append(f"%{search.lower()}%")

        conn = get_connection(db_path, read_only=True)
        try:
            # All-time per-merchant stats
            alltime_rows = conn.execute(
                f"""SELECT merchant,
                       SUM(resolved_amount) AS total_spend,
                       COUNT(*) AS txn_count,
                       MAX(transaction_date) AS last_date,
                       MIN(transaction_date) AS first_date
                    FROM transactions_norm
                    WHERE transaction_subtype = 'spending'
                      AND merchant IS NOT NULL
                      {search_clause}
                    GROUP BY merchant""",
                params,
            ).fetchall()

            # Monthly totals for the last 3 months (for trend)
            trend_rows = conn.execute(
                f"""SELECT merchant,
                       YEAR(transaction_date) AS y,
                       MONTH(transaction_date) AS m,
                       SUM(resolved_amount) AS spend
                    FROM transactions_norm
                    WHERE transaction_subtype = 'spending'
                      AND merchant IS NOT NULL
                      AND transaction_date >= ?
                      {search_clause}
                    GROUP BY merchant, y, m
                    ORDER BY merchant, y, m""",
                [m3_start.isoformat()] + params,
            ).fetchall()

            conn.close()
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Merchant analytics failed: {exc}"
            ) from exc

        # Build trend map: merchant -> list of (year, month, spend)
        trend_map: dict[str, list] = {}
        for r in trend_rows:
            trend_map.setdefault(r[0], []).append({
                "year": int(r[1]), "month": int(r[2]), "spend": float(r[3])
            })

        merchants = []
        for r in alltime_rows:
            merchant_name = r[0]
            total_spend = float(r[1])
            txn_count = int(r[2])
            last_date = _isoformat(r[3]) if r[3] else None
            first_date = _isoformat(r[4]) if r[4] else None

            # Monthly average: total / months active
            if first_date and last_date:
                fd = _dt.date.fromisoformat(first_date[:10])
                ld = _dt.date.fromisoformat(last_date[:10])
                months_active = max(
                    (ld.year - fd.year) * 12 + (ld.month - fd.month) + 1, 1
                )
            else:
                months_active = 1
            monthly_avg = round(total_spend / months_active, 2)

            # Trend analysis: compare most recent month to the one before
            monthly_data = trend_map.get(merchant_name, [])
            trend = "flat"
            trend_pct = 0.0
            accelerating = False

            if len(monthly_data) >= 2:
                latest = monthly_data[-1]["spend"]
                prior = monthly_data[-2]["spend"]
                if prior > 0:
                    trend_pct = round((latest - prior) / prior * 100, 1)
                    if trend_pct > 5:
                        trend = "increasing"
                    elif trend_pct < -5:
                        trend = "decreasing"
                    if trend_pct > 20:
                        accelerating = True

                # Check for sustained acceleration (3 months)
                if len(monthly_data) >= 3:
                    m1, m2, m3 = (
                        monthly_data[-3]["spend"],
                        monthly_data[-2]["spend"],
                        monthly_data[-1]["spend"],
                    )
                    if m1 > 0 and m2 > 0:
                        d1 = (m2 - m1) / m1 * 100
                        d2 = (m3 - m2) / m2 * 100
                        if d1 > 20 and d2 > 20:
                            accelerating = True

            merchants.append({
                "merchant": merchant_name,
                "total_spend": total_spend,
                "txn_count": txn_count,
                "monthly_avg": monthly_avg,
                "months_active": months_active,
                "first_date": first_date,
                "last_date": last_date,
                "trend": trend,
                "trend_pct": trend_pct,
                "accelerating": accelerating,
                "monthly_data": monthly_data,
            })

        # Sort
        sort_keys = {
            "total_spend": lambda m: -m["total_spend"],
            "frequency": lambda m: -m["txn_count"],
            "recent": lambda m: m["last_date"] or "",
            "trend": lambda m: -abs(m["trend_pct"]),
        }
        key_fn = sort_keys.get(sort_by, sort_keys["total_spend"])
        merchants.sort(key=key_fn, reverse=(sort_by == "recent"))
        merchants = merchants[:limit]

        # Summary stats
        total_merchants = len(alltime_rows)
        accelerating_count = sum(1 for m in merchants if m["accelerating"])

        return {
            "merchants": merchants,
            "total_merchants": total_merchants,
            "accelerating_count": accelerating_count,
        }

    # -----------------------------------------------------------------------
    # Category rules CRUD
    # -----------------------------------------------------------------------

    from finance_etl.category_rules import (
        BUILT_IN_CATEGORY_MAP,
        apply_category_rules,
        create_category_job,
        load_category_rules,
    )

    @app.get("/category-rules", tags=["categories"], summary="List all category rules")
    def get_category_rules():
        """Return all entries in category_rules ordered by parent, category."""
        try:
            conn = get_connection(db_path, read_only=True)
            rows = conn.execute(
                "SELECT id, raw_category, category, parent, created_at, updated_at "
                "FROM category_rules ORDER BY parent ASC, category ASC"
            ).fetchall()
            conn.close()
        except Exception:
            return {"rules": []}
        cols = ["id", "raw_category", "category", "parent", "created_at", "updated_at"]
        return {"rules": [dict(zip(cols, r)) for r in rows]}

    @app.post("/category-rules", tags=["categories"], summary="Create or update a category rule",
              status_code=201)
    def create_category_rule(payload: CategoryRuleRequest):
        """Insert a category rule; on UNIQUE conflict update existing entry."""
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        conn = get_connection(db_path)
        try:
            existing = conn.execute(
                "SELECT id FROM category_rules WHERE raw_category=?",
                [payload.raw_category],
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO category_rules (raw_category, category, parent, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [payload.raw_category, payload.category, payload.parent, now, now],
                )
                row_id = conn.execute(
                    "SELECT id FROM category_rules WHERE raw_category=?",
                    [payload.raw_category],
                ).fetchone()[0]
                status = "created"
            else:
                conn.execute(
                    "UPDATE category_rules SET category=?, parent=?, updated_at=? WHERE raw_category=?",
                    [payload.category, payload.parent, now, payload.raw_category],
                )
                row_id = existing[0]
                status = "updated"
        finally:
            conn.close()
        return {"id": row_id, "status": status}

    @app.put("/category-rules/{rule_id}", tags=["categories"], summary="Update a category rule")
    def update_category_rule(rule_id: int, payload: CategoryRuleRequest):
        """Update an existing category rule by ID."""
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        conn = get_connection(db_path)
        try:
            conn.execute(
                "UPDATE category_rules SET raw_category=?, category=?, parent=?, updated_at=? WHERE id=?",
                [payload.raw_category, payload.category, payload.parent, now, rule_id],
            )
        finally:
            conn.close()
        return {"status": "updated"}

    @app.delete("/category-rules/{rule_id}", tags=["categories"], summary="Delete a category rule")
    def delete_category_rule(rule_id: int):
        """Delete a category rule by ID."""
        conn = get_connection(db_path)
        try:
            conn.execute("DELETE FROM category_rules WHERE id=?", [rule_id])
        finally:
            conn.close()
        return {"status": "deleted"}

    @app.get("/category-rules/unmapped", tags=["categories"],
             summary="List raw categories not covered by any rule")
    def get_unmapped_categories():
        """
        Return raw categories in transactions_norm that have no user-defined rule.
        Each entry also indicates whether a built-in suggestion exists.
        """
        try:
            conn = get_connection(db_path, read_only=True)
            rows = conn.execute(
                """
                SELECT category, COUNT(*) AS cnt
                FROM transactions_norm
                WHERE category IS NOT NULL AND category != ''
                  AND category NOT IN (SELECT raw_category FROM category_rules)
                GROUP BY category
                ORDER BY cnt DESC
                """
            ).fetchall()
            conn.close()
        except Exception:
            return {"unmapped": []}
        result = []
        for raw_cat, cnt in rows:
            builtin = BUILT_IN_CATEGORY_MAP.get(raw_cat)
            result.append({
                "raw_category": raw_cat,
                "count": cnt,
                "has_builtin_suggestion": builtin is not None,
                "builtin_category": builtin[0] if builtin else None,
                "builtin_parent": builtin[1] if builtin else None,
            })
        return {"unmapped": result}

    @app.get("/category-rules/suggestions", tags=["categories"],
             summary="Suggest category rules from built-in map")
    def get_category_rule_suggestions():
        """
        Return raw categories from transactions_norm not already in category_rules
        that have a matching entry in BUILT_IN_CATEGORY_MAP.
        """
        try:
            conn = get_connection(db_path, read_only=True)
            rows = conn.execute(
                """
                SELECT category, COUNT(*) AS cnt
                FROM transactions_norm
                WHERE category IS NOT NULL AND category != ''
                  AND category NOT IN (SELECT raw_category FROM category_rules)
                GROUP BY category
                ORDER BY cnt DESC
                """
            ).fetchall()
            conn.close()
        except Exception:
            return {"suggestions": []}
        suggestions = []
        for raw_cat, cnt in rows:
            builtin = BUILT_IN_CATEGORY_MAP.get(raw_cat)
            if builtin:
                suggestions.append({
                    "raw_category": raw_cat,
                    "category": builtin[0],
                    "parent": builtin[1],
                    "count": cnt,
                })
        return {"suggestions": suggestions}

    @app.post("/category-rules/apply", tags=["categories"],
              summary="Start a batch category normalization job", status_code=202)
    async def start_category_normalize():
        """
        Apply all current category rules to every row in transactions_norm.
        Returns a job_id for polling via GET /normalize/{job_id}.
        Runs asynchronously in a background thread.
        """
        import threading
        # Use create_category_job() to pre-compute rows_total so the UI
        # progress bar shows correct totals from the start
        conn = get_connection(db_path)
        try:
            job_id = create_category_job(conn)
        finally:
            conn.close()

        def _run():
            apply_category_rules(str(db_path), job_id)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return {"job_id": job_id, "status": "pending"}

    # -----------------------------------------------------------------------
    # Budget goals CRUD
    # -----------------------------------------------------------------------

    @app.get("/budgets", tags=["budgets"], summary="List all budget goals")
    def get_budgets():
        """Return all budget goals ordered by parent, category."""
        try:
            conn = get_connection(db_path, read_only=True)
            rows = conn.execute(
                "SELECT id, parent, category, monthly_amount, created_at, updated_at "
                "FROM budget_goals ORDER BY parent, category"
            ).fetchall()
            conn.close()
        except Exception:
            return {"budgets": []}
        cols = ["id", "parent", "category", "monthly_amount", "created_at", "updated_at"]
        return {"budgets": [dict(zip(cols, r)) for r in rows]}

    @app.post("/budgets", tags=["budgets"], summary="Create or update a budget goal",
              status_code=201)
    def create_budget(payload: BudgetGoalRequest):
        """Insert a budget goal; on UNIQUE conflict update monthly_amount."""
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        conn = get_connection(db_path)
        try:
            existing = conn.execute(
                "SELECT id FROM budget_goals WHERE parent=? AND category IS NOT DISTINCT FROM ?",
                [payload.parent, payload.category],
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO budget_goals (parent, category, monthly_amount, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    [payload.parent, payload.category, payload.monthly_amount, now, now],
                )
                row = conn.execute(
                    "SELECT id FROM budget_goals WHERE parent=? AND category IS NOT DISTINCT FROM ?",
                    [payload.parent, payload.category],
                ).fetchone()
                row_id = row[0]
                status = "created"
            else:
                conn.execute(
                    "UPDATE budget_goals SET monthly_amount=?, updated_at=? WHERE id=?",
                    [payload.monthly_amount, now, existing[0]],
                )
                row_id = existing[0]
                status = "updated"
        finally:
            conn.close()
        return {"id": row_id, "status": status}

    @app.delete("/budgets/{budget_id}", tags=["budgets"], summary="Delete a budget goal")
    def delete_budget(budget_id: int):
        """Delete a budget goal by ID."""
        conn = get_connection(db_path)
        try:
            conn.execute("DELETE FROM budget_goals WHERE id=?", [budget_id])
        finally:
            conn.close()
        return {"status": "deleted"}

    # -----------------------------------------------------------------------
    # Budget rebalancing
    # -----------------------------------------------------------------------

    @app.get("/budgets/rebalance", tags=["budgets"],
             summary="Generate budget rebalance suggestions")
    def get_rebalance_suggestions():
        """
        Analyse average monthly spend per budget category over the last 3+ months
        and suggest adjustments for categories that are consistently over or under
        their budgeted amount.  Requires at least 30 days of transaction history.
        """
        import datetime as _dt

        conn = get_connection(db_path, read_only=True)
        try:
            # Check we have 30+ days of data
            span_row = conn.execute(
                "SELECT MIN(transaction_date), MAX(transaction_date) FROM transactions_norm"
            ).fetchone()
            if not span_row or not span_row[0] or not span_row[1]:
                return {"suggestions": [], "message": "No transaction data found."}

            min_date, max_date = span_row
            if hasattr(min_date, "date"):
                min_date = min_date.date()
            if hasattr(max_date, "date"):
                max_date = max_date.date()
            if not isinstance(min_date, _dt.date):
                min_date = _dt.date.fromisoformat(str(min_date))
            if not isinstance(max_date, _dt.date):
                max_date = _dt.date.fromisoformat(str(max_date))

            days_span = (max_date - min_date).days
            if days_span < 30:
                return {
                    "suggestions": [],
                    "message": f"Need at least 30 days of data (currently {days_span} days).",
                }

            # Get all budget goals
            budget_rows = conn.execute(
                "SELECT id, parent, category, monthly_amount "
                "FROM budget_goals ORDER BY parent, category"
            ).fetchall()
            if not budget_rows:
                return {"suggestions": [], "message": "No budgets defined yet."}

            # Compute months spanned (for averaging)
            months_spanned = max(days_span / 30.44, 1.0)

            suggestions = []
            for bid, parent, category, monthly_amount in budget_rows:
                monthly_f = float(monthly_amount)
                if monthly_f <= 0:
                    continue

                # Compute total actual spend for this category across all time
                if category:
                    actual_row = conn.execute(
                        """
                        SELECT COALESCE(SUM(resolved_amount), 0)
                        FROM transactions_norm
                        WHERE transaction_subtype = 'spending'
                          AND category_parent = ?
                          AND category_normalized = ?
                        """,
                        [parent, category],
                    ).fetchone()
                else:
                    actual_row = conn.execute(
                        """
                        SELECT COALESCE(SUM(resolved_amount), 0)
                        FROM transactions_norm
                        WHERE transaction_subtype = 'spending'
                          AND category_parent = ?
                        """,
                        [parent],
                    ).fetchone()

                total_actual = float(actual_row[0]) if actual_row else 0.0
                avg_monthly = round(total_actual / months_spanned, 2)

                # Determine if this is significantly over or under
                diff = avg_monthly - monthly_f
                diff_pct = round(diff / monthly_f * 100, 1) if monthly_f else 0.0

                # Only suggest if >=15% deviation
                if abs(diff_pct) < 15:
                    continue

                direction = "over" if diff > 0 else "under"
                # Suggest rounding to nearest $5
                suggested = round(avg_monthly / 5) * 5
                if suggested <= 0:
                    suggested = 5.0

                suggestions.append({
                    "budget_id": bid,
                    "parent": parent,
                    "category": category,
                    "current_budget": monthly_f,
                    "avg_monthly_actual": avg_monthly,
                    "suggested_budget": float(suggested),
                    "diff": round(diff, 2),
                    "diff_pct": diff_pct,
                    "direction": direction,
                    "months_analysed": round(months_spanned, 1),
                })

            # Sort: over-budget first (most urgent), then by magnitude
            suggestions.sort(key=lambda s: (-1 if s["direction"] == "over" else 1, -abs(s["diff_pct"])))

        finally:
            conn.close()

        return {
            "suggestions": suggestions,
            "data_span_days": days_span,
            "months_analysed": round(months_spanned, 1),
            "message": None,
        }

    @app.post("/budgets/rebalance/apply", tags=["budgets"],
              summary="Apply selected rebalance suggestions")
    def apply_rebalance(payload: dict):
        """
        Accept a list of budget adjustments and update monthly_amount for each.
        Payload: {"adjustments": [{"budget_id": int, "new_amount": float}, ...]}
        Does NOT auto-apply — caller must explicitly send selected adjustments.
        """
        adjustments = payload.get("adjustments", [])
        if not adjustments:
            raise HTTPException(status_code=400, detail="No adjustments provided.")

        now = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
        conn = get_connection(db_path)
        updated = 0
        try:
            for adj in adjustments:
                bid = adj.get("budget_id")
                new_amount = adj.get("new_amount")
                if bid is None or new_amount is None or float(new_amount) <= 0:
                    continue
                conn.execute(
                    "UPDATE budget_goals SET monthly_amount=?, updated_at=? WHERE id=?",
                    [float(new_amount), now, int(bid)],
                )
                updated += 1
        finally:
            conn.close()

        return {"status": "applied", "updated": updated}

    # -----------------------------------------------------------------------
    # Tags
    # -----------------------------------------------------------------------

    @app.get("/tags", tags=["tags"], summary="List all tags")
    def list_tags():
        """Return all user-defined tags ordered by name."""
        try:
            conn = get_connection(db_path, read_only=True)
            rows = conn.execute(
                "SELECT id, name, color, created_at, updated_at FROM tags ORDER BY name"
            ).fetchall()
            conn.close()
        except Exception:
            return {"tags": []}
        cols = ["id", "name", "color", "created_at", "updated_at"]
        return {"tags": [dict(zip(cols, r)) for r in rows]}

    @app.post("/tags", tags=["tags"], summary="Create a tag", status_code=201)
    def create_tag(payload: dict):
        """Create a new tag with name and optional color."""
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Tag name is required.")
        color = (payload.get("color") or "#3b82f6").strip()
        now = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
        conn = get_connection(db_path)
        try:
            existing = conn.execute("SELECT id FROM tags WHERE name = ?", [name]).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail=f"Tag '{name}' already exists.")
            conn.execute(
                "INSERT INTO tags (name, color, created_at, updated_at) VALUES (?,?,?,?)",
                [name, color, now, now],
            )
            row = conn.execute("SELECT id FROM tags WHERE name = ?", [name]).fetchone()
        finally:
            conn.close()
        return {"id": row[0], "name": name, "color": color}

    @app.put("/tags/{tag_id}", tags=["tags"], summary="Update a tag")
    def update_tag(tag_id: int, payload: dict):
        """Update tag name and/or color."""
        now = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
        conn = get_connection(db_path)
        try:
            existing = conn.execute("SELECT id FROM tags WHERE id = ?", [tag_id]).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Tag not found.")
            name = (payload.get("name") or "").strip()
            color = (payload.get("color") or "").strip()
            if name:
                conn.execute("UPDATE tags SET name=?, updated_at=? WHERE id=?", [name, now, tag_id])
            if color:
                conn.execute("UPDATE tags SET color=?, updated_at=? WHERE id=?", [color, now, tag_id])
        finally:
            conn.close()
        return {"id": tag_id, "status": "updated"}

    @app.delete("/tags/{tag_id}", tags=["tags"], summary="Delete a tag")
    def delete_tag(tag_id: int):
        """Delete a tag and all its transaction associations."""
        conn = get_connection(db_path)
        try:
            conn.execute("DELETE FROM transaction_tags WHERE tag_id = ?", [tag_id])
            conn.execute("DELETE FROM tags WHERE id = ?", [tag_id])
        finally:
            conn.close()
        return {"status": "deleted"}

    @app.post("/transactions/tags", tags=["tags"],
              summary="Assign tags to a transaction")
    def assign_tags(payload: dict):
        """
        Assign one or more tags to a transaction by fingerprint.
        Payload: {"fingerprint": str, "tag_ids": [int, ...]}
        """
        fp = payload.get("fingerprint", "")
        tag_ids = payload.get("tag_ids", [])
        if not fp or not tag_ids:
            raise HTTPException(status_code=400, detail="fingerprint and tag_ids required.")
        now = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
        conn = get_connection(db_path)
        added = 0
        try:
            for tid in tag_ids:
                existing = conn.execute(
                    "SELECT 1 FROM transaction_tags WHERE transaction_fingerprint=? AND tag_id=?",
                    [fp, int(tid)],
                ).fetchone()
                if not existing:
                    conn.execute(
                        "INSERT INTO transaction_tags (transaction_fingerprint, tag_id, created_at) "
                        "VALUES (?,?,?)",
                        [fp, int(tid), now],
                    )
                    added += 1
        finally:
            conn.close()
        return {"status": "ok", "added": added}

    @app.delete("/transactions/tags", tags=["tags"],
                summary="Remove a tag from a transaction")
    def remove_tag_from_transaction(
        fingerprint: str = Query(..., description="Transaction fingerprint"),
        tag_id: int = Query(..., description="Tag ID to remove"),
    ):
        """Remove a specific tag from a transaction."""
        conn = get_connection(db_path)
        try:
            conn.execute(
                "DELETE FROM transaction_tags WHERE transaction_fingerprint=? AND tag_id=?",
                [fingerprint, tag_id],
            )
        finally:
            conn.close()
        return {"status": "removed"}

    @app.get("/transactions/{fingerprint}/tags", tags=["tags"],
             summary="Get tags for a transaction")
    def get_transaction_tags(fingerprint: str):
        """Return all tags assigned to a specific transaction."""
        conn = get_connection(db_path, read_only=True)
        try:
            rows = conn.execute(
                """SELECT t.id, t.name, t.color
                   FROM tags t
                   JOIN transaction_tags tt ON tt.tag_id = t.id
                   WHERE tt.transaction_fingerprint = ?
                   ORDER BY t.name""",
                [fingerprint],
            ).fetchall()
        finally:
            conn.close()
        return {"tags": [{"id": r[0], "name": r[1], "color": r[2]} for r in rows]}

    @app.get("/tags/totals", tags=["tags"], summary="Per-tag spending totals")
    def tag_totals(
        year: Optional[int] = Query(None, description="Filter by year"),
        month: Optional[int] = Query(None, description="Filter by month (1-12)"),
    ):
        """
        Return spending totals per tag, optionally filtered by year/month.
        Shows both all-time and (if year/month provided) monthly totals.
        """
        conn = get_connection(db_path, read_only=True)
        try:
            # All-time totals
            alltime_rows = conn.execute(
                """SELECT t.id, t.name, t.color,
                          COUNT(*) AS txn_count,
                          ABS(COALESCE(SUM(CASE WHEN tn.amount < 0 THEN tn.amount ELSE 0 END), 0)) AS total_spending,
                          COALESCE(SUM(CASE WHEN tn.amount > 0 THEN tn.amount ELSE 0 END), 0) AS total_income
                   FROM tags t
                   JOIN transaction_tags tt ON tt.tag_id = t.id
                   JOIN transactions_norm tn ON tn.transaction_fingerprint = tt.transaction_fingerprint
                   GROUP BY t.id, t.name, t.color
                   ORDER BY total_spending DESC"""
            ).fetchall()

            monthly_totals = None
            if year and month:
                monthly_rows = conn.execute(
                    """SELECT t.id, t.name, t.color,
                              COUNT(*) AS txn_count,
                              ABS(COALESCE(SUM(CASE WHEN tn.amount < 0 THEN tn.amount ELSE 0 END), 0)) AS total_spending,
                              COALESCE(SUM(CASE WHEN tn.amount > 0 THEN tn.amount ELSE 0 END), 0) AS total_income
                       FROM tags t
                       JOIN transaction_tags tt ON tt.tag_id = t.id
                       JOIN transactions_norm tn ON tn.transaction_fingerprint = tt.transaction_fingerprint
                       WHERE YEAR(tn.transaction_date) = ? AND MONTH(tn.transaction_date) = ?
                       GROUP BY t.id, t.name, t.color
                       ORDER BY total_spending DESC""",
                    [year, month],
                ).fetchall()
                monthly_totals = [
                    {"id": r[0], "name": r[1], "color": r[2], "txn_count": int(r[3]),
                     "total_spending": float(r[4]), "total_income": float(r[5])}
                    for r in monthly_rows
                ]
        finally:
            conn.close()

        return {
            "alltime": [
                {"id": r[0], "name": r[1], "color": r[2], "txn_count": int(r[3]),
                 "total_spending": float(r[4]), "total_income": float(r[5])}
                for r in alltime_rows
            ],
            "monthly": monthly_totals,
            "year": year,
            "month": month,
        }

    # -----------------------------------------------------------------------
    # Savings Goals
    # -----------------------------------------------------------------------

    @app.get("/savings-goals", tags=["savings"], summary="List all savings goals")
    def list_savings_goals():
        """Return all savings goals ordered by target date."""
        try:
            conn = get_connection(db_path, read_only=True)
            rows = conn.execute(
                "SELECT id, name, target_amount, current_amount, target_date, "
                "linked_account, created_at, updated_at "
                "FROM savings_goals ORDER BY target_date NULLS LAST, name"
            ).fetchall()
            conn.close()
        except Exception:
            return {"goals": []}
        cols = ["id", "name", "target_amount", "current_amount", "target_date",
                "linked_account", "created_at", "updated_at"]
        goals = []
        for r in rows:
            g = dict(zip(cols, r))
            g["target_amount"] = float(g["target_amount"])
            g["current_amount"] = float(g["current_amount"])
            goals.append(g)
        return {"goals": goals}

    @app.post("/savings-goals", tags=["savings"], summary="Create a savings goal",
              status_code=201)
    def create_savings_goal(payload: dict):
        """Create a new savings goal."""
        name = (payload.get("name") or "").strip()
        target_amount = payload.get("target_amount")
        if not name or target_amount is None:
            raise HTTPException(status_code=400, detail="name and target_amount are required")
        now = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
        conn = get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO savings_goals "
                "(name, target_amount, current_amount, target_date, linked_account, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                [name, float(target_amount),
                 float(payload.get("current_amount", 0)),
                 payload.get("target_date") or None,
                 payload.get("linked_account") or None,
                 now, now],
            )
            row = conn.execute(
                "SELECT id FROM savings_goals WHERE name=? ORDER BY id DESC LIMIT 1",
                [name],
            ).fetchone()
        finally:
            conn.close()
        return {"id": row[0] if row else None, "status": "created"}

    @app.put("/savings-goals/{goal_id}", tags=["savings"],
             summary="Update a savings goal")
    def update_savings_goal(goal_id: int, payload: dict):
        """Update an existing savings goal."""
        now = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
        conn = get_connection(db_path)
        try:
            existing = conn.execute(
                "SELECT id FROM savings_goals WHERE id=?", [goal_id]
            ).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Goal not found")
            sets = []
            params = []
            for field in ("name", "target_amount", "current_amount",
                          "target_date", "linked_account"):
                if field in payload:
                    sets.append(f"{field}=?")
                    val = payload[field]
                    if field in ("target_amount", "current_amount"):
                        val = float(val) if val is not None else 0
                    params.append(val)
            if not sets:
                raise HTTPException(status_code=400, detail="No fields to update")
            sets.append("updated_at=?")
            params.append(now)
            params.append(goal_id)
            conn.execute(
                f"UPDATE savings_goals SET {', '.join(sets)} WHERE id=?", params
            )
        finally:
            conn.close()
        return {"id": goal_id, "status": "updated"}

    @app.delete("/savings-goals/{goal_id}", tags=["savings"],
                summary="Delete a savings goal")
    def delete_savings_goal(goal_id: int):
        """Delete a savings goal by ID."""
        conn = get_connection(db_path)
        try:
            conn.execute("DELETE FROM savings_goals WHERE id=?", [goal_id])
        finally:
            conn.close()
        return {"status": "deleted"}

    @app.post("/savings-goals/{goal_id}/update-progress", tags=["savings"],
              summary="Add a manual progress update to a savings goal")
    def update_savings_progress(goal_id: int, payload: dict):
        """Add or set the current saved amount for a goal."""
        amount = payload.get("amount")
        mode = payload.get("mode", "set")  # "set" or "add"
        if amount is None:
            raise HTTPException(status_code=400, detail="amount is required")
        now = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
        conn = get_connection(db_path)
        try:
            existing = conn.execute(
                "SELECT id, current_amount FROM savings_goals WHERE id=?", [goal_id]
            ).fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Goal not found")
            if mode == "add":
                new_amount = float(existing[1]) + float(amount)
            else:
                new_amount = float(amount)
            conn.execute(
                "UPDATE savings_goals SET current_amount=?, updated_at=? WHERE id=?",
                [new_amount, now, goal_id],
            )
        finally:
            conn.close()
        return {"id": goal_id, "current_amount": new_amount, "status": "updated"}

    @app.get("/savings-goals/suggestions", tags=["savings"],
             summary="Suggest monthly savings based on average net cash flow")
    def savings_suggestions():
        """
        Calculate average monthly net cash flow over the last 6 months and
        suggest a monthly savings amount (50% of average net if positive).
        """
        import datetime as _dt
        today = _dt.date.today()
        d_from = (today.replace(day=1) - _dt.timedelta(days=180)).replace(day=1)
        conn = get_connection(db_path, read_only=True)
        try:
            rows = conn.execute(
                """SELECT
                     DATE_TRUNC('month', transaction_date) AS month,
                     COALESCE(SUM(amount), 0) AS net
                   FROM transactions_norm
                   WHERE transaction_date >= ?
                   GROUP BY 1 ORDER BY 1""",
                [d_from.isoformat()],
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return {
                "avg_monthly_net": 0,
                "suggested_monthly_savings": 0,
                "months_analysed": 0,
            }
        nets = [float(r[1]) for r in rows]
        avg_net = sum(nets) / len(nets)
        suggested = round(max(avg_net * 0.5, 0), 2)
        return {
            "avg_monthly_net": round(avg_net, 2),
            "suggested_monthly_savings": suggested,
            "months_analysed": len(nets),
        }

    # -----------------------------------------------------------------------
    # Monthly Summaries
    # -----------------------------------------------------------------------

    def _generate_monthly_summary(conn, year: int, month: int) -> dict:
        """Build a monthly summary dict with metrics and plain-language narrative."""
        import datetime as _dt, json as _json, calendar as _cal

        month_name = _cal.month_name[month]

        # Total spending
        spend_row = conn.execute(
            """SELECT COALESCE(SUM(resolved_amount), 0), COUNT(*)
               FROM transactions_norm
               WHERE transaction_subtype = 'spending'
                 AND YEAR(transaction_date) = ? AND MONTH(transaction_date) = ?""",
            [year, month],
        ).fetchone()
        total_spent = float(spend_row[0])
        txn_count = int(spend_row[1])

        # Total income
        income_row = conn.execute(
            """SELECT COALESCE(SUM(amount), 0)
               FROM transactions_norm
               WHERE amount > 0
                 AND YEAR(transaction_date) = ? AND MONTH(transaction_date) = ?""",
            [year, month],
        ).fetchone()
        total_income = float(income_row[0])
        net_savings = total_income - total_spent

        # Prior month spending for delta
        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        prev_row = conn.execute(
            """SELECT COALESCE(SUM(resolved_amount), 0)
               FROM transactions_norm
               WHERE transaction_subtype = 'spending'
                 AND YEAR(transaction_date) = ? AND MONTH(transaction_date) = ?""",
            [prev_year, prev_month],
        ).fetchone()
        prev_spent = float(prev_row[0])
        spend_delta_pct = (
            round((total_spent - prev_spent) / prev_spent * 100, 1)
            if prev_spent > 0 else None
        )

        # Top 3 categories
        top_cats = conn.execute(
            """SELECT COALESCE(category_parent, category) AS grp,
                      SUM(resolved_amount) AS amt
               FROM transactions_norm
               WHERE transaction_subtype = 'spending'
                 AND YEAR(transaction_date) = ? AND MONTH(transaction_date) = ?
                 AND COALESCE(category_parent, category) IS NOT NULL
               GROUP BY grp ORDER BY amt DESC LIMIT 3""",
            [year, month],
        ).fetchall()
        top_categories = [{"name": r[0], "amount": float(r[1])} for r in top_cats]

        # Per-category delta vs prior month
        for cat in top_categories:
            prev_cat = conn.execute(
                """SELECT COALESCE(SUM(resolved_amount), 0)
                   FROM transactions_norm
                   WHERE transaction_subtype = 'spending'
                     AND YEAR(transaction_date) = ? AND MONTH(transaction_date) = ?
                     AND COALESCE(category_parent, category) = ?""",
                [prev_year, prev_month, cat["name"]],
            ).fetchone()
            prev_amt = float(prev_cat[0])
            cat["delta_pct"] = (
                round((cat["amount"] - prev_amt) / prev_amt * 100, 1)
                if prev_amt > 0 else None
            )

        # Top 3 merchants
        top_merchs = conn.execute(
            """SELECT merchant, SUM(resolved_amount) AS amt
               FROM transactions_norm
               WHERE transaction_subtype = 'spending'
                 AND YEAR(transaction_date) = ? AND MONTH(transaction_date) = ?
                 AND merchant IS NOT NULL
               GROUP BY merchant ORDER BY amt DESC LIMIT 3""",
            [year, month],
        ).fetchall()
        top_merchants = [{"name": r[0], "amount": float(r[1])} for r in top_merchs]

        # Biggest single transaction
        big_row = conn.execute(
            """SELECT description, merchant, resolved_amount, transaction_date,
                      COALESCE(category_parent, category_normalized) AS cat
               FROM transactions_norm
               WHERE transaction_subtype = 'spending'
                 AND YEAR(transaction_date) = ? AND MONTH(transaction_date) = ?
               ORDER BY resolved_amount DESC LIMIT 1""",
            [year, month],
        ).fetchone()
        biggest_txn = None
        if big_row:
            biggest_txn = {
                "description": big_row[0],
                "merchant": big_row[1],
                "amount": float(big_row[2]),
                "date": _isoformat(big_row[3]) if big_row[3] else None,
                "category": big_row[4],
            }

        # Build narrative
        def _fmt(v):
            return f"${abs(v):,.2f}"

        lines = [f"In {month_name} {year}, you spent {_fmt(total_spent)} across {txn_count} transactions."]

        if spend_delta_pct is not None:
            direction = "up" if spend_delta_pct > 0 else "down"
            lines.append(
                f"That's {direction} {abs(spend_delta_pct)}% compared to "
                f"{_cal.month_name[prev_month]}."
            )

        if top_categories:
            cat_parts = []
            for c in top_categories:
                part = f"{_fmt(c['amount'])} on {c['name']}"
                if c.get("delta_pct") is not None:
                    d = c["delta_pct"]
                    part += f" ({'up' if d > 0 else 'down'} {abs(d)}%)"
                cat_parts.append(part)
            lines.append("Your top categories were: " + ", ".join(cat_parts) + ".")

        if top_merchants:
            merch_parts = [f"{m['name']} ({_fmt(m['amount'])})" for m in top_merchants]
            lines.append("Top merchants: " + ", ".join(merch_parts) + ".")

        if biggest_txn:
            label = biggest_txn["merchant"] or biggest_txn["description"]
            lines.append(
                f"Your biggest single purchase was {_fmt(biggest_txn['amount'])} "
                f"at {label}"
                + (f" in {biggest_txn['category']}" if biggest_txn["category"] else "")
                + "."
            )

        if total_income > 0:
            lines.append(f"You earned {_fmt(total_income)} in income.")
            if net_savings >= 0:
                lines.append(f"Net savings for the month: {_fmt(net_savings)}.")
            else:
                lines.append(
                    f"You spent {_fmt(abs(net_savings))} more than you earned."
                )

        narrative = " ".join(lines)

        summary = {
            "year": year,
            "month": month,
            "month_name": month_name,
            "total_spent": total_spent,
            "total_income": total_income,
            "net_savings": net_savings,
            "txn_count": txn_count,
            "spend_delta_pct": spend_delta_pct,
            "prev_month_spent": prev_spent,
            "top_categories": top_categories,
            "top_merchants": top_merchants,
            "biggest_transaction": biggest_txn,
        }
        return {"summary": summary, "narrative": narrative}

    @app.post("/monthly-summaries/generate", tags=["summaries"],
              summary="Generate or regenerate a monthly summary")
    def generate_monthly_summary(
        year: int = Query(..., description="Year"),
        month: int = Query(..., description="Month (1-12)"),
    ):
        """Generate a monthly summary and store it. Overwrites if exists."""
        import json as _json
        if month < 1 or month > 12:
            raise HTTPException(status_code=400, detail="month must be 1-12")

        now = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()
        conn = get_connection(db_path)
        try:
            result = _generate_monthly_summary(conn, year, month)
            summary_json = _json.dumps(result["summary"])
            narrative = result["narrative"]

            existing = conn.execute(
                "SELECT id FROM monthly_summaries WHERE year=? AND month=?",
                [year, month],
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE monthly_summaries SET summary_json=?, narrative=?, "
                    "created_at=? WHERE id=?",
                    [summary_json, narrative, now, existing[0]],
                )
                row_id = existing[0]
            else:
                conn.execute(
                    "INSERT INTO monthly_summaries (year, month, summary_json, "
                    "narrative, created_at) VALUES (?,?,?,?,?)",
                    [year, month, summary_json, narrative, now],
                )
                row = conn.execute(
                    "SELECT id FROM monthly_summaries WHERE year=? AND month=?",
                    [year, month],
                ).fetchone()
                row_id = row[0] if row else None
        finally:
            conn.close()

        return {
            "id": row_id,
            "year": year,
            "month": month,
            "summary": result["summary"],
            "narrative": narrative,
            "created_at": now,
        }

    @app.get("/monthly-summaries", tags=["summaries"],
             summary="List all stored monthly summaries")
    def list_monthly_summaries():
        """Return all stored monthly summaries, newest first."""
        import json as _json
        try:
            conn = get_connection(db_path, read_only=True)
            rows = conn.execute(
                "SELECT id, year, month, summary_json, narrative, created_at "
                "FROM monthly_summaries ORDER BY year DESC, month DESC"
            ).fetchall()
            conn.close()
        except Exception:
            return {"summaries": []}
        result = []
        for r in rows:
            try:
                summary = _json.loads(r[3])
            except Exception:
                summary = {}
            result.append({
                "id": r[0], "year": r[1], "month": r[2],
                "summary": summary, "narrative": r[4], "created_at": r[5],
            })
        return {"summaries": result}

    @app.get("/monthly-summaries/{year}/{month}", tags=["summaries"],
             summary="Get a specific monthly summary")
    def get_monthly_summary(year: int, month: int):
        """Return a stored monthly summary, or generate on-the-fly if not found."""
        import json as _json
        conn = get_connection(db_path, read_only=True)
        try:
            row = conn.execute(
                "SELECT id, summary_json, narrative, created_at "
                "FROM monthly_summaries WHERE year=? AND month=?",
                [year, month],
            ).fetchone()
        finally:
            conn.close()

        if row:
            try:
                summary = _json.loads(row[1])
            except Exception:
                summary = {}
            return {
                "id": row[0], "year": year, "month": month,
                "summary": summary, "narrative": row[2],
                "created_at": row[3], "stored": True,
            }

        # Not stored yet — generate on-the-fly without storing
        conn = get_connection(db_path, read_only=True)
        try:
            result = _generate_monthly_summary(conn, year, month)
        finally:
            conn.close()
        return {
            "id": None, "year": year, "month": month,
            "summary": result["summary"], "narrative": result["narrative"],
            "created_at": None, "stored": False,
        }

    @app.delete("/monthly-summaries/{year}/{month}", tags=["summaries"],
                summary="Delete a stored monthly summary")
    def delete_monthly_summary(year: int, month: int):
        """Delete a stored monthly summary."""
        conn = get_connection(db_path)
        try:
            conn.execute(
                "DELETE FROM monthly_summaries WHERE year=? AND month=?",
                [year, month],
            )
        finally:
            conn.close()
        return {"status": "deleted"}

    # -----------------------------------------------------------------------
    # Dashboard summary
    # -----------------------------------------------------------------------

    @app.get("/dashboard/summary", tags=["dashboard"], summary="Dashboard summary metrics")
    def get_dashboard_summary(
        year: int = Query(
            default=__import__("datetime").datetime.now().year,
            description="Year for MTD summary",
        ),
        month: int = Query(
            default=__import__("datetime").datetime.now().month,
            description="Month for MTD summary (1-12)",
        ),
    ):
        """
        Return dashboard summary metrics for a given year+month:
          - mtd_spend, mtd_count
          - top_categories (top 8 by spending)
          - top_merchants (top 8 by spending)
          - recent_transactions (last 10)
          - budgets_vs_actual
        """
        try:
            conn = get_connection(db_path, read_only=True)

            # MTD spend & count
            mtd_row = conn.execute(
                """
                SELECT COALESCE(SUM(resolved_amount), 0), COUNT(*)
                FROM transactions_norm
                WHERE transaction_subtype = 'spending'
                  AND YEAR(transaction_date) = ?
                  AND MONTH(transaction_date) = ?
                """,
                [year, month],
            ).fetchone()
            mtd_spend = float(mtd_row[0]) if mtd_row else 0.0
            mtd_count = int(mtd_row[1]) if mtd_row else 0

            # Top categories
            top_cat_rows = conn.execute(
                """
                SELECT
                    COALESCE(category_parent, category) AS grp,
                    SUM(resolved_amount) AS total_amount,
                    COUNT(*) AS cnt
                FROM transactions_norm
                WHERE transaction_subtype = 'spending'
                  AND YEAR(transaction_date) = ?
                  AND MONTH(transaction_date) = ?
                  AND COALESCE(category_parent, category) IS NOT NULL
                GROUP BY grp
                ORDER BY total_amount DESC
                LIMIT 8
                """,
                [year, month],
            ).fetchall()
            top_categories = [
                {"category_parent": r[0], "total_amount": float(r[1]), "count": int(r[2])}
                for r in top_cat_rows
            ]

            # Top merchants
            top_merch_rows = conn.execute(
                """
                SELECT merchant, SUM(resolved_amount) AS total_amount, COUNT(*) AS cnt
                FROM transactions_norm
                WHERE transaction_subtype = 'spending'
                  AND YEAR(transaction_date) = ?
                  AND MONTH(transaction_date) = ?
                  AND merchant IS NOT NULL
                GROUP BY merchant
                ORDER BY total_amount DESC
                LIMIT 8
                """,
                [year, month],
            ).fetchall()
            top_merchants = [
                {"merchant": r[0], "total_amount": float(r[1]), "count": int(r[2])}
                for r in top_merch_rows
            ]

            # Recent transactions
            recent_rows = conn.execute(
                """
                SELECT transaction_date, description, merchant, category_normalized,
                       category_parent, resolved_amount, bank_name,
                       COALESCE(unreviewed, TRUE) AS unreviewed,
                       transaction_fingerprint
                FROM transactions_norm
                ORDER BY transaction_date DESC, ingested_at DESC
                LIMIT 10
                """
            ).fetchall()
            recent_cols = [
                "transaction_date", "description", "merchant",
                "category_normalized", "category_parent", "amount", "bank_name",
                "unreviewed", "transaction_fingerprint",
            ]
            recent_transactions = [
                {k: (_isoformat(v) if k == "transaction_date" else v)
                 for k, v in zip(recent_cols, r)}
                for r in recent_rows
            ]

            # Budgets vs actual
            budget_rows = conn.execute(
                "SELECT id, parent, category, monthly_amount FROM budget_goals ORDER BY parent, category"
            ).fetchall()
            budgets_vs_actual = []
            for _bid, parent, category, monthly_amount in budget_rows:
                if category:
                    actual_row = conn.execute(
                        """
                        SELECT COALESCE(SUM(resolved_amount), 0)
                        FROM transactions_norm
                        WHERE transaction_subtype = 'spending'
                          AND YEAR(transaction_date) = ?
                          AND MONTH(transaction_date) = ?
                          AND category_parent = ?
                          AND category_normalized = ?
                        """,
                        [year, month, parent, category],
                    ).fetchone()
                else:
                    actual_row = conn.execute(
                        """
                        SELECT COALESCE(SUM(resolved_amount), 0)
                        FROM transactions_norm
                        WHERE transaction_subtype = 'spending'
                          AND YEAR(transaction_date) = ?
                          AND MONTH(transaction_date) = ?
                          AND category_parent = ?
                        """,
                        [year, month, parent],
                    ).fetchone()
                actual = float(actual_row[0]) if actual_row else 0.0
                monthly_f = float(monthly_amount)
                pct = round(actual / monthly_f * 100, 1) if monthly_f > 0 else None
                budgets_vs_actual.append({
                    "parent": parent,
                    "monthly_amount": monthly_f,
                    "actual_amount": actual,
                    "pct": pct,
                })

            # Spending alerts: derive from budgets_vs_actual
            spending_alerts = []
            for bva in budgets_vs_actual:
                if bva["pct"] is not None and bva["pct"] >= 80:
                    status = "exceeded" if bva["pct"] >= 100 else "warning"
                    spending_alerts.append({
                        "parent": bva["parent"],
                        "budget": bva["monthly_amount"],
                        "spent": bva["actual_amount"],
                        "pct": bva["pct"],
                        "status": status,
                    })

            # Unreviewed count (global, not month-scoped)
            unrev_row = conn.execute(
                "SELECT COUNT(*) FROM transactions_norm WHERE COALESCE(unreviewed, TRUE) = TRUE"
            ).fetchone()
            unreviewed_count = int(unrev_row[0]) if unrev_row else 0

            # Active savings goals summary
            savings_goals_summary = []
            try:
                sg_rows = conn.execute(
                    "SELECT id, name, target_amount, current_amount, target_date "
                    "FROM savings_goals ORDER BY target_date NULLS LAST, name"
                ).fetchall()
                for sg in sg_rows:
                    target = float(sg[2])
                    current = float(sg[3])
                    pct_done = round(current / target * 100, 1) if target > 0 else 0
                    savings_goals_summary.append({
                        "id": sg[0], "name": sg[1],
                        "target_amount": target,
                        "current_amount": current,
                        "target_date": sg[4],
                        "pct": min(pct_done, 100),
                    })
            except Exception:
                pass  # table may not exist yet

            conn.close()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Dashboard query failed: {exc}") from exc

        return {
            "year": year,
            "month": month,
            "mtd_spend": mtd_spend,
            "mtd_count": mtd_count,
            "top_categories": top_categories,
            "top_merchants": top_merchants,
            "recent_transactions": recent_transactions,
            "budgets_vs_actual": budgets_vs_actual,
            "spending_alerts": spending_alerts,
            "unreviewed_count": unreviewed_count,
            "savings_goals": savings_goals_summary,
        }

    # -----------------------------------------------------------------------
    # Cash Flow
    # -----------------------------------------------------------------------

    @app.get("/cashflow/summary", tags=["cashflow"],
             summary="Cash flow summary with monthly breakdown")
    def get_cashflow_summary(
        period: str = Query(
            "last_3_months",
            description="Preset period: this_month, last_month, last_3_months, last_12_months, custom",
        ),
        start_date: Optional[str] = Query(None, description="ISO start date for custom range"),
        end_date: Optional[str] = Query(None, description="ISO end date for custom range"),
        include_transfers: bool = Query(False, description="Include transfer/payment transactions"),
    ):
        """
        Return cash flow summary: income vs spending vs net, monthly breakdown,
        category breakdown, and month-over-month delta.

        Uses the signed `amount` column: positive = income, negative = spending.
        """
        import datetime as _dt

        now = _dt.date.today()

        # Resolve date range from preset
        if period == "this_month":
            d_from = now.replace(day=1)
            d_to = now
        elif period == "last_month":
            first_this = now.replace(day=1)
            last_prev = first_this - _dt.timedelta(days=1)
            d_from = last_prev.replace(day=1)
            d_to = last_prev
        elif period == "last_3_months":
            d_to = now
            m = now.month - 2
            y = now.year
            while m < 1:
                m += 12
                y -= 1
            d_from = _dt.date(y, m, 1)
        elif period == "last_12_months":
            d_to = now
            m = now.month
            y = now.year - 1
            d_from = _dt.date(y, m, 1)
        elif period == "custom" and start_date and end_date:
            d_from = _dt.date.fromisoformat(start_date)
            d_to = _dt.date.fromisoformat(end_date)
        else:
            d_from = now.replace(day=1)
            d_to = now

        try:
            conn = get_connection(db_path, read_only=True)

            # Build transfer exclusion clause
            transfer_clause = ""
            if not include_transfers:
                transfer_clause = (
                    " AND COALESCE(transaction_subtype, '') != 'payment'"
                    " AND LOWER(COALESCE(category, '')) NOT LIKE '%transfer%'"
                )

            # ── Summary totals ──────────────────────────────────────
            summary_row = conn.execute(
                f"""
                SELECT
                    COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0),
                    ABS(COALESCE(SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END), 0)),
                    COALESCE(SUM(amount), 0),
                    COUNT(*)
                FROM transactions_norm
                WHERE transaction_date >= ? AND transaction_date <= ?
                {transfer_clause}
                """,
                [d_from.isoformat(), d_to.isoformat()],
            ).fetchone()
            total_income = float(summary_row[0])
            total_spending = float(summary_row[1])
            net = float(summary_row[2])
            txn_count = int(summary_row[3])

            # ── Monthly breakdown ───────────────────────────────────
            monthly_rows = conn.execute(
                f"""
                SELECT
                    DATE_TRUNC('month', transaction_date) AS month,
                    COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0) AS income,
                    ABS(COALESCE(SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END), 0)) AS spending,
                    COALESCE(SUM(amount), 0) AS net
                FROM transactions_norm
                WHERE transaction_date >= ? AND transaction_date <= ?
                {transfer_clause}
                GROUP BY 1
                ORDER BY 1
                """,
                [d_from.isoformat(), d_to.isoformat()],
            ).fetchall()
            monthly = [
                {
                    "month": _isoformat(r[0])[:10],
                    "income": float(r[1]),
                    "spending": float(r[2]),
                    "net": float(r[3]),
                }
                for r in monthly_rows
            ]

            # ── Category breakdown (spending only) ──────────────────
            cat_rows = conn.execute(
                f"""
                SELECT
                    COALESCE(category_parent, category, 'Uncategorized') AS grp,
                    ABS(SUM(amount)) AS total
                FROM transactions_norm
                WHERE transaction_date >= ? AND transaction_date <= ?
                  AND amount < 0
                {transfer_clause}
                GROUP BY grp
                ORDER BY total DESC
                LIMIT 12
                """,
                [d_from.isoformat(), d_to.isoformat()],
            ).fetchall()
            cat_total = sum(float(r[1]) for r in cat_rows) if cat_rows else 1.0
            by_category = [
                {
                    "category": r[0],
                    "amount": float(r[1]),
                    "pct": round(float(r[1]) / cat_total * 100, 1) if cat_total else 0,
                }
                for r in cat_rows
            ]

            # ── Month-over-month delta ──────────────────────────────
            # Compare the most recent full month to the one before it
            mom_delta = None
            if len(monthly) >= 2:
                curr = monthly[-1]
                prev = monthly[-2]
                delta = curr["net"] - prev["net"]
                spending_delta = curr["spending"] - prev["spending"]
                mom_delta = {
                    "current_month": curr["month"],
                    "prior_month": prev["month"],
                    "current_net": curr["net"],
                    "prior_net": prev["net"],
                    "delta": delta,
                    "current_spending": curr["spending"],
                    "prior_spending": prev["spending"],
                    "spending_delta": spending_delta,
                }

            conn.close()

        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Cash flow query failed: {exc}"
            ) from exc

        return {
            "period": {
                "preset": period,
                "start_date": d_from.isoformat(),
                "end_date": d_to.isoformat(),
            },
            "summary": {
                "total_income": total_income,
                "total_spending": total_spending,
                "net": net,
                "transaction_count": txn_count,
            },
            "monthly": monthly,
            "by_category": by_category,
            "mom_delta": mom_delta,
            "include_transfers": include_transfers,
        }

    # -----------------------------------------------------------------------
    # Recurring Transactions
    # -----------------------------------------------------------------------

    @app.get("/recurring", tags=["recurring"],
             summary="Detect recurring transactions")
    def get_recurring():
        """
        Analyse transaction history and return detected recurring charges.
        User overrides (mark/unmark) are merged into the results.
        Returns the pattern list and an estimated monthly total.
        """
        from finance_etl.recurring import detect_recurring, compute_monthly_recurring_total
        from finance_etl.db import get_connection as _gc

        try:
            conn = _gc(db_path, read_only=True)
            patterns = detect_recurring(conn)
            monthly_total = compute_monthly_recurring_total(patterns)
            conn.close()
        except Exception as exc:
            raise HTTPException(status_code=500,
                                detail=f"Recurring detection failed: {exc}") from exc

        return {
            "patterns": patterns,
            "monthly_total": monthly_total,
            "count": len(patterns),
        }

    @app.post("/recurring/override", tags=["recurring"],
              summary="Mark or unmark a merchant as recurring")
    def set_recurring_override(body: dict):
        """
        Set a manual override for a merchant's recurring status.

        Body: ``{"merchant": "Netflix", "is_recurring": true}``

        Setting ``is_recurring: true`` forces the merchant into the recurring
        list even if auto-detection didn't flag it.  Setting ``false`` removes
        it from the list even if auto-detected.
        """
        import datetime as _dt
        from finance_etl.db import get_connection as _gc

        merchant = body.get("merchant", "").strip()
        is_recurring = body.get("is_recurring")
        if not merchant or is_recurring is None:
            raise HTTPException(status_code=400,
                                detail="merchant and is_recurring are required.")

        now = _dt.datetime.utcnow().isoformat()
        try:
            conn = _gc(db_path)
            # Upsert: DuckDB doesn't support ON CONFLICT on all versions,
            # so delete-then-insert pattern is safest.
            conn.execute(
                "DELETE FROM recurring_overrides WHERE merchant_key = ?",
                [merchant],
            )
            conn.execute(
                """INSERT INTO recurring_overrides
                   (merchant_key, is_recurring, created_at, updated_at)
                   VALUES (?, ?, ?, ?)""",
                [merchant, bool(is_recurring), now, now],
            )
            conn.close()
        except Exception as exc:
            raise HTTPException(status_code=500,
                                detail=f"Override failed: {exc}") from exc

        return {"status": "ok", "merchant": merchant, "is_recurring": is_recurring}

    @app.delete("/recurring/override/{merchant}", tags=["recurring"],
                summary="Remove a recurring override")
    def delete_recurring_override(merchant: str):
        """Remove a user override, reverting to auto-detection for this merchant."""
        from finance_etl.db import get_connection as _gc

        try:
            conn = _gc(db_path)
            conn.execute(
                "DELETE FROM recurring_overrides WHERE merchant_key = ?",
                [merchant],
            )
            conn.close()
        except Exception as exc:
            raise HTTPException(status_code=500,
                                detail=f"Delete override failed: {exc}") from exc

        return {"status": "ok", "merchant": merchant}

    # -----------------------------------------------------------------------
    # Backup & Restore  (v2 — comprehensive full-state backup)
    # -----------------------------------------------------------------------

    # Tables exported/restored in dependency order (parents before children)
    _BACKUP_TABLES = [
        "runs",
        "merchant_rules",
        "merchant_category_map",
        "category_rules",
        "budget_goals",
        "recurring_overrides",
        "normalization_jobs",
        "transactions_stage",
        "transactions_norm",
        "tags",
        "transaction_tags",
        "savings_goals",
        "monthly_summaries",
    ]

    def _rows_to_dicts(cursor_result) -> list[dict]:
        """Convert a DuckDB cursor result to a list of dicts."""
        if cursor_result.description is None:
            return []
        cols = [d[0] for d in cursor_result.description]
        return [dict(zip(cols, row)) for row in cursor_result.fetchall()]

    def _get_schema_version(conn) -> int:
        """Read the current DuckDB schema version (defaults to 1)."""
        try:
            row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            return row[0] if row else 1
        except Exception:
            return 1

    def _collect_wizard_profiles() -> dict[str, str]:
        """Read all YAML wizard profiles into {relative_path: content}."""
        profiles: dict[str, str] = {}
        profiles_path = Path(wizard_profiles_dir)
        if profiles_path.exists():
            for f in sorted(profiles_path.rglob("*.yaml")):
                rel = str(f.relative_to(profiles_path))
                profiles[rel] = f.read_text(encoding="utf-8")
            for f in sorted(profiles_path.rglob("*.yml")):
                rel = str(f.relative_to(profiles_path))
                if rel not in profiles:
                    profiles[rel] = f.read_text(encoding="utf-8")
        return profiles

    def _write_auto_backup(payload_bytes: bytes) -> Path:
        """
        Write an auto-backup file and rotate to keep at most 5.
        Returns the path of the newly created backup file.
        """
        import datetime as _dt
        auto_dir = Path("data/auto_backups")
        auto_dir.mkdir(parents=True, exist_ok=True)

        ts = _dt.datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
        dest = auto_dir / f"auto_backup_{ts}.json"
        dest.write_bytes(payload_bytes)

        # Rotate: keep only the 5 most recent
        existing = sorted(auto_dir.glob("auto_backup_*.json"), key=lambda p: p.name, reverse=True)
        for old in existing[5:]:
            old.unlink(missing_ok=True)

        return dest

    def _create_export_payload() -> bytes:
        """Build a v2 backup payload and return it as UTF-8 JSON bytes."""
        import datetime as _dt
        from finance_etl.backup_migrations import CURRENT_BACKUP_VERSION
        from finance_etl.db import get_connection as _gc

        conn = _gc(db_path, read_only=True)
        data: dict[str, Any] = {}
        for table in _BACKUP_TABLES:
            data[table] = _rows_to_dicts(conn.execute(f"SELECT * FROM {table}"))
        schema_ver = _get_schema_version(conn)
        conn.close()

        payload = {
            "backup_version": CURRENT_BACKUP_VERSION,
            "app_version": "2.0.0",
            "created_at": _dt.datetime.utcnow().isoformat() + "Z",
            "duckdb_schema_version": schema_ver,
            "data": data,
            "wizard_profiles": _collect_wizard_profiles(),
        }
        return json.dumps(payload, indent=2, default=str).encode("utf-8")

    @app.get("/backup/export", tags=["backup"], summary="Export all user data as JSON (v2)")
    def export_backup():
        """
        Export the complete application state — all DuckDB tables and YAML
        wizard profiles — as a single versioned JSON document.
        """
        from fastapi.responses import Response as FastAPIResponse
        import datetime as _dt

        try:
            body = _create_export_payload()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Export failed: {exc}") from exc

        ts = _dt.datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
        filename = f"spendly_backup_{ts}.json"
        return FastAPIResponse(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/backup/restore", tags=["backup"],
              summary="Restore user data from a JSON backup (v1 or v2)",
              status_code=200)
    async def restore_backup(file: UploadFile = File(...)):
        """
        Restore the full application state from a JSON backup.

        Accepts both v1 (legacy partial) and v2 (full) backups. A v1 payload
        is automatically migrated to v2 before applying. An auto-snapshot of
        the current state is saved to data/auto_backups/ before overwriting.
        """
        import datetime as _dt
        from finance_etl.backup_migrations import CURRENT_BACKUP_VERSION, run_migrations
        from finance_etl.db import get_connection as _gc

        raw = await file.read()
        try:
            payload = json.loads(raw)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON file.")

        version = payload.get("backup_version")
        if version is None or not isinstance(version, int):
            raise HTTPException(status_code=400, detail="Missing or invalid backup_version.")
        if version > CURRENT_BACKUP_VERSION:
            raise HTTPException(
                status_code=400,
                detail=f"Backup version {version} is newer than supported ({CURRENT_BACKUP_VERSION}). "
                       "Please upgrade the application.",
            )

        # ── Migrate legacy payloads to current version ───────────────────
        if version < CURRENT_BACKUP_VERSION:
            payload = run_migrations(payload, version, CURRENT_BACKUP_VERSION)

        data = payload.get("data", {})
        now = _dt.datetime.utcnow().isoformat()

        # ── Auto-snapshot current state before overwriting ────────────────
        try:
            snapshot = _create_export_payload()
            _write_auto_backup(snapshot)
        except Exception:
            pass  # Non-fatal — don't block restore if snapshot fails

        try:
            conn = _gc(db_path)

            # ── Restore DuckDB tables (truncate + reinsert, dependency order) ──

            # 1. runs
            conn.execute("DELETE FROM runs")
            for r in data.get("runs", []):
                conn.execute(
                    """INSERT INTO runs (run_id, started_at, finished_at, status,
                       statement_type, run_label, files_count, rows_in, rows_staged,
                       rows_normalized, rows_loaded, errors_count, notes, imported_file)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [r.get("run_id"), r.get("started_at"), r.get("finished_at"),
                     r.get("status"), r.get("statement_type"), r.get("run_label"),
                     r.get("files_count"), r.get("rows_in"), r.get("rows_staged"),
                     r.get("rows_normalized"), r.get("rows_loaded"),
                     r.get("errors_count"), r.get("notes"), r.get("imported_file")],
                )

            # 2. merchant_rules — includes conditions/logic for compound rules
            conn.execute("DELETE FROM merchant_rules")
            for r in data.get("merchant_rules", []):
                conn.execute(
                    """INSERT INTO merchant_rules
                       (pattern, match_type, merchant, priority, created_at, updated_at,
                        conditions, logic)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    [r["pattern"], r.get("match_type", "contains"), r["merchant"],
                     r.get("priority", 0), r.get("created_at", now), r.get("updated_at", now),
                     r.get("conditions"), r.get("logic", "AND")],
                )

            # 3. merchant_category_map
            conn.execute("DELETE FROM merchant_category_map")
            for r in data.get("merchant_category_map", data.get("merchant_categories", [])):
                conn.execute(
                    """INSERT INTO merchant_category_map (merchant, category, source, updated_at)
                       VALUES (?,?,?,?)""",
                    [r["merchant"], r["category"], r.get("source", "user"),
                     r.get("updated_at", now)],
                )

            # 4. category_rules
            conn.execute("DELETE FROM category_rules")
            for r in data.get("category_rules", []):
                conn.execute(
                    """INSERT INTO category_rules
                       (raw_category, category, parent, created_at, updated_at)
                       VALUES (?,?,?,?,?)""",
                    [r["raw_category"], r["category"], r["parent"],
                     r.get("created_at", now), r.get("updated_at", now)],
                )

            # 5. budget_goals
            conn.execute("DELETE FROM budget_goals")
            for r in data.get("budget_goals", []):
                conn.execute(
                    """INSERT INTO budget_goals
                       (parent, category, monthly_amount, created_at, updated_at)
                       VALUES (?,?,?,?,?)""",
                    [r["parent"], r.get("category"), r["monthly_amount"],
                     r.get("created_at", now), r.get("updated_at", now)],
                )

            # 6. recurring_overrides
            conn.execute("DELETE FROM recurring_overrides")
            for r in data.get("recurring_overrides", []):
                conn.execute(
                    """INSERT INTO recurring_overrides
                       (merchant_key, is_recurring, created_at, updated_at)
                       VALUES (?,?,?,?)""",
                    [r["merchant_key"], r.get("is_recurring", True),
                     r.get("created_at", now), r.get("updated_at", now)],
                )

            # 7. normalization_jobs
            conn.execute("DELETE FROM normalization_jobs")
            for r in data.get("normalization_jobs", []):
                conn.execute(
                    """INSERT INTO normalization_jobs
                       (job_id, status, rows_total, rows_done, error,
                        started_at, finished_at, created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    [r["job_id"], r.get("status", "pending"), r.get("rows_total"),
                     r.get("rows_done", 0), r.get("error"),
                     r.get("started_at"), r.get("finished_at"),
                     r.get("created_at", now)],
                )

            # 8. transactions_stage
            conn.execute("DELETE FROM transactions_stage")
            for r in data.get("transactions_stage", []):
                conn.execute(
                    """INSERT INTO transactions_stage
                       (run_id, file_hash, source_file, source_row, bank_name,
                        account_name, account_id, transaction_date_raw,
                        posted_date_raw, description_raw, amount_raw, debit_raw,
                        credit_raw, money_in_raw, money_out_raw, dc_flag_raw,
                        currency_raw, extra_json, amount_debit_raw, amount_credit_raw)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [r.get("run_id"), r.get("file_hash"), r.get("source_file"),
                     r.get("source_row"), r.get("bank_name"), r.get("account_name"),
                     r.get("account_id"), r.get("transaction_date_raw"),
                     r.get("posted_date_raw"), r.get("description_raw"),
                     r.get("amount_raw"), r.get("debit_raw"), r.get("credit_raw"),
                     r.get("money_in_raw"), r.get("money_out_raw"),
                     r.get("dc_flag_raw"), r.get("currency_raw"),
                     r.get("extra_json"), r.get("amount_debit_raw"),
                     r.get("amount_credit_raw")],
                )

            # 9. transactions_norm — full replace (not upsert) for v2
            conn.execute("DELETE FROM transactions_norm")
            tx_count = 0
            for r in data.get("transactions_norm", []):
                conn.execute(
                    """INSERT INTO transactions_norm (
                         transaction_date, posted_date, description, merchant,
                         category, amount, currency, bank_name, account_name,
                         account_id, source_file, source_row, file_hash,
                         transaction_fingerprint, ingested_at, statement_type,
                         run_id, transaction_subtype, resolved_amount,
                         category_normalized, category_parent, unreviewed
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [
                        r.get("transaction_date"), r.get("posted_date"),
                        r.get("description", ""), r.get("merchant"),
                        r.get("category"), r.get("amount", 0),
                        r.get("currency", "USD"), r.get("bank_name", ""),
                        r.get("account_name", ""), r.get("account_id", ""),
                        r.get("source_file", ""), r.get("source_row", 0),
                        r.get("file_hash", ""), r.get("transaction_fingerprint", ""),
                        r.get("ingested_at", now), r.get("statement_type"),
                        r.get("run_id"), r.get("transaction_subtype"),
                        r.get("resolved_amount"), r.get("category_normalized"),
                        r.get("category_parent"), r.get("unreviewed", True),
                    ],
                )
                tx_count += 1

            # 10. tags
            conn.execute("DELETE FROM tags")
            for r in data.get("tags", []):
                conn.execute(
                    """INSERT INTO tags (name, color, created_at, updated_at)
                       VALUES (?,?,?,?)""",
                    [r["name"], r.get("color", "#3b82f6"),
                     r.get("created_at", now), r.get("updated_at", now)],
                )

            # 11. transaction_tags
            conn.execute("DELETE FROM transaction_tags")
            for r in data.get("transaction_tags", []):
                conn.execute(
                    """INSERT INTO transaction_tags
                       (transaction_fingerprint, tag_id, created_at)
                       VALUES (?,?,?)""",
                    [r["transaction_fingerprint"], r["tag_id"],
                     r.get("created_at", now)],
                )

            # 12. savings_goals
            conn.execute("DELETE FROM savings_goals")
            for r in data.get("savings_goals", []):
                conn.execute(
                    """INSERT INTO savings_goals
                       (name, target_amount, current_amount, target_date,
                        linked_account, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    [r["name"], r.get("target_amount", 0),
                     r.get("current_amount", 0),
                     r.get("target_date"), r.get("linked_account"),
                     r.get("created_at", now), r.get("updated_at", now)],
                )

            # 13. monthly_summaries
            conn.execute("DELETE FROM monthly_summaries")
            for r in data.get("monthly_summaries", []):
                conn.execute(
                    """INSERT INTO monthly_summaries
                       (year, month, summary_json, narrative, created_at)
                       VALUES (?,?,?,?,?)""",
                    [r["year"], r["month"], r.get("summary_json", "{}"),
                     r.get("narrative", ""), r.get("created_at", now)],
                )

            conn.close()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Restore failed: {exc}") from exc

        # ── Restore YAML wizard profiles ─────────────────────────────────
        profiles_restored = 0
        wp = payload.get("wizard_profiles", {})
        if wp:
            profiles_path = Path(wizard_profiles_dir)
            profiles_path.mkdir(parents=True, exist_ok=True)
            for rel_path, content in wp.items():
                dest = profiles_path / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
                profiles_restored += 1

        return {
            "status": "ok",
            "backup_version_received": version,
            "runs_restored": len(data.get("runs", [])),
            "merchant_rules_restored": len(data.get("merchant_rules", [])),
            "merchant_categories_restored": len(
                data.get("merchant_category_map", data.get("merchant_categories", []))
            ),
            "category_rules_restored": len(data.get("category_rules", [])),
            "budget_goals_restored": len(data.get("budget_goals", [])),
            "recurring_overrides_restored": len(data.get("recurring_overrides", [])),
            "normalization_jobs_restored": len(data.get("normalization_jobs", [])),
            "transactions_stage_restored": len(data.get("transactions_stage", [])),
            "transactions_norm_restored": tx_count,
            "tags_restored": len(data.get("tags", [])),
            "transaction_tags_restored": len(data.get("transaction_tags", [])),
            "savings_goals_restored": len(data.get("savings_goals", [])),
            "monthly_summaries_restored": len(data.get("monthly_summaries", [])),
            "wizard_profiles_restored": profiles_restored,
        }

    @app.get("/backup/status", tags=["backup"], summary="Backup system status")
    def backup_status():
        """
        Return backup system metadata: last export timestamp, auto-backup
        file list, and current row counts for all backed-up tables.
        """
        from finance_etl.db import get_connection as _gc

        # Auto-backup files
        auto_dir = Path("data/auto_backups")
        auto_backups: list[dict[str, Any]] = []
        if auto_dir.exists():
            for f in sorted(auto_dir.glob("auto_backup_*.json"), key=lambda p: p.name, reverse=True):
                auto_backups.append({
                    "filename": f.name,
                    "size_bytes": f.stat().st_size,
                    "modified_at": _dt_from_stat(f),
                })

        # DB table counts
        db_table_counts: dict[str, int] = {}
        try:
            conn = _gc(db_path, read_only=True)
            for table in _BACKUP_TABLES:
                row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                db_table_counts[table] = row[0] if row else 0
            conn.close()
        except Exception:
            pass

        # Last export: check most recent auto-backup timestamp
        last_export_at = auto_backups[0]["modified_at"] if auto_backups else None

        return {
            "last_export_at": last_export_at,
            "auto_backups": auto_backups,
            "db_table_counts": db_table_counts,
        }

    def _dt_from_stat(path: Path) -> str:
        """ISO timestamp from file mtime."""
        import datetime as _dt
        return _dt.datetime.utcfromtimestamp(path.stat().st_mtime).isoformat() + "Z"

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
        return HTMLResponse(content="<h1>Spendly API</h1><p>UI not installed.</p>")

    return app
