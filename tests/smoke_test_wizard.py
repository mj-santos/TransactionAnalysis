#!/usr/bin/env python3
"""
Smoke test for the mapping wizard API end-to-end flow.

Tests:
  1. Server health check (GET /)
  2. Upload CSV with nonstandard headers → response includes headers + suggestions
  3. POST /wizard/detect → returns matched_profile=null and canonical field list
  4. POST /wizard/validate → validates correct mapping and rejects incomplete mapping
  5. POST /wizard/save-and-run → saves profile YAML, starts pipeline run
  6. Poll run until success or staged
  7. Second upload of same file → matched_profile is now non-null (auto-detected)
  8. GET /wizard/profiles → lists saved profile

Usage:
    python tests/smoke_test_wizard.py [BASE_URL]

Default BASE_URL: http://127.0.0.1:8000

Docker:
    docker --context desktop-linux compose up -d
    python tests/smoke_test_wizard.py http://localhost:8000
"""
import sys
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"
FIXTURES = Path(__file__).parent / "fixtures"
CSV_NONSTANDARD = FIXTURES / "nonstandard_headers.csv"


def _req(method: str, path: str, body=None, *, content_type="application/json"):
    url = f"{BASE_URL}{path}"
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw)
            except Exception:
                return resp.status, {"_raw": raw[:200].decode(errors="replace")}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            body = json.loads(raw)
        except Exception:
            body = {"raw": e.reason, "_body": raw[:200].decode(errors="replace")}
        return e.code, body


def _upload(csv_path: Path) -> tuple[int, dict]:
    import io, email.mime.multipart, email.mime.base
    # Build multipart manually using urllib
    boundary = "----WizardSmokeBoundary7a1b"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{csv_path.name}"\r\n'
        f"Content-Type: text/csv\r\n\r\n"
    ).encode() + csv_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{BASE_URL}/upload",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def ok(test_name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ✅  {test_name}")
    else:
        print(f"  ❌  {test_name}" + (f": {detail}" if detail else ""))
        sys.exit(1)


def section(title: str) -> None:
    print(f"\n── {title} ──────────────────────────────────────────")


def main():
    print(f"\nWizard smoke test → {BASE_URL}\n")

    # 1. Health check
    section("Test 1: Server health")
    status, body = _req("GET", "/")
    ok("GET / returns 200", status == 200, f"got {status}")
    status2, _ = _req("GET", "/openapi.json")
    ok("GET /openapi.json returns 200", status2 == 200, f"got {status2}")

    # 2. Upload nonstandard CSV
    section("Test 2: Upload CSV with nonstandard headers")
    status, upload = _upload(CSV_NONSTANDARD)
    ok("POST /upload returns 200", status == 200, json.dumps(upload)[:200])
    ok("response includes 'headers'", bool(upload.get("headers")), str(upload.get("headers")))
    ok("detected Posting Date header",
       "Posting Date" in upload.get("headers", []),
       str(upload.get("headers")))
    ok("suggestions dict present", isinstance(upload.get("suggestions"), dict),
       str(type(upload.get("suggestions"))))
    ok("no false matched_profile on first upload",
       upload.get("matched_profile") is None,
       str(upload.get("matched_profile")))

    file_path = upload["path"]
    print(f"    path: {file_path}")

    # 3. Wizard detect
    section("Test 3: POST /wizard/detect")
    status, det = _req("POST", "/wizard/detect", {"file_path": file_path})
    ok("returns 200", status == 200, json.dumps(det)[:200])
    ok("canonical_fields list present", bool(det.get("canonical_fields")),
       str(det.get("canonical_fields")))
    ok("transaction_date in canonical_fields",
       "transaction_date" in det.get("canonical_fields", []))
    ok("canonical_labels present", bool(det.get("canonical_labels")))
    ok("suggestions present", isinstance(det.get("suggestions"), dict))

    # 4. Wizard validate — correct mapping
    section("Test 4a: POST /wizard/validate — valid debit/credit mapping")
    good_map = {
        "transaction_date": "Posting Date",
        "debit_amount":     "Withdrawals",
        "credit_amount":    "Deposits",
        "description":      "Narrative",
    }
    status, val = _req("POST", "/wizard/validate", {"canonical_map": good_map})
    ok("valid mapping returns 200", status == 200, json.dumps(val))
    ok("ok is True", val.get("ok") is True)

    section("Test 4b: POST /wizard/validate — invalid (missing date + amount)")
    status, val2 = _req("POST", "/wizard/validate", {"canonical_map": {}})
    ok("invalid mapping returns 422", status == 422, f"got {status}")
    errors = (val2.get("detail") or {}).get("errors", [])
    ok("errors list contains transaction_date issue",
       any("transaction_date" in e for e in errors), str(errors))

    section("Test 4c: POST /wizard/validate — partial amount (debit only, no credit)")
    status, val3 = _req("POST", "/wizard/validate", {"canonical_map": {
        "transaction_date": "Posting Date",
        "debit_amount":     "Withdrawals",  # missing credit_amount
    }})
    ok("partial amount returns 422", status == 422, f"got {status}")

    # 5. Wizard save-and-run
    section("Test 5: POST /wizard/save-and-run")
    status, sar = _req("POST", "/wizard/save-and-run", {
        "file_paths":       [file_path],
        "canonical_map":    good_map,
        "institution":      "testbank_smoke",
        "account_id":       "chk_smoke001",
        "account_name":     "Smoke Checking",
        "bank_name":        "Smoke Test Bank",
        "profile_name":     "default",
        "date_format":      "%m/%d/%Y",
        "currency_default": "USD",
        "drop_columns":     ["Balance"],
        "preview_only":     True,
    })
    ok("save-and-run returns 202", status == 202, json.dumps(sar)[:300])
    run_id = sar.get("run_id")
    ok("run_id present", bool(run_id), str(run_id))
    ok("profile_path returned", bool(sar.get("profile_path")), str(sar.get("profile_path")))
    print(f"    run_id: {run_id}")

    # 6. Poll run status
    section("Test 6: Poll run until terminal state")
    terminal_status = None
    for attempt in range(30):
        time.sleep(1)
        status, run = _req("GET", f"/runs/{run_id}")
        if status != 200:
            ok(f"GET /runs/{run_id} HTTP 200", False, f"got {status}")
        run_status = run.get("status", "")
        print(f"    [{attempt+1}] status={run_status}")
        if run_status in ("staged", "success", "failed", "fail"):
            terminal_status = run_status
            break

    ok("run reached terminal state", terminal_status is not None,
       f"timed out after 30s (last status: {run_status})")
    ok("run succeeded or staged (not failed)",
       terminal_status in ("staged", "success"),
       f"terminal_status={terminal_status}; error={run.get('error')}")

    # 7. Second upload — auto-detect
    section("Test 7: Second upload → auto-detected profile")
    status2, upload2 = _upload(CSV_NONSTANDARD)
    ok("second upload returns 200", status2 == 200, json.dumps(upload2)[:200])
    mp = upload2.get("matched_profile")
    ok("matched_profile is now non-null (auto-detected)", mp is not None,
       "no profile auto-detected on second upload")
    if mp:
        ok("matched profile score > 0", (mp.get("score") or 0) > 0, str(mp.get("score")))
        ok("matched institution correct",
           mp.get("institution") == "testbank_smoke",
           str(mp.get("institution")))

    # 8. List profiles
    section("Test 8: GET /wizard/profiles")
    status, profiles_resp = _req("GET", "/wizard/profiles")
    ok("returns 200", status == 200, f"got {status}")
    profiles = profiles_resp.get("profiles", [])
    ok("at least one profile listed", len(profiles) >= 1, str(profiles))
    ok("smoke profile is listed",
       any(p.get("institution") == "testbank_smoke" for p in profiles),
       str(profiles))

    # 9. No regression: existing POST /runs still works with mapping_path
    section("Test 9: Regression — POST /runs with mapping_path still works")
    status, upload3 = _upload(CSV_NONSTANDARD)
    ok("third upload returns 200", status == 200)
    status, mappings_resp = _req("GET", "/mappings")
    ok("GET /mappings returns 200", status == 200)
    if mappings_resp.get("mappings"):
        m = mappings_resp["mappings"][0]
        status, run_resp = _req("POST", "/runs", {
            "inputs":       [upload3["path"]],
            "mapping_path": m["path"],
            "preview_only": True,
        })
        ok(f"POST /runs with mapping_path={m['path']} returns 202",
           status == 202, json.dumps(run_resp)[:200])

    print("\n══════════════════════════════════════════════════")
    print("  All smoke tests passed ✅")
    print("══════════════════════════════════════════════════\n")


if __name__ == "__main__":
    main()
