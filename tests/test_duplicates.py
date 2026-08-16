"""HelloFresh publishes one dish at several URLs, so the URL can't be its identity."""


def imported(client, name, url, canonical=None, qty=450, ingredient="Potatoes"):
    import store
    from db import get_db

    with client.application.app_context():
        return store.save_recipe(get_db(), {
            "name": name, "servings": 2, "cooking_time_mins": 30,
            "source_url": url, "canonical_id": canonical,
            "yields": {2: [{"quantity": qty, "unit": "grams",
                            "name": ingredient, "is_pantry": False}]},
            "instructions": [],
        })


def test_same_canonical_id_updates_rather_than_duplicates(client):
    import store
    from db import get_db

    imported(client, "Tacos", "https://hf/recipes/tacos-aaa", canonical="ID-1")
    with client.application.app_context():
        conn = get_db()
        found = store.find_existing(conn, {
            "canonical_id": "ID-1",
            "source_url": "https://hf/recipes/tacos-bbb",  # a different alias
        })
    assert found is not None


def test_different_canonical_ids_stay_separate(client):
    import store
    from db import get_db

    imported(client, "Tacos", "https://hf/recipes/tacos-aaa", canonical="ID-1")
    with client.application.app_context():
        found = store.find_existing(get_db(), {
            "canonical_id": "ID-2", "source_url": "https://hf/recipes/other-ccc",
        })
    assert found is None


def test_falls_back_to_url_without_a_canonical_id(client):
    import store
    from db import get_db

    imported(client, "Manual", "https://hf/recipes/thing-aaa")
    with client.application.app_context():
        found = store.find_existing(get_db(), {
            "canonical_id": None, "source_url": "https://hf/recipes/thing-aaa",
        })
    assert found is not None


# --- merging what's already been duplicated ---------------------------------

def test_identical_recipes_detected_as_duplicates(client):
    import store
    from db import get_db

    imported(client, "Tacos", "https://hf/recipes/tacos-aaa")
    imported(client, "Tacos", "https://hf/recipes/tacos-bbb")
    with client.application.app_context():
        assert store.count_duplicates(get_db()) == 1


def test_different_recipes_are_not_merged(client):
    import store
    from db import get_db

    imported(client, "Tacos", "https://hf/recipes/tacos-aaa", qty=450)
    imported(client, "Tacos", "https://hf/recipes/tacos-bbb", qty=900)
    with client.application.app_context():
        assert store.count_duplicates(get_db()) == 0


def test_same_name_different_ingredients_kept_apart(client):
    import store
    from db import get_db

    imported(client, "Penne", "https://hf/a", ingredient="Chorizo")
    imported(client, "Penne", "https://hf/b", ingredient="Chicken")
    with client.application.app_context():
        assert store.count_duplicates(get_db()) == 0


def test_merge_keeps_one_and_removes_the_rest(client):
    import store
    from db import get_db

    for suffix in "abcd":
        imported(client, "Tacos", f"https://hf/recipes/tacos-{suffix}")

    with client.application.app_context():
        conn = get_db()
        assert store.merge_duplicates(conn) == 3
        assert len(store.list_recipes(conn)) == 1
        assert store.count_duplicates(conn) == 0


def test_merge_prefers_the_copy_already_planned(client):
    """A planned meal must not vanish because a twin was saved first."""
    import store
    from db import get_db

    first = imported(client, "Tacos", "https://hf/recipes/tacos-a")
    second = imported(client, "Tacos", "https://hf/recipes/tacos-b")
    client.post(f"/plan/add/{second}", data={"portions": 2})

    with client.application.app_context():
        conn = get_db()
        store.merge_duplicates(conn)
        remaining = [r["id"] for r in store.list_recipes(conn)]
        plan = store.get_active_plan(conn)
        planned = [e["recipe_id"] for e in store.plan_entries(conn, plan["id"])]

    assert remaining == [second]
    assert planned == [second]
    assert first not in remaining


def test_merge_moves_plan_membership_onto_the_keeper(client):
    import store
    from db import get_db

    first = imported(client, "Tacos", "https://hf/recipes/tacos-a")
    client.post(f"/plan/add/{first}", data={"portions": 3})
    imported(client, "Tacos", "https://hf/recipes/tacos-b")

    with client.application.app_context():
        conn = get_db()
        store.merge_duplicates(conn)
        plan = store.get_active_plan(conn)
        entries = store.plan_entries(conn, plan["id"])

    assert len(entries) == 1
    assert entries[0]["portions"] == 3


def test_merge_is_safe_with_nothing_to_do(client):
    import store
    from db import get_db

    imported(client, "Solo", "https://hf/recipes/solo-a")
    with client.application.app_context():
        assert store.merge_duplicates(get_db()) == 0


def test_dedupe_button_appears_only_when_needed(client):
    imported(client, "Tacos", "https://hf/recipes/tacos-a")
    assert "recipes/dedupe" not in client.get("/recipes").get_data(as_text=True)

    imported(client, "Tacos", "https://hf/recipes/tacos-b")
    assert "recipes/dedupe" in client.get("/recipes").get_data(as_text=True)


def test_dedupe_route_merges(client):
    import store
    from db import get_db

    imported(client, "Tacos", "https://hf/recipes/tacos-a")
    imported(client, "Tacos", "https://hf/recipes/tacos-b")

    body = client.post("/recipes/dedupe", follow_redirects=True).get_data(as_text=True)
    assert "Merged 1 duplicate" in body
    with client.application.app_context():
        assert len(store.list_recipes(get_db())) == 1
