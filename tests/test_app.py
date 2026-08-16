"""Route-level tests, including regressions for the bugs found in the original app."""

import re

from werkzeug.datastructures import MultiDict


SAMPLE = {
    "name": "Test Curry",
    "cooking_time_mins": 30,
    "servings": 2,
    "yields": {
        2: [
            {"quantity": 450, "unit": "grams", "name": "Potatoes", "is_pantry": False},
            {"quantity": 1, "unit": "unit(s)", "name": "Garlic Clove", "is_pantry": False},
            {"quantity": 20, "unit": "grams", "name": "Butter", "is_pantry": True},
        ]
    },
    "instructions": ["Chop things.", "Cook things."],
}


def make_recipe(client, **overrides):
    import store
    from db import get_db

    data = dict(SAMPLE)
    data.update(overrides)
    with client.application.app_context():
        return store.save_recipe(get_db(), data)


def test_all_pages_load(client):
    make_recipe(client)
    for url in ["/", "/recipes", "/recipes/1", "/recipes/new", "/import", "/shopping"]:
        assert client.get(url).status_code == 200, url


def test_missing_recipe_is_404_not_500(client):
    assert client.get("/recipes/999").status_code == 404


def test_recipe_list_actually_renders_recipes(client):
    """The original app rendered a hardcoded 'Example Recipe' and ignored the DB."""
    make_recipe(client)
    body = client.get("/recipes").get_data(as_text=True)
    assert "Test Curry" in body
    assert "Example Recipe" not in body


def test_edit_roundtrip_preserves_everything(client):
    """Regression: submitting the edit form unchanged used to wipe the recipe."""
    import store
    from db import get_db

    make_recipe(client)
    html = client.get("/recipes/1/edit").get_data(as_text=True)

    data = MultiDict()
    for name, val in re.findall(r'name="([^"]+)"[^>]*value="([^"]*)"', html):
        data.add(name, val)
    for text in re.findall(r'<textarea name="instruction\[\]"[^>]*>(.*?)</textarea>', html, re.S):
        data.add("instruction[]", text.strip())

    assert client.post("/recipes/1/edit", data=data).status_code == 302

    with client.application.app_context():
        recipe = store.get_recipe(get_db(), 1)
    assert recipe["name"] == "Test Curry"
    assert recipe["cooking_time_mins"] == 30
    assert len(recipe["ingredients"]) == 3
    assert len(recipe["instructions"]) == 2
    assert [i["name"] for i in recipe["ingredients"]] == ["Potatoes", "Garlic Clove", "Butter"]


def test_edit_preserves_pantry_flag(client):
    import store
    from db import get_db

    make_recipe(client)
    html = client.get("/recipes/1/edit").get_data(as_text=True)
    data = MultiDict()
    for name, val in re.findall(r'name="([^"]+)"[^>]*value="([^"]*)"', html):
        data.add(name, val)
    client.post("/recipes/1/edit", data=data)

    with client.application.app_context():
        recipe = store.get_recipe(get_db(), 1)
    pantry = {i["name"]: i["is_pantry"] for i in recipe["ingredients"]}
    assert pantry["Butter"] == 1
    assert pantry["Potatoes"] == 0


def test_delete_requires_post(client):
    """Regression: delete used to be a GET, so any prefetch could wipe data."""
    make_recipe(client)
    assert client.get("/delete/1").status_code == 404
    assert client.post("/recipes/1/delete").status_code == 302
    assert client.get("/recipes/1").status_code == 404


def test_plan_and_shopping_list_flow(client):
    make_recipe(client)
    client.post("/plan/add/1", data={"portions": 2})

    body = client.get("/shopping").get_data(as_text=True)
    assert "450 g" in body
    assert "Potatoes" in body
    assert "Butter" not in body  # pantry item hidden by default

    assert "Butter" in client.get("/shopping?pantry=1").get_data(as_text=True)


def test_ingredients_merge_across_two_recipes(client):
    make_recipe(client)
    make_recipe(client, name="Second Dish", yields={
        2: [{"quantity": 550, "unit": "grams", "name": "potatoes", "is_pantry": False}]
    })
    client.post("/plan/add/1", data={"portions": 2})
    client.post("/plan/add/2", data={"portions": 2})

    body = client.get("/shopping").get_data(as_text=True)
    assert "1 kg" in body  # 450 g + 550 g, promoted to kg


def test_tick_off_persists(client):
    make_recipe(client)
    client.post("/plan/add/1", data={"portions": 2})

    resp = client.post("/shopping/toggle", json={"key": "potato|g", "checked": True})
    assert resp.status_code == 200

    body = client.get("/shopping").get_data(as_text=True)
    assert re.search(r'<li class="checked" data-key="potato\|g"', body)


def test_extra_items(client):
    client.post("/shopping/extra", data={"text": "Bin bags"})
    assert "Bin bags" in client.get("/shopping").get_data(as_text=True)


def test_plain_text_export(client):
    make_recipe(client)
    client.post("/plan/add/1", data={"portions": 2})
    resp = client.get("/shopping.txt")
    assert resp.mimetype == "text/plain"
    assert "450 g Potatoes" in resp.get_data(as_text=True)


def test_portions_uses_published_yield_table(client):
    """With a 4-portion table available, we use its numbers rather than doubling."""
    import store
    from db import get_db

    make_recipe(client, yields={
        2: [{"quantity": 450, "unit": "grams", "name": "Potatoes", "is_pantry": False}],
        4: [{"quantity": 900, "unit": "grams", "name": "Potatoes", "is_pantry": False}],
    })
    with client.application.app_context():
        recipe = store.get_recipe(get_db(), 1, portions=4)
    assert recipe["multiplier"] == 1.0
    assert recipe["ingredients"][0]["quantity"] == 900


def test_portions_falls_back_to_scaling(client):
    import store
    from db import get_db

    make_recipe(client)  # only a 2-portion table
    with client.application.app_context():
        recipe = store.get_recipe(get_db(), 1, portions=6)
    assert recipe["multiplier"] == 3.0
