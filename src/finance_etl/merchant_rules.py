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

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from finance_etl.utils.log import get_logger
from finance_etl.utils.query_helpers import evaluate_rule_groups, _match_single as _shared_match

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
    # Compound condition support — when set, overrides single pattern/match_type
    # Can be a flat list [{pattern, match_type, negate}] (legacy)
    # or a grouped structure {"groups": [{group_logic, conditions: [...]}]}
    conditions: list[dict] | dict | None = None
    logic: str = "AND"                     # 'AND' | 'OR' (legacy flat mode)
    _condition_regexes: dict[int, re.Pattern | None] = field(default_factory=dict)
    # Grouped condition support — parsed from conditions on init
    _groups: list[dict] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        # Detect and normalize grouped vs flat conditions
        if isinstance(self.conditions, dict) and "groups" in self.conditions:
            # New grouped format
            self._groups = self.conditions["groups"]
        elif isinstance(self.conditions, list) and self.conditions:
            # Legacy flat format — wrap in single group
            self._groups = [{"group_logic": self.logic, "conditions": self.conditions}]
        else:
            self._groups = None

        if self._groups:
            # Compile regexes for all conditions across all groups
            idx = 0
            for group in self._groups:
                for cond in group.get("conditions", []):
                    if cond.get("match_type") == "regex":
                        try:
                            self._condition_regexes[idx] = re.compile(cond["pattern"], re.IGNORECASE)
                        except re.error as exc:
                            log.warning("Invalid regex in merchant_rule id=%s condition %d: %s", self.id, idx, exc)
                            self._condition_regexes[idx] = None
                    idx += 1
        elif self.match_type == "regex":
            try:
                self._regex = re.compile(self.pattern, re.IGNORECASE)
            except re.error as exc:
                log.warning("Invalid regex in merchant_rule id=%s: %s", self.id, exc)
                self._regex = None

    def matches(self, text: str) -> bool:
        if self._groups:
            return evaluate_rule_groups(self._groups, text, self._condition_regexes)
        return _shared_match(self.pattern, self.match_type, text, self._regex)


# ---------------------------------------------------------------------------
# Load / apply rules
# ---------------------------------------------------------------------------

def load_rules(conn) -> list[CompiledRule]:
    """Load all merchant rules ordered by priority DESC, id ASC."""
    rows = conn.execute(
        "SELECT id, pattern, match_type, merchant, priority, conditions, logic "
        "FROM merchant_rules ORDER BY priority DESC, id ASC"
    ).fetchall()
    rules = []
    for row in rows:
        conditions_raw = row[5]
        conditions = None
        if conditions_raw:
            try:
                conditions = json.loads(conditions_raw)
            except Exception:
                conditions = None
        r = CompiledRule(
            id=row[0],
            pattern=row[1],
            match_type=row[2],
            merchant=row[3],
            priority=row[4],
            conditions=conditions,
            logic=row[6] or "AND",
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


def assign_category(conn, merchant: str, category: str, parent: str | None = None,
                    source: str = "user") -> None:
    """
    Assign a category to a merchant in merchant_category_map.

    Does NOT touch transactions_norm directly — callers should trigger
    re-normalization via renormalize_merchant() after this call.
    """
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT 1 FROM merchant_category_map WHERE merchant = ?", [merchant]
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO merchant_category_map (merchant, category, source, updated_at) "
            "VALUES (?, ?, ?, ?)",
            [merchant, category, source, now],
        )
    else:
        conn.execute(
            "UPDATE merchant_category_map SET category = ?, source = ?, updated_at = ? "
            "WHERE merchant = ?",
            [category, source, now, merchant],
        )


def renormalize_merchant(db_path_or_conn, merchant: str) -> int:
    """
    Re-normalize all transactions for a single merchant.

    Applies merchant rules + category map to update merchant, category_normalized,
    and category_parent on transactions_norm rows. Respects category_override=TRUE.

    Returns number of transactions updated.
    """
    from finance_etl.db import get_connection as _get_conn

    own_conn = False
    if isinstance(db_path_or_conn, str):
        conn = _get_conn(db_path_or_conn)
        own_conn = True
    else:
        conn = db_path_or_conn

    try:
        cat_map = load_category_map(conn)
        cat_entry = cat_map.get(merchant.lower())

        # Determine category_normalized and category_parent from merchant_category_map
        if cat_entry:
            # cat_map returns the category string; look up parent from DB
            row = conn.execute(
                "SELECT category, source FROM merchant_category_map WHERE LOWER(merchant) = LOWER(?)",
                [merchant],
            ).fetchone()
            if row:
                cat_normalized = row[0]
                # Look up parent from category_rules or built-in map
                parent_row = conn.execute(
                    "SELECT parent FROM category_rules WHERE category = ? LIMIT 1",
                    [cat_normalized],
                ).fetchone()
                if parent_row:
                    cat_parent = parent_row[0]
                else:
                    from finance_etl.category_rules import BUILT_IN_CATEGORY_MAP
                    cat_parent = None
                    for raw, (norm, par) in BUILT_IN_CATEGORY_MAP.items():
                        if norm == cat_normalized:
                            cat_parent = par
                            break
                    if cat_parent is None:
                        # Try merchant_category_map for parent stored alongside
                        cat_parent = "Other"
            else:
                cat_normalized = cat_entry
                cat_parent = "Other"
        else:
            cat_normalized = None
            cat_parent = None

        # Update non-overridden transactions for this merchant
        if cat_normalized is not None:
            conn.execute(
                "UPDATE transactions_norm "
                "SET category_normalized = ?, category_parent = ? "
                "WHERE merchant = ? "
                "AND COALESCE(category_override, FALSE) = FALSE",
                [cat_normalized, cat_parent, merchant],
            )
        else:
            # Category removed — let category rules engine re-assign
            # For now, set to NULL so next full normalization picks them up
            from finance_etl.category_rules import (
                load_category_rules,
                load_grouped_category_rules,
                normalize_category,
            )
            user_rules = load_category_rules(conn)
            grouped_rules = load_grouped_category_rules(conn)
            rows = conn.execute(
                "SELECT transaction_fingerprint, category FROM transactions_norm "
                "WHERE merchant = ? AND COALESCE(category_override, FALSE) = FALSE",
                [merchant],
            ).fetchall()
            for fp, raw_cat in rows:
                cat_n, cat_p = normalize_category(raw_cat, user_rules, grouped_rules)
                conn.execute(
                    "UPDATE transactions_norm "
                    "SET category_normalized = ?, category_parent = ? "
                    "WHERE transaction_fingerprint = ?",
                    [cat_n, cat_p, fp],
                )

        updated = conn.execute(
            "SELECT COUNT(*) FROM transactions_norm "
            "WHERE merchant = ? AND COALESCE(category_override, FALSE) = FALSE",
            [merchant],
        ).fetchone()[0]
        return updated
    finally:
        if own_conn:
            conn.close()


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
                "UPDATE normalization_jobs SET status='failed', error=?, finished_at=? "
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


# ---------------------------------------------------------------------------
# Description analysis — smart rule suggestions
# ---------------------------------------------------------------------------

# POS/payment-gateway prefixes that appear before the real merchant name
_PLATFORM_PREFIX_RE = re.compile(
    r"^(?:SQ \*|TST\*\s*|SP \*|PP\*|PAYPAL \*|DRI\*\s*|ADP\*\s*|CHECKCARD \d+\s+)",
    re.IGNORECASE,
)

# Trailing noise: US state codes, store/order numbers, hash-prefixed numbers
_TRAILING_NOISE_RE = re.compile(
    r"(?:"
    r"\s+[A-Z]{2}\s*$"      # " CA", " NY"
    r"|\s+#?\d{3,}\s*$"     # " #12345", " 01234"
    r"|\s+\d{1,4}\s*$"      # trailing 1-4 digit store number
    r")",
    re.IGNORECASE,
)

# Common domain TLDs to strip
_TLD_RE = re.compile(r"\.(?:com|net|org|io|co)\s*$", re.IGNORECASE)


def _strip_description(desc: str) -> str:
    """
    Strip transaction-unique noise from a raw description to expose the merchant core.

    Handles:
    - POS/gateway prefixes: "SQ *", "TST*", "PAYPAL *", etc.
    - Transaction ID suffixes: "AMAZON.COM*AB12XY9" → "AMAZON.COM"
    - Trailing store numbers and US state codes
    - Common TLDs (.com, .net, .org)
    """
    s = desc.strip()
    # 1. Strip known gateway prefixes
    m = _PLATFORM_PREFIX_RE.match(s)
    if m:
        s = s[m.end():].strip()
    # 2. Split on '*' — everything after is typically a transaction reference ID
    if "*" in s:
        s = s.split("*")[0].strip()
    # 3. Iteratively strip trailing noise (state codes, digit strings)
    for _ in range(4):
        cleaned = _TRAILING_NOISE_RE.sub("", s).strip()
        if cleaned == s:
            break
        s = cleaned
    # 4. Strip trailing TLD
    s = _TLD_RE.sub("", s).strip()
    return s


def _merchant_name_from_core(core: str) -> str:
    """Convert a stripped core string to a clean merchant display name."""
    name = re.sub(r"[._\-/\\]+", " ", core)
    name = re.sub(r"\s+", " ", name).strip()
    return name.title()


def analyze_descriptions(
    conn,
    min_transactions: int = 3,
    max_suggestions: int = 50,
) -> list[dict]:
    """
    Analyze transaction descriptions to suggest merchant normalization rules.

    Algorithm:
      1. Fetch all distinct descriptions with their transaction counts (up to 5 000).
      2. Skip descriptions already matched by an existing rule.
      3. Strip noise from each description to extract a merchant "core".
      4. Group descriptions by their core.
      5. Emit a suggestion for every group whose total transaction count ≥ min_transactions.
      6. Sort by count desc and return the top max_suggestions.

    Returns a list of suggestion dicts:
      {pattern, match_type, merchant, count, num_variants, sample_descriptions}
    """
    from collections import defaultdict

    rows = conn.execute(
        "SELECT description, COUNT(*) AS cnt "
        "FROM transactions_norm "
        "WHERE description IS NOT NULL "
        "GROUP BY description "
        "ORDER BY cnt DESC "
        "LIMIT 5000"
    ).fetchall()

    existing_rules = load_rules(conn)

    groups: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for raw_desc, cnt in rows:
        if not raw_desc:
            continue
        # Skip descriptions already normalized by an existing rule
        if any(r.matches(raw_desc) for r in existing_rules):
            continue
        core = _strip_description(raw_desc)
        if not core or len(core) < 3:
            continue
        groups[core].append((raw_desc, int(cnt)))

    suggestions: list[dict] = []
    for core, items in groups.items():
        total_count = sum(cnt for _, cnt in items)
        if total_count < min_transactions:
            continue

        items_sorted = sorted(items, key=lambda x: x[1], reverse=True)
        sample_descs = [d for d, _ in items_sorted[:5]]

        # Skip: only one variant and it already equals the core (already clean)
        if len(items) == 1 and sample_descs[0].strip().upper() == core.strip().upper():
            continue

        # Prefer startswith when all variants share the core as a prefix
        core_lower = core.lower()
        all_start = all(d.lower().startswith(core_lower) for d, _ in items)
        match_type = "startswith" if (all_start and len(core) >= 4) else "contains"

        suggestions.append({
            "pattern":            core,
            "match_type":         match_type,
            "merchant":           _merchant_name_from_core(core),
            "count":              total_count,
            "num_variants":       len(items),
            "sample_descriptions": sample_descs,
        })

    return sorted(suggestions, key=lambda x: x["count"], reverse=True)[:max_suggestions]


# ---------------------------------------------------------------------------
# Category suggestions — keyword heuristics
# ---------------------------------------------------------------------------

# (category_name, [keywords that imply membership])
# Category names aligned with BUILT_IN_CATEGORY_MAP subcategories in category_rules.py
_CATEGORY_HINTS: list[tuple[str, list[str]]] = [
    ("Restaurants", [
        "restaurant", "cafe", "coffee", "pizza", "burger", "grill", "sushi",
        "mcdonald", "starbucks", "chipotle", "subway", "domino", "taco bell",
        "dunkin", "doordash", "grubhub", "uber eats", "panera", "shake shack",
        "chick-fil", "five guys", "wendy", "kfc", "popeye", "bakery", "diner",
        "kitchen", "bistro", "eatery", "bbq", "steakhouse", "sandwich",
        "noodle", "ramen", "thai", "tapas", "brasserie", "cantina",
    ]),
    ("Groceries", [
        "grocery", "supermarket", "kroger", "safeway", "aldi", "whole foods",
        "trader joe", "publix", "wegmans", "costco", "food mart", "fresh market",
        "harris teeter", "meijer", "giant", "sprouts", "food lion", "h-e-b",
        "market basket", "stop & shop", "walmart supercenter",
    ]),
    ("Gas & Fuel", [
        "shell", "bp", "chevron", "exxon", "mobil", "sunoco", "marathon",
        "valero", "phillips 66", "circle k", "wawa", "speedway", "casey",
        "gas station", "fuel", "petroleum",
    ]),
    ("Rideshare & Taxis", [
        "uber", "lyft", "taxi", "parking", "toll", "transit", "metro", "mta",
    ]),
    ("General Retail", [
        "amazon", "amzn", "ebay", "etsy", "target", "best buy", "home depot",
        "lowes", "ikea", "nordstrom", "macy", "gap", "h&m", "zara", "uniqlo",
        "tj maxx", "marshalls", "ross", "dollar tree", "dollar general",
        "five below", "bath & body", "victoria secret", "old navy", "banana republic",
        "autozone", "advance auto",
    ]),
    ("Streaming", [
        "netflix", "spotify", "hulu", "disney", "apple tv", "youtube",
        "hbo", "amazon prime", "peacock", "paramount", "crunchyroll",
    ]),
    ("Entertainment", [
        "steam", "playstation", "xbox", "nintendo", "twitch",
        "cinema", "theater", "amc", "regal", "ticketmaster", "stubhub",
    ]),
    ("Pharmacy", [
        "pharmacy", "cvs", "walgreens", "rite aid",
    ]),
    ("Medical", [
        "hospital", "clinic", "doctor", "medical", "dental", "optometry",
        "health", "wellness", "urgent care",
    ]),
    ("Fitness", [
        "gym", "planet fitness", "la fitness", "24 hour fitness", "equinox",
    ]),
    ("Hotels & Lodging", [
        "hotel", "marriott", "hilton", "hyatt", "airbnb", "vrbo", "motel",
        "booking.com", "expedia",
    ]),
    ("Airlines", [
        "delta", "united airlines", "american airlines",
        "southwest", "jetblue", "spirit", "frontier", "alaska air",
    ]),
    ("Rental Cars", [
        "hertz", "enterprise", "avis", "budget rent",
    ]),
    ("Internet & Cable", [
        "adobe", "microsoft", "google", "dropbox", "zoom", "slack",
        "github", "notion", "figma", "canva", "cloudflare",
        "aws", "azure", "digitalocean", "openai", "anthropic",
    ]),
    ("Utilities", [
        "electric", "water utility", "gas utility", "internet", "cable",
        "comcast", "spectrum", "at&t", "att", "verizon", "t-mobile",
        "power company", "energy",
    ]),
    ("Insurance", [
        "insurance", "geico", "progressive", "state farm", "allstate",
    ]),
    ("Other Financial", [
        "paypal", "venmo", "cashapp", "zelle",
        "loan", "mortgage", "fidelity", "schwab", "robinhood",
        "coinbase", "crypto", "brokerage", "credit union",
    ]),
]


def suggest_categories_for_merchants(merchants: list[str]) -> list[dict]:
    """
    Suggest categories for a list of merchant names using keyword heuristics.

    Scores each merchant against the category keyword lists and returns
    the best-matching category.  Merchants with no keyword match are omitted.

    Returns [{merchant, suggested_category, confidence}].
    Confidence is 'high' for 2+ keyword matches, 'medium' for 1.
    """
    results: list[dict] = []
    for merchant in merchants:
        m_lower = merchant.lower()
        best_cat: str | None = None
        best_score = 0
        for category, keywords in _CATEGORY_HINTS:
            score = sum(1 for kw in keywords if kw in m_lower)
            if score > best_score:
                best_score = score
                best_cat = category
        if best_cat:
            results.append({
                "merchant":           merchant,
                "suggested_category": best_cat,
                "confidence":         "high" if best_score >= 2 else "medium",
            })
    return results
