"""Route-level tests, including regressions for the bugs found in the original app."""

import pytest
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


# --- search, tags and grouping ----------------------------------------------

def tagged_recipe(client, name, protein, tags=(), cuisines=(), ingredient="Potatoes"):
    import store
    from db import get_db

    with client.application.app_context():
        return store.save_recipe(get_db(), {
            "name": name, "servings": 2, "cooking_time_mins": 30,
            "yields": {2: [{"quantity": 1, "unit": "", "name": ingredient,
                            "is_pantry": False}]},
            "instructions": [], "protein": protein,
            "tags": list(tags), "cuisines": list(cuisines),
        })


def test_search_matches_recipe_name(client):
    tagged_recipe(client, "Chicken Korma", "Chicken")
    tagged_recipe(client, "Beef Stew", "Beef")
    body = client.get("/recipes?q=korma").get_data(as_text=True)
    assert "Chicken Korma" in body
    assert "Beef Stew" not in body


def test_search_matches_ingredient_not_just_title(client):
    """'chorizo' should find the pasta dish even though the title omits it."""
    tagged_recipe(client, "Penne 'n' Cheese", "Pork", ingredient="Chorizo")
    body = client.get("/recipes?q=chorizo").get_data(as_text=True)
    assert "Penne" in body


def test_filter_by_protein(client):
    tagged_recipe(client, "Chicken Korma", "Chicken")
    tagged_recipe(client, "Beef Stew", "Beef")
    body = client.get("/recipes?protein=Beef").get_data(as_text=True)
    assert "Beef Stew" in body
    assert "Chicken Korma" not in body


def test_filter_by_tag(client):
    tagged_recipe(client, "Fast One", "Chicken", tags=["Quick and Easy"])
    tagged_recipe(client, "Slow One", "Chicken", tags=["Family Friendly"])
    body = client.get("/recipes?tag=Quick+and+Easy").get_data(as_text=True)
    assert "Fast One" in body
    assert "Slow One" not in body


def test_search_and_filter_combine(client):
    tagged_recipe(client, "Chicken Korma", "Chicken", tags=["Quick and Easy"])
    tagged_recipe(client, "Chicken Pie", "Chicken", tags=["Family Friendly"])
    body = client.get("/recipes?q=chicken&tag=Quick+and+Easy").get_data(as_text=True)
    assert "Chicken Korma" in body
    assert "Chicken Pie" not in body


def test_grouping_headings_appear(client):
    tagged_recipe(client, "Chicken Korma", "Chicken")
    tagged_recipe(client, "Beef Stew", "Beef")
    body = client.get("/recipes?group=protein").get_data(as_text=True)
    assert "<h2>Beef" in body
    assert "<h2>Chicken" in body


def test_grouping_by_cuisine(client):
    tagged_recipe(client, "Korma", "Chicken", cuisines=["Indian"])
    body = client.get("/recipes?group=cuisine").get_data(as_text=True)
    assert "<h2>Indian" in body


def test_no_results_message(client):
    tagged_recipe(client, "Chicken Korma", "Chicken")
    body = client.get("/recipes?q=zzzznotathing").get_data(as_text=True)
    assert "Nothing matched" in body


def test_tags_are_replaced_not_duplicated_on_reimport(client):
    import store
    from db import get_db

    recipe_id = tagged_recipe(client, "Dish", "Chicken", tags=["Old Tag"])
    with client.application.app_context():
        conn = get_db()
        store.save_recipe(conn, {
            "name": "Dish", "servings": 2, "cooking_time_mins": 30,
            "yields": {2: [{"quantity": 1, "unit": "", "name": "X", "is_pantry": False}]},
            "instructions": [], "protein": "Beef", "tags": ["New Tag"], "cuisines": [],
        }, recipe_id=recipe_id)
        tags = store.get_tags(conn, recipe_id)

    names = {t["tag"] for t in tags}
    assert names == {"New Tag", "Beef"}


def test_backfill_gives_old_recipes_a_protein(client):
    """Recipes saved before tagging existed must still group, without re-import."""
    import store
    from db import get_db

    with client.application.app_context():
        conn = get_db()
        recipe_id = store.save_recipe(conn, {
            "name": "Legacy Beef Hash", "servings": 2, "cooking_time_mins": 45,
            "yields": {2: [{"quantity": 400, "unit": "grams",
                            "name": "Beef Mince", "is_pantry": False}]},
            "instructions": [],
        })
        conn.execute("DELETE FROM recipe_tags WHERE recipe_id = ?", (recipe_id,))
        conn.commit()
        assert store.get_tags(conn, recipe_id) == []

        assert store.backfill_proteins(conn) == 1
        assert [t["tag"] for t in store.get_tags(conn, recipe_id)] == ["Beef"]


def test_backfill_leaves_tagged_recipes_alone(client):
    import store
    from db import get_db

    recipe_id = tagged_recipe(client, "Already Tagged", "Chicken")
    with client.application.app_context():
        conn = get_db()
        assert store.backfill_proteins(conn) == 0
        assert [t["tag"] for t in store.get_tags(conn, recipe_id)] == ["Chicken"]


# --- deleting from the library ----------------------------------------------

def test_recipe_list_has_a_delete_button(client):
    make_recipe(client)
    body = client.get("/recipes").get_data(as_text=True)
    assert 'action="/recipes/1/delete"' in body
    assert "confirm(" in body


def test_delete_from_list_removes_the_recipe(client):
    make_recipe(client)
    assert client.post("/recipes/1/delete", data={"next": "/recipes"}).status_code == 302
    # Check for the card link, not the name: the flash message legitimately
    # says 'Deleted "Test Curry"'.
    body = client.get("/recipes").get_data(as_text=True)
    assert 'href="/recipes/1"' not in body
    assert "No recipes yet" in body


def test_delete_returns_to_the_filtered_list(client):
    """Deleting from a filtered view shouldn't throw away the filters."""
    tagged_recipe(client, "Chicken Korma", "Chicken")
    tagged_recipe(client, "Chicken Pie", "Chicken")
    resp = client.post("/recipes/2/delete", data={"next": "/recipes?q=chicken"})
    assert resp.headers["Location"].endswith("/recipes?q=chicken")


@pytest.mark.parametrize("evil", ["https://evil.example.com", "//evil.example.com"])
def test_delete_next_cannot_redirect_off_site(client, evil):
    make_recipe(client)
    resp = client.post("/recipes/1/delete", data={"next": evil})
    assert "evil.example.com" not in resp.headers["Location"]


def test_deleting_a_planned_recipe_clears_it_from_the_plan(client):
    import store
    from db import get_db

    make_recipe(client)
    client.post("/plan/add/1", data={"portions": 2})
    client.post("/recipes/1/delete")

    with client.application.app_context():
        conn = get_db()
        plan = store.get_active_plan(conn)
        assert store.plan_entries(conn, plan["id"]) == []
        lines, _ = store.build_shopping_list(conn, plan["id"])
    assert lines == []


def test_deleting_a_missing_recipe_is_404(client):
    assert client.post("/recipes/999/delete").status_code == 404


def test_delete_confirm_warns_when_recipe_is_planned(client):
    make_recipe(client)
    client.post("/plan/add/1", data={"portions": 2})
    body = client.get("/recipes").get_data(as_text=True)
    assert "removed from it" in body


def test_adding_a_deleted_recipe_does_not_500(client):
    """A stale link or a re-submit after deleting hit a foreign key error."""
    make_recipe(client)
    client.post("/recipes/1/delete")

    resp = client.post("/plan/add/1", data={"portions": 2})
    assert resp.status_code == 302
    body = client.get("/recipes").get_data(as_text=True)
    assert "no longer exists" in body


def test_adding_a_never_existing_recipe_does_not_500(client):
    assert client.post("/plan/add/12345", data={"portions": 2}).status_code == 302
