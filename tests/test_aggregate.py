"""The ingredient merging that makes the shopping list worth having."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aggregate import aggregate, format_quantity, normalise_name, normalise_unit


def line(qty, unit, name, recipe="R", pantry=False, multiplier=1.0):
    return {
        "quantity": qty, "unit": unit, "name": name, "is_pantry": pantry,
        "recipe_name": recipe, "multiplier": multiplier,
    }


def test_grams_and_kilos_combine():
    out = aggregate([line(450, "grams", "Potatoes", "A"), line(0.5, "kg", "potatoes", "B")])
    assert len(out) == 1
    assert out[0]["display_quantity"] == "950 g"
    assert out[0]["recipes"] == ["A", "B"]


def test_promotes_to_kg_when_large():
    out = aggregate([line(600, "g", "Potatoes", "A"), line(700, "g", "Potatoes", "B")])
    assert out[0]["display_quantity"] == "1.3 kg"


def test_millilitres_and_litres_combine():
    out = aggregate([line(500, "ml", "Stock", "A"), line(1, "litre", "stock", "B")])
    assert out[0]["display_quantity"] == "1.5 l"


def test_different_dimensions_stay_separate():
    """2 tbsp mayo must not be summed with 100 ml mayo."""
    out = aggregate([line(2, "tbsp", "Mayonnaise"), line(100, "ml", "Mayonnaise")])
    assert len(out) == 2


def test_unitless_does_not_merge_with_united():
    """HelloFresh sometimes omits units; a bare 400 must not fake-merge into grams."""
    out = aggregate([line(400, "", "Penne Pasta", "A"), line(200, "g", "Penne Pasta", "B")])
    assert len(out) == 2


def test_pantry_items_excluded_by_default():
    rows = [line(450, "g", "Potatoes"), line(20, "g", "Butter", pantry=True)]
    assert len(aggregate(rows)) == 1
    assert len(aggregate(rows, include_pantry=True)) == 2


def test_multiplier_scales_quantities():
    out = aggregate([line(100, "g", "Peas", multiplier=1.5)])
    assert out[0]["display_quantity"] == "150 g"


def test_allergen_parentheticals_ignored_when_matching():
    out = aggregate([
        line(200, "grams", "Salmon Fillets (Contains: Fish)", "A"),
        line(100, "grams", "Salmon Fillets", "B"),
    ])
    assert len(out) == 1
    assert out[0]["display_quantity"] == "300 g"


def test_unit_aliases():
    assert normalise_unit("Grams") == ("g", 1.0)
    assert normalise_unit("kg") == ("g", 1000.0)
    assert normalise_unit("unit(s)") == ("", 1.0)
    assert normalise_unit("cloves") == ("clove", 1.0)


def test_name_normalisation():
    assert normalise_name("Garlic Clove") == "garlic"
    assert normalise_name("  POTATOES  ") == "potato"
    assert normalise_name("Chicken Breasts (Contains: nothing)") == "chicken breast"


def test_quantity_formatting_trims_noise():
    assert format_quantity(2.0, "g") == "2 g"
    assert format_quantity(2.5, "tbsp") == "2.5 tbsp"
    assert format_quantity(1, "") == "1"
    assert format_quantity(None, "g") == ""
