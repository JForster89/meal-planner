"""Aisle grouping: walking the shop once instead of doubling back."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from taxonomy import AISLE_ORDER, aisle_sort_key, detect_aisle


@pytest.mark.parametrize("ingredient,aisle", [
    ("Potatoes", "Fruit & Veg"),
    ("Broccoli Florets", "Fruit & Veg"),
    ("Garlic Clove", "Fruit & Veg"),
    ("Echalion Shallot", "Fruit & Veg"),
    ("Salmon Fillets", "Meat & Fish"),
    ("Chorizo", "Meat & Fish"),
    ("Chicken Breast", "Meat & Fish"),
    ("Mature Cheddar Cheese", "Dairy & Eggs"),
    ("Creme Fraiche", "Dairy & Eggs"),
    ("Butter", "Dairy & Eggs"),
    ("Panko Breadcrumbs", "Bakery"),
    ("Penne Pasta", "Cupboard"),
    ("Plain Flour", "Cupboard"),
    ("Mango Chutney", "Cupboard"),
])
def test_ingredients_land_in_the_right_aisle(ingredient, aisle):
    assert detect_aisle(ingredient) == aisle


def test_stock_goes_to_the_cupboard_not_the_meat_counter():
    """The same trap as protein detection: stock is a flavouring."""
    assert detect_aisle("Chicken Stock Powder") == "Cupboard"
    assert detect_aisle("Beef Bouillon") == "Cupboard"


def test_korma_paste_is_cupboard_not_produce():
    assert detect_aisle("Korma Curry Paste") == "Cupboard"


def test_unknown_ingredients_fall_back():
    assert detect_aisle("Flurblewidget") == "Other"
    assert detect_aisle("") == "Other"
    assert detect_aisle(None) == "Other"


def test_aisles_sort_in_shop_order():
    shuffled = ["Cupboard", "Fruit & Veg", "Other", "Meat & Fish"]
    assert sorted(shuffled, key=aisle_sort_key) == [
        "Fruit & Veg", "Meat & Fish", "Cupboard", "Other",
    ]


def test_unknown_aisle_sorts_last():
    assert aisle_sort_key("Nonsense") >= len(AISLE_ORDER) - 1


# --- through the app --------------------------------------------------------

def test_shopping_list_groups_by_aisle(client):
    import store
    from db import get_db

    with client.application.app_context():
        store.save_recipe(get_db(), {
            "name": "Mixed", "servings": 2, "cooking_time_mins": 30,
            "yields": {2: [
                {"quantity": 450, "unit": "grams", "name": "Potatoes", "is_pantry": False},
                {"quantity": 200, "unit": "grams", "name": "Salmon Fillets", "is_pantry": False},
                {"quantity": 100, "unit": "grams", "name": "Penne Pasta", "is_pantry": False},
            ]},
            "instructions": [],
        })
    client.post("/plan/add/1", data={"portions": 2})

    body = client.get("/shopping").get_data(as_text=True)
    assert "Fruit &amp; Veg" in body or "Fruit & Veg" in body
    assert "Meat &amp; Fish" in body or "Meat & Fish" in body
    assert "Cupboard" in body
    # Produce before cupboard, i.e. shop order not alphabetical.
    assert body.index("Potatoes") < body.index("Penne Pasta")


def test_flat_list_still_available(client):
    import store
    from db import get_db

    with client.application.app_context():
        store.save_recipe(get_db(), {
            "name": "Mixed", "servings": 2, "cooking_time_mins": 30,
            "yields": {2: [{"quantity": 450, "unit": "grams",
                            "name": "Potatoes", "is_pantry": False}]},
            "instructions": [],
        })
    client.post("/plan/add/1", data={"portions": 2})

    body = client.get("/shopping?aisle=0").get_data(as_text=True)
    assert 'class="aisle"' not in body
    assert "Potatoes" in body


def test_aisle_stored_on_save(client):
    import store
    from db import get_db

    with client.application.app_context():
        conn = get_db()
        store.save_recipe(conn, {
            "name": "Dish", "servings": 2, "cooking_time_mins": 30,
            "yields": {2: [{"quantity": 1, "unit": "", "name": "Chorizo",
                            "is_pantry": False}]},
            "instructions": [],
        })
        row = conn.execute("SELECT aisle FROM ingredients WHERE name = 'Chorizo'").fetchone()
    assert row["aisle"] == "Meat & Fish"


@pytest.mark.parametrize("ingredient,aisle", [
    # Preserved forms beat the plain ingredient word.
    ("Dried Thyme", "Cupboard"),
    ("Dried Oregano", "Cupboard"),
    ("Finely Chopped Tomatoes", "Cupboard"),
    ("Tinned Chickpeas", "Cupboard"),
    ("Sun-Dried Tomatoes", "Cupboard"),
    ("Tomato Puree", "Cupboard"),
    ("Ground Cumin", "Cupboard"),
    ("Frozen Peas", "Frozen"),
    # ...but the fresh versions stay in produce.
    ("Thyme", "Fruit & Veg"),
    ("Tomatoes", "Fruit & Veg"),
    ("Peas", "Fruit & Veg"),
])
def test_preserved_forms_go_to_the_cupboard(ingredient, aisle):
    assert detect_aisle(ingredient) == aisle


def test_resync_moves_ingredients_when_rules_improve(client):
    """Improving the rules must re-file rows saved under the old ones."""
    import store
    from db import get_db

    with client.application.app_context():
        conn = get_db()
        store.save_recipe(conn, {
            "name": "Dish", "servings": 2, "cooking_time_mins": 30,
            "yields": {2: [{"quantity": 1, "unit": "", "name": "Dried Thyme",
                            "is_pantry": False}]},
            "instructions": [],
        })
        # Simulate a row filed by the older, wrong rules.
        conn.execute("UPDATE ingredients SET aisle = 'Fruit & Veg'")
        conn.commit()

        assert store.resync_aisles(conn) == 1
        row = conn.execute("SELECT aisle FROM ingredients").fetchone()
        assert row["aisle"] == "Cupboard"
        # Idempotent: a second run changes nothing.
        assert store.resync_aisles(conn) == 0
