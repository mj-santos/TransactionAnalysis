"""FastAPI service — uploads, async runs, preview/commit, reports, and web UI."""
from __future__ import annotations

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
# Pydantic models — these power the /docs schema and enforce types at runtime
# ---------------------------------------------------------------------------
try:
    from pydantic import BaseModel, Field

    class UploadResponse(BaseModel):
        filename: str = Field(..., description="Original filename as uploaded")
        path: str     = Field(..., description="Server-side path to pass as input to POST /runs")
        size: int     = Field(..., description="File size in bytes")

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
                        "Provide this OR bank_key, not both.",
        )
        bank_key: Optional[str] = Field(
            None,
            description="Bank key (YAML stem) to auto-locate a mapping. "
                        "Alternative to mapping_path.",
        )
        preview_only: bool = Field(
            False,
            description="When true the pipeline stops after validation — data is staged "
                        "but NOT written to the ledger. Call POST /runs/{run_id}/commit "
                        "to finalise, or simply discard.",
        )

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


def create_app(
    db_path:      str = "data/db/finance.duckdb",
    mappings_dir: str = "config/mappings",
    reports_dir:  str = "data/reports",
    upload_dir:   str = "data/uploads",
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

    def _run_bg(run_id: str, inputs: list, mapping_path, bank_key, preview_only: bool):
        _async_runs[run_id] = {"status": "running", "run_id": run_id}
        try:
            result = run_with_options(
                inputs=inputs,
                db_path=db_path,
                mappings_dir=mappings_dir,
                mapping_path=mapping_path,
                bank_key=bank_key,
                reports_dir=reports_dir,
                preview_only=preview_only,
                run_id=run_id,
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
            return {"filename": safe_original, "path": str(dest), "size": len(content)}
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
        if not payload.mapping_path and not payload.bank_key:
            raise HTTPException(status_code=400, detail="Provide mapping_path or bank_key.")

        run_id = uuid.uuid4().hex[:16]
        _async_runs[run_id] = {"status": "pending", "run_id": run_id}

        background_tasks.add_task(
            _run_bg,
            run_id,
            payload.inputs,
            payload.mapping_path,
            payload.bank_key,
            payload.preview_only,
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
                       amount_raw, currency_raw
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
            "amount_raw", "currency_raw",
        ]
        return {
            "run_id":    run_id,
            "rows":      [dict(zip(cols, r)) for r in rows],
            "count":     len(rows),
            "truncated": len(rows) == limit,
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
    def read_logs(limit: int = Query(120, description="Maximum log lines to return")):
        file_name, lines = _tail_latest_log_lines(limit)
        return {"file": file_name, "lines": lines}

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

    @app.get(
        "/charts/{name}",
        tags=["reports"],
        summary="Get a report as JSON rows",
        response_model=ChartResponse if _PYDANTIC_OK else None,
    )
    def chart_json(name: str):
        """
        Return the contents of a report CSV as a JSON array of row objects.

        Useful for building charts or tables in a frontend without parsing CSV.
        Keys are taken from the CSV header row.
        """
        path = Path(reports_dir) / name
        if path.suffix.lower() != ".csv" or not path.exists():
            raise HTTPException(status_code=404, detail=f"Report '{name}' not found. Run an import first.")
        return {"name": path.name, "rows": chart_from_report_csv(path)}

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
