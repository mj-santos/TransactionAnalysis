"""Tests for subcategory-aware category suggestion matching."""

import pytest
from finance_etl.merchant_rules import suggest_categories_for_merchants


class TestSubcategoryMatching:
    """Verify that suggest_categories_for_merchants returns specific subcategories."""

    def test_coffee_suggests_coffee_shops(self):
        results = suggest_categories_for_merchants(["Starbucks Coffee"])
        assert len(results) == 1
        assert results[0]["suggested_category"] == "Coffee Shops"
        assert results[0]["parent_category"] == "Food & Dining"

    def test_dunkin_suggests_coffee_shops(self):
        results = suggest_categories_for_merchants(["Dunkin Donuts"])
        assert len(results) == 1
        assert results[0]["suggested_category"] == "Coffee Shops"

    def test_fast_food_suggests_fast_food(self):
        results = suggest_categories_for_merchants(["McDonald's"])
        assert len(results) == 1
        assert results[0]["suggested_category"] == "Fast Food"
        assert results[0]["parent_category"] == "Food & Dining"

    def test_taco_bell_suggests_fast_food(self):
        results = suggest_categories_for_merchants(["Taco Bell #1234"])
        assert len(results) == 1
        assert results[0]["suggested_category"] == "Fast Food"

    def test_doordash_suggests_food_delivery(self):
        results = suggest_categories_for_merchants(["DoorDash Order"])
        assert len(results) == 1
        assert results[0]["suggested_category"] == "Food Delivery"
        assert results[0]["parent_category"] == "Food & Dining"

    def test_restaurant_suggests_restaurants(self):
        results = suggest_categories_for_merchants(["Olive Garden Restaurant"])
        assert len(results) == 1
        assert results[0]["suggested_category"] == "Restaurants"

    def test_parent_category_included(self):
        results = suggest_categories_for_merchants(["Shell Gas Station"])
        assert len(results) == 1
        assert "parent_category" in results[0]
        assert results[0]["parent_category"] == "Transportation"

    def test_groceries_still_match(self):
        results = suggest_categories_for_merchants(["Kroger Grocery"])
        assert len(results) == 1
        assert results[0]["suggested_category"] == "Groceries"

    def test_gas_still_matches(self):
        results = suggest_categories_for_merchants(["Chevron Gas Station"])
        assert len(results) == 1
        assert results[0]["suggested_category"] == "Gas & Fuel"

    def test_streaming_still_matches(self):
        results = suggest_categories_for_merchants(["Netflix"])
        assert len(results) == 1
        assert results[0]["suggested_category"] == "Streaming"

    def test_no_match_returns_empty(self):
        results = suggest_categories_for_merchants(["XYZ Unknown Corp"])
        assert len(results) == 0

    def test_confidence_high_for_multiple_matches(self):
        results = suggest_categories_for_merchants(["Starbucks Coffee Shop"])
        assert len(results) == 1
        assert results[0]["confidence"] == "high"

    def test_confidence_medium_for_single_match(self):
        results = suggest_categories_for_merchants(["Netflix"])
        assert len(results) == 1
        assert results[0]["confidence"] == "medium"

    def test_pharmacy_still_matches(self):
        results = suggest_categories_for_merchants(["CVS Pharmacy"])
        assert len(results) == 1
        assert results[0]["suggested_category"] == "Pharmacy"

    def test_parking_suggests_parking_tolls(self):
        results = suggest_categories_for_merchants(["City Parking Garage"])
        assert len(results) == 1
        assert results[0]["suggested_category"] == "Parking & Tolls"
