"""Protein detection and tag cleanup."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from taxonomy import clean_tags, detect_protein, difficulty_label, is_flavouring


@pytest.mark.parametrize("ingredients,expected", [
    (["Chicken Breast", "Rice"], "Chicken"),
    (["Beef Mince", "Onion"], "Beef"),
    (["Pork Loin", "Apple"], "Pork"),
    (["Diced Lamb", "Mint"], "Lamb"),
    (["Salmon Fillets", "Peas"], "Fish"),
    (["King Prawns", "Noodles"], "Seafood"),
    (["Chorizo", "Penne Pasta"], "Pork"),
    (["Potatoes", "Broccoli", "Peas"], "Veggie"),
])
def test_protein_from_ingredients(ingredients, expected):
    assert detect_protein(ingredients) == expected


def test_stock_does_not_decide_the_protein():
    """The real case: a chorizo pasta listing Chicken Stock Powder is pork."""
    assert detect_protein(["Chorizo", "Chicken Stock Powder", "Penne"]) == "Pork"


@pytest.mark.parametrize("name", [
    "Chicken Stock Powder", "Beef Bouillon", "Vegetable Stock Cube",
    "Chicken Seasoning", "Korma Curry Paste", "Fish Sauce",
])
def test_flavourings_recognised(name):
    assert is_flavouring(name)


def test_a_dish_of_only_flavourings_is_veggie():
    assert detect_protein(["Chicken Stock Powder", "Beef Bouillon"]) == "Veggie"


def test_real_meat_still_wins_alongside_stock():
    assert detect_protein(["Chicken Breast", "Chicken Stock Powder"]) == "Chicken"


def test_empty_ingredients_are_veggie():
    assert detect_protein([]) == "Veggie"
    assert detect_protein([None, ""]) == "Veggie"


# --- tags -------------------------------------------------------------------

def test_keeps_displayable_tags():
    tags = clean_tags([
        {"name": "Family Friendly", "slug": "family-friendly", "displayLabel": True},
        {"name": "High Protein", "slug": "high-protein", "displayLabel": True},
    ])
    assert tags == ["Family Friendly", "High Protein"]


def test_drops_internal_tags():
    tags = clean_tags([
        {"name": "SEO", "slug": "seo", "displayLabel": False},
        {"name": "classic-plates", "slug": "classic-plates", "displayLabel": False},
        {"name": "South/SoutheastAsian", "slug": "south-southeastasian", "displayLabel": False},
    ])
    assert tags == []


def test_keeps_useful_hidden_tags():
    """Some hidden tags are still worth showing a human."""
    tags = clean_tags([{"name": "Quick and Easy", "slug": "quick-and-easy",
                        "displayLabel": False}])
    assert tags == ["Quick and Easy"]


def test_junk_slug_wins_over_display_flag():
    assert clean_tags([{"name": "SEO", "slug": "seo", "displayLabel": True}]) == []


def test_tags_deduplicated_and_blank_safe():
    tags = clean_tags([
        {"name": "Family Friendly", "slug": "a", "displayLabel": True},
        {"name": "Family Friendly", "slug": "b", "displayLabel": True},
        {"name": "", "slug": "c", "displayLabel": True},
        {},
    ])
    assert tags == ["Family Friendly"]


def test_difficulty_labels():
    assert difficulty_label(1) == "Easy"
    assert difficulty_label(2) == "Medium"
    assert difficulty_label(99) is None


@pytest.mark.parametrize("ingredients,expected", [
    # Plurals must match: "\bprawn\b" never matched "King Prawns".
    (["King Prawns"], "Seafood"),
    (["Salmon Fillets"], "Fish"),
    (["Pork Sausages"], "Pork"),
    (["Beef Steaks"], "Beef"),
    # A bare "mince" in the Beef rule made every mince beef.
    (["Pork Mince", "Onion"], "Pork"),
    (["Lamb Mince", "Onion"], "Lamb"),
    (["Beef Mince", "Onion"], "Beef"),
    # Nothing names the animal, so the generic tier decides.
    (["Mince", "Onion"], "Beef"),
])
def test_plurals_and_generic_mince(ingredients, expected):
    assert detect_protein(ingredients) == expected
