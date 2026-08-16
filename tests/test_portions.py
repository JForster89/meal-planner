"""Serving sizes: published yield tables, scaling fallback, and whole-unit rounding."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aggregate import aggregate, format_quantity


def line(qty, unit, name, multiplier=1.0):
    return {
        "quantity": qty, "unit": unit, "name": name, "is_pantry": False,
        "recipe_name": "R", "multiplier": multiplier,
    }


# --- whole-unit rounding ----------------------------------------------------

def test_cans_round_up_when_scaled():
    """1 can scaled to 3 portions is 1.5 - you have to buy 2."""
    out = aggregate([line(1, "can", "Sweetcorn", multiplier=1.5)])
    assert out[0]["display_quantity"] == "2 can"


def test_cloves_round_up():
    out = aggregate([line(1, "cloves", "Garlic", multiplier=1.5)])
    assert out[0]["display_quantity"] == "2 clove"


def test_countable_items_round_up():
    out = aggregate([line(1, "unit(s)", "Echalion Shallot", multiplier=1.5)])
    assert out[0]["display_quantity"] == "2"


def test_weights_keep_fractions():
    """450 g scaled to 3 portions is a real, buyable 675 g - do not round."""
    out = aggregate([line(450, "grams", "Potatoes", multiplier=1.5)])
    assert out[0]["display_quantity"] == "675 g"


def test_spoons_keep_fractions():
    out = aggregate([line(1, "tbsp", "Mayonnaise", multiplier=1.5)])
    assert out[0]["display_quantity"] == "1.5 tbsp"


def test_whole_numbers_are_not_inflated():
    """Rounding must not turn an exact 2 cans into 3."""
    assert format_quantity(2.0, "can") == "2 can"
    assert format_quantity(4.0, "") == "4"


# --- yield tables vs scaling ------------------------------------------------

def test_three_people_uses_published_table_not_arithmetic(client):
    """HelloFresh's 3-portion numbers are not 1.5x their 2-portion ones."""
    import store
    from db import get_db

    with client.application.app_context():
        conn = get_db()
        store.save_recipe(conn, {
            "name": "Korma", "servings": 2, "cooking_time_mins": 35,
            "yields": {
                2: [{"quantity": 450, "unit": "grams", "name": "Potatoes", "is_pantry": False}],
                3: [{"quantity": 700, "unit": "grams", "name": "Potatoes", "is_pantry": False}],
                4: [{"quantity": 900, "unit": "grams", "name": "Potatoes", "is_pantry": False}],
            },
            "instructions": [],
        })
        recipe = store.get_recipe(conn, 1, portions=3)

    assert recipe["multiplier"] == 1.0
    assert recipe["ingredients"][0]["quantity"] == 700  # not 675


def test_falls_back_to_scaling_beyond_published_range(client):
    import store
    from db import get_db

    with client.application.app_context():
        conn = get_db()
        store.save_recipe(conn, {
            "name": "Solo", "servings": 2, "cooking_time_mins": None,
            "yields": {2: [{"quantity": 1, "unit": "can", "name": "Sweetcorn", "is_pantry": False}]},
            "instructions": [],
        })
        recipe = store.get_recipe(conn, 1, portions=3)

    assert recipe["multiplier"] == 1.5


# --- household default ------------------------------------------------------

def test_default_portions_applies_to_newly_planned_recipes(client):
    import store
    from db import get_db

    with client.application.app_context():
        conn = get_db()
        store.save_recipe(conn, {
            "name": "Dish", "servings": 2, "cooking_time_mins": None,
            "yields": {2: [{"quantity": 450, "unit": "grams", "name": "Potatoes", "is_pantry": False}]},
            "instructions": [],
        })

    client.post("/plan/default-portions", data={"portions": 3})
    client.post("/plan/add/1")  # no explicit portions

    with client.application.app_context():
        conn = get_db()
        plan = store.get_active_plan(conn)
        entries = store.plan_entries(conn, plan["id"])
    assert entries[0]["portions"] == 3


def test_changing_default_updates_already_planned_recipes(client):
    import store
    from db import get_db

    with client.application.app_context():
        conn = get_db()
        store.save_recipe(conn, {
            "name": "Dish", "servings": 2, "cooking_time_mins": None,
            "yields": {2: [{"quantity": 450, "unit": "grams", "name": "Potatoes", "is_pantry": False}]},
            "instructions": [],
        })

    client.post("/plan/add/1", data={"portions": 2})
    client.post("/plan/default-portions", data={"portions": 4})

    with client.application.app_context():
        conn = get_db()
        plan = store.get_active_plan(conn)
        entries = store.plan_entries(conn, plan["id"])
    assert entries[0]["portions"] == 4


def test_default_portions_persists(client):
    import store
    from db import get_db

    client.post("/plan/default-portions", data={"portions": 5})
    with client.application.app_context():
        assert store.default_portions(get_db()) == 5
