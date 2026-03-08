"""
Category normalization rules engine.

Maps raw bank category strings → (normalized_category, parent_group) pairs.

Two sources of rules (checked in order):
  1. DB table category_rules  — user-editable
  2. BUILT_IN_CATEGORY_MAP    — bundled defaults

Matching is exact-string (case-sensitive, as bank data varies).
"""
from __future__ import annotations

from datetime import datetime, timezone

from finance_etl.utils.log import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Built-in category map
# ---------------------------------------------------------------------------

BUILT_IN_CATEGORY_MAP: dict[str, tuple[str, str]] = {
    # Food & Dining
    "Groceries": ("Groceries", "Food & Dining"),
    "Supermarkets": ("Groceries", "Food & Dining"),
    "Merchandise & Supplies-Groceries": ("Groceries", "Food & Dining"),
    "Restaurant-Restaurant": ("Restaurants", "Food & Dining"),
    "Restaurants & Dining": ("Restaurants", "Food & Dining"),
    "Restaurant": ("Restaurants", "Food & Dining"),
    "Dining": ("Restaurants", "Food & Dining"),
    "Fast Food": ("Fast Food", "Food & Dining"),
    "Restaurant-Bar & Café": ("Bars & Cafes", "Food & Dining"),
    "Bar/Cafe": ("Bars & Cafes", "Food & Dining"),
    "Coffee Shops": ("Coffee Shops", "Food & Dining"),
    # Shopping
    "Shopping & Retail": ("General Retail", "Shopping"),
    "Merchandise": ("General Retail", "Shopping"),
    "Merchandise & Supplies-General Retail": ("General Retail", "Shopping"),
    "Merchandise & Supplies-Department Stores": ("Department Stores", "Shopping"),
    "Merchandise & Supplies-Clothing Stores": ("Clothing", "Shopping"),
    "Merchandise & Supplies-Wholesale Stores": ("Wholesale Clubs", "Shopping"),
    "Merchandise & Supplies-Internet Purchase": ("Online Retail", "Shopping"),
    "Merchandise & Supplies-Mail Order": ("Online Retail", "Shopping"),
    "Merchandise & Supplies-Sporting Goods Stores": ("Sporting Goods", "Shopping"),
    "Merchandise & Supplies-Book Stores": ("Books & Hobbies", "Shopping"),
    "Merchandise & Supplies-Arts & Jewelry": ("Arts & Jewelry", "Shopping"),
    "Merchandise & Supplies-Music & Video": ("Electronics & Media", "Shopping"),
    "Merchandise & Supplies-Hardware Supplies": ("Hardware & Home Improvement", "Shopping"),
    "Merchandise & Supplies-Florists & Garden": ("Home & Garden", "Shopping"),
    "Merchandise & Supplies-Furnishing": ("Home Furnishings", "Shopping"),
    "Merchandise & Supplies-Pharmacies": ("Pharmacy", "Shopping"),
    # Travel
    "Travel-Airline": ("Airlines", "Travel"),
    "Travel Airline": ("Airlines", "Travel"),
    "Travel-Lodging": ("Hotels & Lodging", "Travel"),
    "Travel & Lodging": ("Hotels & Lodging", "Travel"),
    "Hotel": ("Hotels & Lodging", "Travel"),
    "Travel-Vehicle Rental": ("Rental Cars", "Travel"),
    "Rental Car": ("Rental Cars", "Travel"),
    "Other Travel": ("Other Travel", "Travel"),
    # Transportation
    "Transportation-Fuel": ("Gas & Fuel", "Transportation"),
    "Gas/Automotive": ("Gas & Fuel", "Transportation"),
    "Gas Stations": ("Gas & Fuel", "Transportation"),
    "Transportation-Parking Charges": ("Parking & Tolls", "Transportation"),
    "Transportation-Tolls & Fees": ("Parking & Tolls", "Transportation"),
    "Parking": ("Parking & Tolls", "Transportation"),
    "Transportation-Taxis & Coach": ("Rideshare & Taxis", "Transportation"),
    "Rideshare": ("Rideshare & Taxis", "Transportation"),
    "Transportation-Rail Services": ("Rail & Transit", "Transportation"),
    "Transportation-Auto Services": ("Auto Services", "Transportation"),
    "Transportation-Vehicle Leasing & Purchase": ("Auto Purchase & Lease", "Transportation"),
    # Entertainment
    "STREAMING SERVICES": ("Streaming", "Entertainment"),
    "Streaming Services": ("Streaming", "Entertainment"),
    "Movies & Music": ("Movies & Music", "Entertainment"),
    "Sports": ("Sports & Recreation", "Entertainment"),
    # Health & Wellness
    "Health Care": ("Medical", "Health & Wellness"),
    "Health & Fitness": ("Fitness", "Health & Wellness"),
    "Medical": ("Medical", "Health & Wellness"),
    "Pharmacy": ("Pharmacy", "Health & Wellness"),
    # Bills & Utilities
    "Utilities": ("Utilities", "Bills & Utilities"),
    "Internet": ("Internet & Cable", "Bills & Utilities"),
    "Phone": ("Phone", "Bills & Utilities"),
    "Insurance": ("Insurance", "Bills & Utilities"),
    # Financial
    "Payment/Credit": ("Credit Card Payment", "Financial"),
    "Payments and Credits": ("Credit Card Payment", "Financial"),
    "Credit Card Payment": ("Credit Card Payment", "Financial"),
    "Fees & Adjustments-Fees & Adjustments": ("Bank Fees", "Financial"),
    "Fees & Adjustments": ("Bank Fees", "Financial"),
    "Bank Fees": ("Bank Fees", "Financial"),
    "Other-Government Services": ("Government & Taxes", "Financial"),
    # Education
    "Other-Education": ("Education", "Education"),
    "Education": ("Education", "Education"),
    # Gifts & Charity
    "Other-Charities": ("Charitable Giving", "Gifts & Charity"),
    "Charity": ("Charitable Giving", "Gifts & Charity"),
    "Gifts": ("Gifts", "Gifts & Charity"),
    # Other
    "Other-Miscellaneous": ("Miscellaneous", "Other"),
    "Other Services": ("Other Services", "Other"),
    "Other": ("Other", "Other"),
}


# ---------------------------------------------------------------------------
# Load rules from DB
# ---------------------------------------------------------------------------

def load_category_rules(conn) -> dict[str, tuple[str, str]]:
    """Return {raw_category: (category, parent)} from DB category_rules table."""
    rows = conn.execute(
        "SELECT raw_category, category, parent FROM category_rules"
    ).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


# ---------------------------------------------------------------------------
# Resolve a raw category string
# ---------------------------------------------------------------------------

def resolve_category(
    raw_category: str | None,
    rules: dict[str, tuple[str, str]],
) -> tuple[str | None, str | None]:
    """
    Return (normalized_category, parent_group) for a raw_category.

    Lookup order:
      1. DB rules (user-editable, highest priority)
      2. BUILT_IN_CATEGORY_MAP
      3. (None, None) if no match found
    """
    if not raw_category:
        return (None, None)

    # 1. DB rules
    if raw_category in rules:
        return rules[raw_category]

    # 2. Built-in map
    if raw_category in BUILT_IN_CATEGORY_MAP:
        return BUILT_IN_CATEGORY_MAP[raw_category]

    return (None, None)


# ---------------------------------------------------------------------------
# Batch apply category normalization
# ---------------------------------------------------------------------------

def apply_category_rules(db_path: str, job_id: str, batch_size: int = 500) -> None:
    """
    Background job: update category_normalized and category_parent on all
    transactions_norm rows.

    Uses normalization_jobs table (same table as merchant normalize jobs) to
    track progress. job_id must already exist in normalization_jobs.
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

        rules = load_category_rules(conn)

        # Fetch all distinct (fingerprint, category) pairs
        all_rows = conn.execute(
            "SELECT transaction_fingerprint, category FROM transactions_norm"
        ).fetchall()

        total = len(all_rows)
        conn.execute(
            "UPDATE normalization_jobs SET rows_total=? WHERE job_id=?",
            [total, job_id],
        )
        log.info("[CATNorm] job=%s total=%d rows", job_id, total)

        done = 0
        batch_updates: list[tuple] = []

        for fp, raw_category in all_rows:
            cat_normalized, cat_parent = resolve_category(raw_category, rules)
            batch_updates.append((cat_normalized, cat_parent, fp))
            done += 1

            if len(batch_updates) >= batch_size:
                _flush_category_batch(conn, batch_updates, job_id, done)
                batch_updates = []

        # Flush remainder
        if batch_updates:
            _flush_category_batch(conn, batch_updates, job_id, done)

        finished = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE normalization_jobs SET status='success', rows_done=?, finished_at=? "
            "WHERE job_id=?",
            [done, finished, job_id],
        )
        log.info("[CATNorm] job=%s done. %d rows updated.", job_id, done)

    except Exception as exc:
        log.exception("[CATNorm] job=%s failed: %s", job_id, exc)
        try:
            conn.execute(
                "UPDATE normalization_jobs SET status='failed', error=?, finished_at=? "
                "WHERE job_id=?",
                [str(exc), datetime.now(timezone.utc).isoformat(), job_id],
            )
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _flush_category_batch(conn, updates: list[tuple], job_id: str, done: int) -> None:
    """Execute a batch UPDATE and commit progress."""
    for cat_normalized, cat_parent, fp in updates:
        conn.execute(
            "UPDATE transactions_norm SET category_normalized=?, category_parent=? "
            "WHERE transaction_fingerprint=?",
            [cat_normalized, cat_parent, fp],
        )
    conn.execute(
        "UPDATE normalization_jobs SET rows_done=? WHERE job_id=?",
        [done, job_id],
    )
    log.debug("[CATNorm] Flushed batch. rows_done=%d", done)
