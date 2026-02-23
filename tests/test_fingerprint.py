"""
Unit tests for transaction fingerprint — stability and uniqueness.
Covers design_rules.txt §3 (identity/dedupe) + §8.
"""
import datetime
from decimal import Decimal

import pytest

from finance_etl.utils.fingerprint import compute_fingerprint


class TestFingerprintStability:
    BASE = dict(
        bank_name="TestBank",
        account_id="ACC-001",
        transaction_date=datetime.date(2024, 3, 15),
        description="STARBUCKS COFFEE",
        amount=Decimal("-4.75"),
        currency="USD",
    )

    def test_same_inputs_same_hash(self):
        h1 = compute_fingerprint(**self.BASE)
        h2 = compute_fingerprint(**self.BASE)
        assert h1 == h2

    def test_description_whitespace_collapsed(self):
        """Extra whitespace in description should produce same fingerprint."""
        h1 = compute_fingerprint(**self.BASE)
        h2 = compute_fingerprint(**{**self.BASE, "description": "  STARBUCKS  COFFEE  "})
        assert h1 == h2

    def test_description_case_insensitive(self):
        """Lowercase and uppercase description should yield same fingerprint."""
        h1 = compute_fingerprint(**self.BASE)
        h2 = compute_fingerprint(**{**self.BASE, "description": "starbucks coffee"})
        assert h1 == h2

    def test_different_amount_different_hash(self):
        h1 = compute_fingerprint(**self.BASE)
        h2 = compute_fingerprint(**{**self.BASE, "amount": Decimal("-5.00")})
        assert h1 != h2

    def test_different_date_different_hash(self):
        h1 = compute_fingerprint(**self.BASE)
        h2 = compute_fingerprint(**{**self.BASE, "transaction_date": datetime.date(2024, 3, 16)})
        assert h1 != h2

    def test_different_bank_different_hash(self):
        h1 = compute_fingerprint(**self.BASE)
        h2 = compute_fingerprint(**{**self.BASE, "bank_name": "OtherBank"})
        assert h1 != h2

    def test_different_account_different_hash(self):
        h1 = compute_fingerprint(**self.BASE)
        h2 = compute_fingerprint(**{**self.BASE, "account_id": "ACC-002"})
        assert h1 != h2

    def test_different_currency_different_hash(self):
        h1 = compute_fingerprint(**self.BASE)
        h2 = compute_fingerprint(**{**self.BASE, "currency": "EUR"})
        assert h1 != h2

    def test_hash_is_64_char_hex(self):
        h = compute_fingerprint(**self.BASE)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_currency_case_insensitive(self):
        """Currency should be normalized to uppercase before hashing."""
        h1 = compute_fingerprint(**self.BASE)
        h2 = compute_fingerprint(**{**self.BASE, "currency": "usd"})
        assert h1 == h2

    def test_positive_amount(self):
        h = compute_fingerprint(**{**self.BASE, "amount": Decimal("1000.00")})
        assert isinstance(h, str) and len(h) == 64

    def test_zero_amount(self):
        h = compute_fingerprint(**{**self.BASE, "amount": Decimal("0.00")})
        assert isinstance(h, str) and len(h) == 64
