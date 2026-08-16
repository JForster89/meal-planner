"""Parser tests against a trimmed copy of HelloFresh's real page structure."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hellofresh

NEXT_DATA = {
    "props": {"pageProps": {"ssrPayload": {"recipe": {
        "name": "Korma Baked Salmon and Chips",
        "headline": "with Garlic Butter Peas",
        "totalTime": "PT25M",
        "prepTime": "PT35M",
        "ingredients": [
            {"id": "a", "name": "Potatoes", "shipped": True},
            {"id": "b", "name": "Garlic Clove", "shipped": True},
            {"id": "c", "name": "Butter", "shipped": False},
        ],
        "yields": [
            {"yields": 2, "ingredients": [
                {"id": "a", "amount": 450, "unit": "grams"},
                {"id": "b", "amount": 1, "unit": "unit(s)"},
                {"id": "c", "amount": 20, "unit": "grams"},
            ]},
            {"yields": 4, "ingredients": [
                {"id": "a", "amount": 900, "unit": "grams"},
                {"id": "b", "amount": 2, "unit": "unit(s)"},
                {"id": "c", "amount": 40, "unit": "grams"},
            ]},
        ],
        "steps": [
            {"index": 1, "instructions": "<p>Preheat to <strong>220&deg;C</strong>.</p>"},
            {"index": 2, "instructions": "<p>Chop the potatoes.</p>"},
        ],
    }}}}
}

LD_JSON = {
    "@type": "Recipe",
    "name": "Fallback Recipe",
    "recipeYield": 2,
    "totalTime": "PT30M",
    "recipeIngredient": ["450 grams Potatoes", "1 unit(s) Garlic Clove"],
    "recipeInstructions": [{"text": "Cook it."}],
}


def page(next_data=None, ld=None):
    html = "<html><body>"
    if ld is not None:
        html += f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    if next_data is not None:
        html += (
            '<script id="__NEXT_DATA__" type="application/json">'
            f"{json.dumps(next_data)}</script>"
        )
    return html + "</body></html>"


def test_prefers_next_data_and_keeps_every_yield():
    r = hellofresh.parse(page(NEXT_DATA, LD_JSON))
    assert r["source"] == "next_data"
    assert sorted(r["yields"]) == [2, 4]
    assert r["name"] == "Korma Baked Salmon and Chips with Garlic Butter Peas"


def test_quantities_stay_structured():
    r = hellofresh.parse(page(NEXT_DATA))
    potatoes = r["yields"][2][0]
    assert potatoes["quantity"] == 450
    assert potatoes["unit"] == "grams"
    assert potatoes["name"] == "Potatoes"


def test_unshipped_items_marked_as_pantry():
    r = hellofresh.parse(page(NEXT_DATA))
    by_name = {i["name"]: i for i in r["yields"][2]}
    assert by_name["Butter"]["is_pantry"] is True
    assert by_name["Potatoes"]["is_pantry"] is False


def test_non_linear_yields_preserved_not_multiplied():
    """1 garlic clove at 2 portions becomes 2 at 4 portions, not 2x450g of it."""
    r = hellofresh.parse(page(NEXT_DATA))
    assert r["yields"][2][1]["quantity"] == 1
    assert r["yields"][4][1]["quantity"] == 2


def test_takes_longer_of_the_two_times():
    assert hellofresh.parse(page(NEXT_DATA))["cooking_time_mins"] == 35


def test_instructions_stripped_of_markup():
    steps = hellofresh.parse(page(NEXT_DATA))["instructions"]
    assert steps[0] == "Preheat to 220°C."
    assert "<" not in "".join(steps)


def test_falls_back_to_ld_json():
    r = hellofresh.parse(page(None, LD_JSON))
    assert r["source"] == "ld_json"
    assert r["yields"][2][0]["quantity"] == 450.0
    assert r["yields"][2][0]["unit"] == "grams"


def test_unparseable_page_raises():
    with pytest.raises(hellofresh.ImportError_):
        hellofresh.parse("<html><body>nothing here</body></html>")


def test_rejects_non_hellofresh_urls():
    with pytest.raises(hellofresh.ImportError_, match="HelloFresh recipe URL"):
        hellofresh.import_recipe("https://bbcgoodfood.com/recipes/thing")


@pytest.mark.parametrize("url,expected", [
    ("https://www.hellofresh.co.uk/recipes/thing-abc123", True),
    ("http://hellofresh.co.uk/recipes/thing", True),
    ("https://www.hellofresh.de/recipes/thing", True),
    ("https://www.hellofresh.co.uk/plans", False),
    ("https://example.com/recipes/thing", False),
])
def test_url_recognition(url, expected):
    assert hellofresh.is_hellofresh_url(url) is expected
