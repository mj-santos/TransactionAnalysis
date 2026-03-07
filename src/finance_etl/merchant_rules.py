"""
Merchant normalization rules engine.

Two-table architecture:
  merchant_rules      — pattern → merchant name mappings (user-editable)
  merchant_category_map — merchant → category memory (learned + user-assigned)

Matching is always case-insensitive.  Match types:
  contains   — substring match
  startswith — string must start with pattern
  regex      — full regex match (compiled with re.IGNORECASE)

Rules are ordered by priority DESC, id ASC.  First match wins.

Category learning:
  When a transaction has a known category and a rule matched, the pair is
  written to merchant_category_map as source='learned'.  User-assigned
  entries (source='user') are never overwritten.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from finance_etl.utils.log import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# CompiledRule
# ---------------------------------------------------------------------------

@dataclass
class CompiledRule:
    id: int
    pattern: str
    match_type: str          # 'contains' | 'startswith' | 'regex'
    merchant: str
    priority: int
    _regex: re.Pattern | None = None

    def __post_init__(self) -> None:
        if self.match_type == "regex":
            try:
                self._regex = re.compile(self.pattern, re.IGNORECASE)
            except re.error as exc:
                log.warning("Invalid regex in merchant_rule id=%s: %s", self.id, exc)
                self._regex = None

    def matches(self, text: str) -> bool:
        if self.match_type == "contains":
            return self.pattern.lower() in text.lower()
        if self.match_type == "startswith":
            return text.lower().startswith(self.pattern.lower())
        if self.match_type == "regex":
            return bool(self._regex and self._regex.search(text))
        return False


# ---------------------------------------------------------------------------
# Load / apply rules
# ---------------------------------------------------------------------------

def load_rules(conn) -> list[CompiledRule]:
    """Load all merchant rules ordered by priority DESC, id ASC."""
    rows = conn.execute(
        "SELECT id, pattern, match_type, merchant, priority FROM merchant_rules "
        "ORDER BY priority DESC, id ASC"
    ).fetchall()
    rules = []
    for row in rows:
        r = CompiledRule(
            id=row[0],
            pattern=row[1],
            match_type=row[2],
            merchant=row[3],
            priority=row[4],
        )
        rules.append(r)
    return rules


def apply_rules(description: str, rules: list[CompiledRule]) -> str | None:
    """Return the normalized merchant name for description, or None if no match."""
    for rule in rules:
        if rule.matches(description):
            return rule.merchant
    return None


# ---------------------------------------------------------------------------
# Category map
# ---------------------------------------------------------------------------

def load_category_map(conn) -> dict[str, str]:
    """Return {lower(merchant): category} for all entries in merchant_category_map."""
    rows = conn.execute(
        "SELECT merchant, category FROM merchant_category_map"
    ).fetchall()
    return {r[0].lower(): r[1] for r in rows}


def learn_category(conn, merchant: str, category: str) -> None:
    """
    Record a merchant→category association as source='learned'.

    Never overwrites an existing source='user' entry.
    Upserts learned entries: INSERT if absent, UPDATE if existing source='learned'.
    """
    existing = conn.execute(
        "SELECT source FROM merchant_category_map WHERE merchant = ?",
        [merchant],
    ).fetchone()

    now = datetime.now(timezone.utc).isoformat()

    if existing is None:
        conn.execute(
            "INSERT INTO merchant_category_map (merchant, category, source, updated_at) "
            "VALUES (?, ?, 'learned', ?)",
            [merchant, category, now],
        )
    elif existing[0] == "learned":
        # Update if category changed
        conn.execute(
            "UPDATE merchant_category_map SET category = ?, updated_at = ? "
            "WHERE merchant = ? AND source = 'learned'",
            [category, now, merchant],
        )
    # If source='user', leave untouched


def assign_category(conn, merchant: str, category: str) -> None:
    """
    Assign a category to a merchant as source='user' (highest authority).

    Always overwrites regardless of existing source.
    """
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT 1 FROM merchant_category_map WHERE merchant = ?", [merchant]
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO merchant_category_map (merchant, category, source, updated_at) "
            "VALUES (?, ?, 'user', ?)",
            [merchant, category, now],
        )
    else:
        conn.execute(
            "UPDATE merchant_category_map SET category = ?, source = 'user', updated_at = ? "
            "WHERE merchant = ?",
            [category, now, merchant],
        )

    # Backfill category onto historical transactions for this merchant
    conn.execute(
        "UPDATE transactions_norm SET category = ? WHERE merchant = ?",
        [category, merchant],
    )


# ---------------------------------------------------------------------------
# Batch re-normalization
# ---------------------------------------------------------------------------

def create_normalization_job(conn, job_id: str | None = None) -> str:
    """Create a normalization_jobs row and return the job_id."""
    if job_id is None:
        job_id = "norm_" + uuid.uuid4().hex[:16]
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO normalization_jobs (job_id, status, rows_done, created_at) "
        "VALUES (?, 'pending', 0, ?)",
        [job_id, now],
    )
    return job_id


def batch_renormalize(db_path: str, job_id: str, batch_size: int = 500) -> None:
    """
    Re-apply merchant rules to all transactions_norm rows.

    Runs in a background thread.  Progress is tracked in normalization_jobs.
    Uses transaction_fingerprint (UNIQUE) as the update key since DuckDB has
    no implicit rowid.

    Steps per row:
      1. apply_rules(description) → new merchant (or keep existing if no match)
      2. look up category from merchant_category_map (user entries take priority)
      3. update transactions_norm in batches of batch_size
    """
    from finance_etl.db import get_connection

    conn = get_connection(db_path)
    now_str = datetime.now(timezone.utc).isoformat()

    try:
        conn.execute(
            "UPDATE normalization_jobs SET status='running', started_at=?, rows_done=0 "
            "WHERE job_id=?",
            [now_str, job_id],
        )

        rules = load_rules(conn)
        cat_map = load_category_map(conn)

        # Fetch fingerprint + description + existing merchant + existing category
        all_rows = conn.execute(
            "SELECT transaction_fingerprint, description, merchant, category "
            "FROM transactions_norm"
        ).fetchall()

        total = len(all_rows)
        conn.execute(
            "UPDATE normalization_jobs SET rows_total=? WHERE job_id=?",
            [total, job_id],
        )
        log.info("[RENorm] job=%s total=%d rows", job_id, total)

        done = 0
        batch_updates: list[tuple] = []

        for fp, description, existing_merchant, existing_category in all_rows:
            new_merchant = apply_rules(description, rules)
            # If no rule matched, keep existing merchant (may be None)
            merchant = new_merchant if new_merchant is not None else existing_merchant

            # Resolve category: prefer user-assigned, then learned, then existing
            if merchant:
                cat = cat_map.get(merchant.lower())
            else:
                cat = None
            category = cat if cat is not None else existing_category

            batch_updates.append((merchant, category, fp))
            done += 1

            if len(batch_updates) >= batch_size:
                _flush_batch(conn, batch_updates, job_id, done)
                batch_updates = []

        # Flush remainder
        if batch_updates:
            _flush_batch(conn, batch_updates, job_id, done)

        finished = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE normalization_jobs SET status='success', rows_done=?, finished_at=? "
            "WHERE job_id=?",
            [done, finished, job_id],
        )
        log.info("[RENorm] job=%s done. %d rows updated.", job_id, done)

    except Exception as exc:
        log.exception("[RENorm] job=%s failed: %s", job_id, exc)
        try:
            conn.execute(
                "UPDATE normalization_jobs SET status='fail', error=?, finished_at=? "
                "WHERE job_id=?",
                [str(exc), datetime.now(timezone.utc).isoformat(), job_id],
            )
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _flush_batch(conn, updates: list[tuple], job_id: str, done: int) -> None:
    """Execute a batch UPDATE and commit progress."""
    for merchant, category, fp in updates:
        conn.execute(
            "UPDATE transactions_norm SET merchant=?, category=? "
            "WHERE transaction_fingerprint=?",
            [merchant, category, fp],
        )
    conn.execute(
        "UPDATE normalization_jobs SET rows_done=? WHERE job_id=?",
        [done, job_id],
    )
    log.debug("[RENorm] Flushed batch. rows_done=%d", done)
