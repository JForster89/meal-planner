"""The static shopping list published to GitHub Pages."""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from export_static import build_page, render_items, write_site


def line(name, qty="450 g", key=None, recipes=("Curry",), pantry=False):
    return {
        "key": key or name.lower(), "name": name, "display_quantity": qty,
        "recipes": list(recipes), "is_pantry": pantry, "unit": "g", "quantity": 450,
    }


def test_items_render_with_quantity_and_source():
    out = render_items([line("Potatoes", "450 g", recipes=("Curry", "Pasta"))])
    assert "450 g" in out
    assert "Potatoes" in out
    assert "Curry, Pasta" in out


def test_unquantified_items_omit_the_number():
    out = render_items([line("Sweetcorn", "")])
    assert "Sweetcorn" in out
    assert 'class="qty"' not in out


def test_pantry_items_are_marked():
    assert "cupboard" in render_items([line("Butter", pantry=True)])
    assert "cupboard" not in render_items([line("Potatoes")])


def test_checkbox_carries_the_stable_key():
    """Ticks are keyed by ingredient so republishing keeps them."""
    out = render_items([line("Potatoes", key="potato|g")])
    assert 'data-key="potato|g"' in out


def test_empty_list_says_so():
    assert "Nothing planned" in render_items([])


def test_html_in_names_is_escaped():
    out = render_items([line('<script>alert(1)</script>')])
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_quotes_in_key_cannot_break_the_attribute():
    out = render_items([line("X", key='a" onerror="alert(1)')])
    assert 'onerror="alert(1)"' not in out
    assert "&quot;" in out


def test_page_is_self_contained():
    """No external requests - it has to work with no signal."""
    page = build_page([line("Potatoes")])
    assert "<style>" in page and "<script>" in page
    for pattern in ["src=\"http", "href=\"http", "cdn.", "googleapis"]:
        assert pattern not in page


def test_page_reports_recipe_count():
    page = build_page([line("Potatoes")], recipe_names=["A", "B"])
    assert "2 recipes" in page


def test_write_site_emits_every_file(tmp_path):
    out = str(tmp_path)
    write_site([line("Potatoes")], ["Curry"], out_dir=out)
    for name in ["index.html", "sw.js", "manifest.json", ".nojekyll"]:
        assert os.path.exists(os.path.join(out, name)), name


def test_manifest_is_valid_json_with_relative_urls(tmp_path):
    """GitHub Pages serves project sites from a subpath, so absolute URLs break."""
    out = str(tmp_path)
    write_site([line("Potatoes")], out_dir=out)
    with open(os.path.join(out, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    assert manifest["start_url"].startswith("./")
    assert manifest["icons"][0]["src"].startswith("./")


def test_page_uses_relative_asset_paths(tmp_path):
    out = str(tmp_path)
    write_site([line("Potatoes")], out_dir=out)
    with open(os.path.join(out, "index.html"), encoding="utf-8") as fh:
        page = fh.read()
    assert 'href="./manifest.json"' in page
    assert "register('./sw.js')" in page
    assert 'href="/manifest.json"' not in page


def test_service_worker_cache_name_changes_per_publish(tmp_path):
    """A fixed cache name would serve last week's list forever."""
    import time
    out = str(tmp_path)
    write_site([line("Potatoes")], out_dir=out)
    with open(os.path.join(out, "sw.js"), encoding="utf-8") as fh:
        first = re.search(r"var CACHE = '([^']+)'", fh.read()).group(1)
    time.sleep(1.1)
    write_site([line("Potatoes")], out_dir=out)
    with open(os.path.join(out, "sw.js"), encoding="utf-8") as fh:
        second = re.search(r"var CACHE = '([^']+)'", fh.read()).group(1)
    assert first != second


def test_publish_route_writes_the_site(client, tmp_path, monkeypatch):
    import export_static
    import store
    from db import get_db

    monkeypatch.setattr(export_static, "OUT_DIR", str(tmp_path))
    original = export_static.write_site
    monkeypatch.setattr(
        export_static, "write_site",
        lambda lines, names=(), out_dir=None, recipes=():
            original(lines, names, str(tmp_path), recipes),
    )

    with client.application.app_context():
        conn = get_db()
        store.save_recipe(conn, {
            "name": "Curry", "servings": 2, "cooking_time_mins": 30,
            "yields": {2: [{"quantity": 450, "unit": "grams",
                            "name": "Potatoes", "is_pantry": False}]},
            "instructions": [],
        })
    client.post("/plan/add/1", data={"portions": 2})

    assert client.post("/publish").status_code == 302
    with open(os.path.join(str(tmp_path), "index.html"), encoding="utf-8") as fh:
        page = fh.read()
    assert "Potatoes" in page
    assert "450 g" in page


# --- cook page --------------------------------------------------------------

RECIPE = {
    "name": "Korma Salmon", "portions": 3, "cooking_time_mins": 35,
    "ingredients": [
        {"display_quantity": "700 g", "name": "Potatoes", "is_pantry": False},
        {"display_quantity": "30 g", "name": "Butter", "is_pantry": True},
    ],
    "steps": ["Preheat the oven.", "Chop the potatoes.", "Bake for 25 minutes."],
}


def test_cook_page_has_a_card_per_step_plus_ingredients():
    from export_static import build_cook_page
    page = build_cook_page([RECIPE])
    assert page.count('class="card"') == len(RECIPE["steps"]) + 1
    assert "Step 1 of 3" in page and "Step 3 of 3" in page


def test_cook_page_shows_ingredients_and_marks_pantry():
    from export_static import build_cook_page
    page = build_cook_page([RECIPE])
    assert "700 g" in page and "Potatoes" in page
    assert "cupboard" in page


def test_cook_page_picker_only_when_several_recipes():
    from export_static import build_cook_page
    assert 'id="picker"' not in build_cook_page([RECIPE])
    two = build_cook_page([RECIPE, dict(RECIPE, name="Second")])
    assert 'id="picker"' in two
    assert two.count('class="deck"') == 2


def test_cook_page_handles_missing_method():
    from export_static import build_cook_page
    page = build_cook_page([dict(RECIPE, steps=[])])
    assert "No method saved" in page


def test_cook_page_with_nothing_planned():
    from export_static import build_cook_page
    assert "Nothing planned" in build_cook_page([])


def test_cook_page_escapes_recipe_content():
    from export_static import build_cook_page
    page = build_cook_page([dict(RECIPE, name='<img src=x onerror=alert(1)>',
                                 steps=["<script>bad()</script>"])])
    assert "<img src=x" not in page
    assert "<script>bad()</script>" not in page
    assert "&lt;script&gt;" in page


def test_cook_page_is_self_contained():
    from export_static import build_cook_page
    page = build_cook_page([RECIPE])
    for pattern in ['src="http', 'href="http', "cdn."]:
        assert pattern not in page


def test_write_site_emits_cook_page(tmp_path):
    from export_static import write_site
    write_site([line("Potatoes")], ["Korma Salmon"], out_dir=str(tmp_path), recipes=[RECIPE])
    cook = os.path.join(str(tmp_path), "cook.html")
    assert os.path.exists(cook)
    with open(cook, encoding="utf-8") as fh:
        assert "Korma Salmon" in fh.read()


def test_service_worker_caches_the_cook_page(tmp_path):
    from export_static import write_site
    write_site([line("Potatoes")], out_dir=str(tmp_path), recipes=[RECIPE])
    with open(os.path.join(str(tmp_path), "sw.js"), encoding="utf-8") as fh:
        assert "./cook.html" in fh.read()


def test_shopping_page_links_to_cook_mode():
    from export_static import build_page
    assert './cook.html' in build_page([line("Potatoes")])
