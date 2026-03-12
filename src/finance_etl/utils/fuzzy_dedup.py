"""Post-import fuzzy duplicate detection.

After every import commit, this module runs a fuzzy pass to detect probable
duplicate transactions that differ in description text, amount, or both.
Results are inserted into ``duplicate_candidates`` for user review — the
app never auto-deletes.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from rapidfuzz import fuzz

if TYPE_CHECKING:
    import duckdb


def fuzzy_duplicate_detection(
    conn: "duckdb.DuckDBPyConnection",
    new_fingerprints: list[str],
    date_window_days: int = 3,
    amount_tolerance: float = 0.50,
    description_threshold: float = 0.75,
) -> int:
    """Detect fuzzy duplicate candidates among newly imported transactions.

    For each newly imported transaction, search for existing transactions that
    match on account, are close in date/amount, and have similar descriptions
    but *different* fingerprints.  Matches are inserted into
    ``duplicate_candidates`` with status ``'pending'``.

    Parameters
    ----------
    conn:
        Open DuckDB read-write connection.
    new_fingerprints:
        Fingerprints inserted by the current import batch.
    date_window_days:
        Maximum day difference between transaction dates (default 3).
    amount_tolerance:
        Maximum absolute dollar difference between amounts (default $0.50).
    description_threshold:
        Minimum token-sort-ratio similarity for descriptions (default 0.75).

    Returns
    -------
    int
        Number of new duplicate_candidates rows inserted.
    """
    if not new_fingerprints:
        return 0

    # Fetch the newly imported transactions
    placeholders = ", ".join(["?"] * len(new_fingerprints))
    new_txns = conn.execute(
        f"""SELECT transaction_fingerprint, account_id, transaction_date,
                   amount, description, split_parent_fingerprint
            FROM transactions_norm
            WHERE transaction_fingerprint IN ({placeholders})""",
        new_fingerprints,
    ).fetchall()

    if not new_txns:
        return 0

    # Compute date bounds across all new transactions for the pre-filter query
    dates = [row[2] for row in new_txns if row[2] is not None]
    if not dates:
        return 0

    min_date = min(dates) - timedelta(days=date_window_days)
    max_date = max(dates) + timedelta(days=date_window_days)

    now_str = conn.execute("SELECT CAST(CURRENT_TIMESTAMP AS TEXT)").fetchone()[0]

    inserted = 0

    for fp_b, acct_b, date_b, amt_b, desc_b, split_parent_b in new_txns:
        # Skip split children
        if split_parent_b is not None:
            continue
        if date_b is None or amt_b is None or desc_b is None:
            continue

        amt_b_f = float(amt_b)

        # Pre-filter: same account, date window, amount window, not in new batch,
        # not a split child
        candidates = conn.execute(
            """SELECT transaction_fingerprint, transaction_date, amount,
                      description
               FROM transactions_norm
               WHERE account_id = ?
                 AND transaction_date BETWEEN ? AND ?
                 AND ABS(CAST(amount AS DOUBLE) - ?) <= ?
                 AND transaction_fingerprint NOT IN ({fps})
                 AND (split_parent_fingerprint IS NULL)
            """.format(fps=placeholders),
            [
                acct_b,
                str(min_date),
                str(max_date),
                amt_b_f,
                amount_tolerance,
                *new_fingerprints,
            ],
        ).fetchall()

        for fp_a, date_a, amt_a, desc_a in candidates:
            if date_a is None or amt_a is None or desc_a is None:
                continue

            # Date check
            day_diff = abs((date_b - date_a).days)
            if day_diff > date_window_days:
                continue

            # Amount check
            amt_a_f = float(amt_a)
            amt_diff = abs(amt_b_f - amt_a_f)
            if amt_diff > amount_tolerance:
                continue

            # Description similarity (token sort ratio)
            similarity = fuzz.token_sort_ratio(desc_b, desc_a) / 100.0
            if similarity < description_threshold:
                continue

            # Determine reason
            desc_fuzzy = similarity < 1.0
            amt_varies = amt_diff > 0.001

            if desc_fuzzy and amt_varies:
                reason = "fuzzy_description_and_amount_variance"
            elif amt_varies:
                reason = "amount_variance"
            else:
                reason = "fuzzy_description_match"

            # Check if this pair already exists (either direction)
            existing = conn.execute(
                """SELECT 1 FROM duplicate_candidates
                   WHERE (fingerprint_a = ? AND fingerprint_b = ?)
                      OR (fingerprint_a = ? AND fingerprint_b = ?)""",
                [fp_a, fp_b, fp_b, fp_a],
            ).fetchone()
            if existing:
                continue

            conn.execute(
                """INSERT INTO duplicate_candidates
                   (fingerprint_a, fingerprint_b, similarity_score, reason,
                    status, detected_at)
                   VALUES (?, ?, ?, ?, 'pending', ?)""",
                [fp_a, fp_b, round(similarity, 2), reason, now_str],
            )
            inserted += 1

    return inserted
