"""
Date parsing with strict ambiguity detection.

Rules (from design_rules.txt §3):
- If mapping provides date_format: use it deterministically.
- Otherwise allow YYYY-MM-DD always (unambiguous).
- MM/DD/YYYY only if locale implies US.
- DD/MM/YYYY only if locale implies EU.
- Anything ambiguous → raise DateParseError.
"""
from __future__ import annotations

import datetime
import re
from typing import Any


class DateParseError(ValueError):
    pass


_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SLASH_8 = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_DASH_US = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$")


def parse_date(
    raw: str,
    date_format: str | None = None,
    locale_cfg: dict[str, Any] | None = None,
) -> datetime.date:
    """
    Parse a date string to datetime.date.

    Parameters
    ----------
    raw : str
        The raw date string from the CSV.
    date_format : str | None
        strptime format string from mapping (deterministic).
    locale_cfg : dict | None
        Locale hints: may contain 'date_locale' = 'US' | 'EU'.
    """
    if not raw or not raw.strip():
        raise DateParseError("Empty date string.")

    s = raw.strip()

    # 1. Explicit format from mapping — always wins
    if date_format:
        try:
            return datetime.datetime.strptime(s, date_format).date()
        except ValueError:
            raise DateParseError(
                f"Date {s!r} does not match configured format {date_format!r}."
            )

    # 2. ISO 8601 — always unambiguous
    if _ISO.match(s):
        try:
            return datetime.date.fromisoformat(s)
        except ValueError:
            raise DateParseError(f"Invalid ISO date: {s!r}")

    # 3. Slash or dash separated d/m/y — needs locale hint
    m = _SLASH_8.match(s) or _DASH_US.match(s)
    if m:
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        locale = (locale_cfg or {}).get("date_locale", "").upper()

        if a > 12 and b <= 12:
            # Unambiguous: a must be day
            return _make_date(year, b, a, s)
        if b > 12 and a <= 12:
            # Unambiguous: b must be day
            return _make_date(year, a, b, s)

        # Both could be month — need explicit locale
        if locale == "US":
            return _make_date(year, a, b, s)   # MM/DD/YYYY
        elif locale == "EU":
            return _make_date(year, b, a, s)   # DD/MM/YYYY
        else:
            raise DateParseError(
                f"Ambiguous date {s!r}: could be MM/DD or DD/MM. "
                "Set date_format or locale.date_locale = US|EU in your mapping YAML."
            )

    # 4. Try a few common named-month formats (unambiguous)
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y",
                "%m-%d-%Y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue

    raise DateParseError(
        f"Cannot parse date {s!r}. "
        "Specify date_format in your mapping YAML (strptime syntax)."
    )


def _make_date(year: int, month: int, day: int, raw: str) -> datetime.date:
    try:
        return datetime.date(year, month, day)
    except ValueError as e:
        raise DateParseError(f"Invalid date components from {raw!r}: {e}") from e
