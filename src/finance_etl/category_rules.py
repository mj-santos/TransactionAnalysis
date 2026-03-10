"""
Category normalization engine.

Maps raw bank-provided category strings to a normalized two-tier taxonomy:
  category  — normalized subcategory (e.g. "Hotels & Lodging")
  parent    — top-level group       (e.g. "Travel")

Two sources of mappings (in priority order):
  1. user-defined rules in the `category_rules` DB table (exact match, case-insensitive)
  2. built-in fallback map (BUILT_IN_CATEGORY_MAP)

apply_category_rules() walks all transactions_norm rows and writes
category_normalized + category_parent, tracking progress in normalization_jobs.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from finance_etl.utils.log import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Built-in taxonomy — maps raw bank category → (normalized_category, parent)
# ---------------------------------------------------------------------------

BUILT_IN_CATEGORY_MAP: dict[str, tuple[str, str]] = {
    # ── Food & Dining ────────────────────────────────────────────────────────
    "Groceries":                                    ("Groceries",             "Food & Dining"),
    "Supermarkets":                                 ("Groceries",             "Food & Dining"),
    "Merchandise & Supplies-Groceries":             ("Groceries",             "Food & Dining"),
    "Restaurant-Restaurant":                        ("Restaurants",           "Food & Dining"),
    "Restaurants & Dining":                         ("Restaurants",           "Food & Dining"),
    "Restaurant":                                   ("Restaurants",           "Food & Dining"),
    "Dining":                                       ("Restaurants",           "Food & Dining"),
    "Fast Food":                                    ("Fast Food",             "Food & Dining"),
    "Restaurant-Bar & Café":                        ("Bars & Cafes",          "Food & Dining"),
    "Bar/Cafe":                                     ("Bars & Cafes",          "Food & Dining"),
    "Coffee Shops":                                 ("Coffee Shops",          "Food & Dining"),
    "Food & Drink":                                 ("Restaurants",           "Food & Dining"),
    # ── Shopping ─────────────────────────────────────────────────────────────
    "Shopping & Retail":                            ("General Retail",        "Shopping"),
    "Merchandise":                                  ("General Retail",        "Shopping"),
    "Merchandise & Supplies-General Retail":        ("General Retail",        "Shopping"),
    "Merchandise & Supplies-Department Stores":     ("Department Stores",     "Shopping"),
    "Merchandise & Supplies-Clothing Stores":       ("Clothing",              "Shopping"),
    "Merchandise & Supplies-Wholesale Stores":      ("Wholesale Clubs",       "Shopping"),
    "Merchandise & Supplies-Internet Purchase":     ("Online Retail",         "Shopping"),
    "Merchandise & Supplies-Mail Order":            ("Online Retail",         "Shopping"),
    "Merchandise & Supplies-Sporting Goods Stores": ("Sporting Goods",        "Shopping"),
    "Merchandise & Supplies-Book Stores":           ("Books & Hobbies",       "Shopping"),
    "Merchandise & Supplies-Arts & Jewelry":        ("Arts & Jewelry",        "Shopping"),
    "Merchandise & Supplies-Music & Video":         ("Electronics & Media",   "Shopping"),
    "Merchandise & Supplies-Hardware Supplies":     ("Hardware & Home Improvement", "Shopping"),
    "Merchandise & Supplies-Florists & Garden":     ("Home & Garden",         "Shopping"),
    "Merchandise & Supplies-Furnishing":            ("Home Furnishings",      "Shopping"),
    "Merchandise & Supplies-Pharmacies":            ("Pharmacy",              "Shopping"),
    "Electronics":                                  ("Electronics & Media",   "Shopping"),
    "Clothing":                                     ("Clothing",              "Shopping"),
    "Online Shopping":                              ("Online Retail",         "Shopping"),
    # ── Travel ───────────────────────────────────────────────────────────────
    "Travel-Airline":                               ("Airlines",              "Travel"),
    "Travel Airline":                               ("Airlines",              "Travel"),
    "Travel-Lodging":                               ("Hotels & Lodging",      "Travel"),
    "Travel & Lodging":                             ("Hotels & Lodging",      "Travel"),
    "Hotel":                                        ("Hotels & Lodging",      "Travel"),
    "Hotels":                                       ("Hotels & Lodging",      "Travel"),
    "Travel-Vehicle Rental":                        ("Rental Cars",           "Travel"),
    "Rental Car":                                   ("Rental Cars",           "Travel"),
    "Other Travel":                                 ("Other Travel",          "Travel"),
    "Travel":                                       ("Other Travel",          "Travel"),
    # ── Transportation ───────────────────────────────────────────────────────
    "Transportation-Fuel":                          ("Gas & Fuel",            "Transportation"),
    "Gas/Automotive":                               ("Gas & Fuel",            "Transportation"),
    "Gas Stations":                                 ("Gas & Fuel",            "Transportation"),
    "Transportation-Parking Charges":               ("Parking & Tolls",       "Transportation"),
    "Transportation-Tolls & Fees":                  ("Parking & Tolls",       "Transportation"),
    "Parking":                                      ("Parking & Tolls",       "Transportation"),
    "Transportation-Taxis & Coach":                 ("Rideshare & Taxis",     "Transportation"),
    "Rideshare":                                    ("Rideshare & Taxis",     "Transportation"),
    "Transportation-Rail Services":                 ("Rail & Transit",        "Transportation"),
    "Transportation-Auto Services":                 ("Auto Services",         "Transportation"),
    "Transportation-Vehicle Leasing & Purchase":    ("Auto Purchase & Lease", "Transportation"),
    "Auto & Transport":                             ("Auto Services",         "Transportation"),
    # ── Entertainment ────────────────────────────────────────────────────────
    "STREAMING SERVICES":                           ("Streaming",             "Entertainment"),
    "Streaming Services":                           ("Streaming",             "Entertainment"),
    "Movies & Music":                               ("Movies & Music",        "Entertainment"),
    "Sports":                                       ("Sports & Recreation",   "Entertainment"),
    "Recreation":                                   ("Sports & Recreation",   "Entertainment"),
    "Entertainment":                                ("Entertainment",         "Entertainment"),
    "Arts & Entertainment":                         ("Entertainment",         "Entertainment"),
    # ── Health & Wellness ────────────────────────────────────────────────────
    "Health Care":                                  ("Medical",               "Health & Wellness"),
    "Health & Fitness":                             ("Fitness",               "Health & Wellness"),
    "Medical":                                      ("Medical",               "Health & Wellness"),
    "Pharmacy":                                     ("Pharmacy",              "Health & Wellness"),
    "Doctor":                                       ("Medical",               "Health & Wellness"),
    "Dentist":                                      ("Medical",               "Health & Wellness"),
    # ── Bills & Utilities ────────────────────────────────────────────────────
    "Utilities":                                    ("Utilities",             "Bills & Utilities"),
    "Internet":                                     ("Internet & Cable",      "Bills & Utilities"),
    "Phone":                                        ("Phone",                 "Bills & Utilities"),
    "Insurance":                                    ("Insurance",             "Bills & Utilities"),
    "Cable/Satellite":                              ("Internet & Cable",      "Bills & Utilities"),
    "Water":                                        ("Utilities",             "Bills & Utilities"),
    "Electric":                                     ("Utilities",             "Bills & Utilities"),
    # ── Financial ────────────────────────────────────────────────────────────
    "Payment/Credit":                               ("Credit Card Payment",   "Financial"),
    "Payments and Credits":                         ("Credit Card Payment",   "Financial"),
    "Credit Card Payment":                          ("Credit Card Payment",   "Financial"),
    "Fees & Adjustments-Fees & Adjustments":        ("Bank Fees",             "Financial"),
    "Fees & Adjustments":                           ("Bank Fees",             "Financial"),
    "Bank Fees":                                    ("Bank Fees",             "Financial"),
    "ATM Fee":                                      ("Bank Fees",             "Financial"),
    "Other-Government Services":                    ("Government & Taxes",    "Financial"),
    "Taxes":                                        ("Government & Taxes",    "Financial"),
    "Financial":                                    ("Other Financial",       "Financial"),
    # ── Education ────────────────────────────────────────────────────────────
    "Other-Education":                              ("Education",             "Education"),
    "Education":                                    ("Education",             "Education"),
    "Tuition":                                      ("Education",             "Education"),
    # ── Home ─────────────────────────────────────────────────────────────────
    "Home":                                         ("Home",                  "Home"),
    "Mortgage":                                     ("Mortgage & Rent",       "Home"),
    "Rent":                                         ("Mortgage & Rent",       "Home"),
    "Home Improvement":                             ("Hardware & Home Improvement", "Home"),
    # ── Gifts & Charity ──────────────────────────────────────────────────────
    "Other-Charities":                              ("Charitable Giving",     "Gifts & Charity"),
    "Charity":                                      ("Charitable Giving",     "Gifts & Charity"),
    "Gifts":                                        ("Gifts",                 "Gifts & Charity"),
    "Charitable Giving":                            ("Charitable Giving",     "Gifts & Charity"),
    # ── Other ────────────────────────────────────────────────────────────────
    "Other-Miscellaneous":                          ("Miscellaneous",         "Other"),
    "Other Services":                               ("Other Services",        "Other"),
    "Other":                                        ("Other",                 "Other"),
}

# Lowercase lookup for case-insensitive matching
_BUILT_IN_LOWER: dict[str, tuple[str, str]] = {
    k.lower(): v for k, v in BUILT_IN_CATEGORY_MAP.items()
}


# ---------------------------------------------------------------------------
# Normalize a single raw category
# ---------------------------------------------------------------------------

def normalize_category(raw: str | None,
                        user_rules: dict[str, tuple[str, str]]) -> tuple[str | None, str | None]:
    """
    Return (category_normalized, category_parent) for a raw bank category string.
    user_rules takes priority over the built-in map.
    Returns (None, None) if raw is None/empty.
    """
    if not raw:
        return None, None
    key = raw.lower()
    if key in user_rules:
        return user_rules[key]
    if key in _BUILT_IN_LOWER:
        return _BUILT_IN_LOWER[key]
    return raw, "Other"   # fallback: keep original, assign Other parent


# ---------------------------------------------------------------------------
# Load user rules from DB → {lower(raw_category): (category, parent)}
# ---------------------------------------------------------------------------

def load_category_rules(conn) -> dict[str, tuple[str, str]]:
    """Return user-defined category rules as {lower(raw_category): (category, parent)}."""
    try:
        rows = conn.execute(
            "SELECT raw_category, category, parent FROM category_rules"
        ).fetchall()
    except Exception:
        return {}
    return {r[0].lower(): (r[1], r[2]) for r in rows}


# ---------------------------------------------------------------------------
# Apply job — backfill category_normalized + category_parent
# ---------------------------------------------------------------------------

def create_category_job(conn) -> str:
    """Create a normalization_jobs entry for category apply; return job_id."""
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    total = conn.execute("SELECT COUNT(*) FROM transactions_norm").fetchone()[0]
    conn.execute(
        "INSERT INTO normalization_jobs (job_id, status, rows_total, rows_done, created_at) "
        "VALUES (?, 'pending', ?, 0, ?)",
        [job_id, total, now],
    )
    return job_id


def apply_category_rules(db_path: str, job_id: str) -> None:
    """
    Background job: iterate all transactions_norm rows, normalize category,
    write back category_normalized + category_parent.
    Updates normalization_jobs for progress tracking.
    """
    import duckdb

    conn = duckdb.connect(db_path)
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "UPDATE normalization_jobs SET status='running', started_at=? WHERE job_id=?",
            [now, job_id],
        )
        user_rules = load_category_rules(conn)
        rows = conn.execute(
            "SELECT transaction_fingerprint, category FROM transactions_norm"
        ).fetchall()
        total = len(rows)
        done = 0
        BATCH = 500
        updates: list[tuple[str | None, str | None, str]] = []

        for fingerprint, raw_cat in rows:
            cat_n, cat_p = normalize_category(raw_cat, user_rules)
            updates.append((cat_n, cat_p, fingerprint))
            done += 1
            if len(updates) >= BATCH:
                conn.executemany(
                    "UPDATE transactions_norm "
                    "SET category_normalized=?, category_parent=? "
                    "WHERE transaction_fingerprint=?",
                    updates,
                )
                conn.execute(
                    "UPDATE normalization_jobs SET rows_done=? WHERE job_id=?",
                    [done, job_id],
                )
                updates = []

        if updates:
            conn.executemany(
                "UPDATE transactions_norm "
                "SET category_normalized=?, category_parent=? "
                "WHERE transaction_fingerprint=?",
                updates,
            )

        finished = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE normalization_jobs "
            "SET status='success', rows_done=?, finished_at=? WHERE job_id=?",
            [total, finished, job_id],
        )
        log.info("Category normalization complete: %d rows", total)
    except Exception as exc:
        log.exception("Category normalization job failed")
        conn.execute(
            "UPDATE normalization_jobs SET status='failed', error=? WHERE job_id=?",
            [str(exc), job_id],
        )
    finally:
        conn.close()
