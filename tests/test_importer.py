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
    assert steps[0]["text"] == "Preheat to 220°C."
    assert "<" not in "".join(s["text"] for s in steps)


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


# --- step photos, nutrition, allergens, utensils -----------------------------

RICH = {
    "props": {"pageProps": {"ssrPayload": {"recipe": {
        "name": "Rich Recipe",
        "totalTime": "PT30M",
        "imagePath": "/image/main-abc.jpg",
        "ingredients": [{"id": "a", "name": "Potatoes", "shipped": True}],
        "yields": [{"yields": 2, "ingredients": [
            {"id": "a", "amount": 450, "unit": "grams"}]}],
        "steps": [
            {"index": 1, "instructions": "<p>Chop things.</p>",
             "images": [{"path": "/xyz/step-1.jpg", "caption": "Chip, Chip, Hooray"}]},
            {"index": 2, "instructions": "<p>Cook things.</p>", "images": []},
        ],
        "nutrition": [
            {"name": "Energy (kcal)", "amount": 750, "unit": "kcal"},
            {"name": "Protein", "amount": 42.5, "unit": "g"},
            {"name": "Broken", "amount": None, "unit": "g"},
        ],
        "allergens": [{"name": "Fish"}, {"name": "Mustard"}, {"name": "Fish"}],
        "utensils": [{"name": "Baking Tray"}, {"name": "Garlic Press"}],
    }}}}
}


def test_step_photos_and_captions_extracted():
    r = hellofresh.parse(page(RICH))
    assert r["instructions"][0]["caption"] == "Chip, Chip, Hooray"
    assert "step-1.jpg" in r["instructions"][0]["image_url"]
    assert r["instructions"][1]["image_url"] is None


def test_step_image_url_is_a_sized_cdn_url():
    url = hellofresh.step_image_url("/xyz/step-1.jpg", width=600)
    assert url.startswith("https://media.hellofresh.com/w_600,")
    assert url.endswith("/hellofresh_s3/xyz/step-1.jpg")


def test_step_image_url_passes_through_absolute_urls():
    assert hellofresh.step_image_url("https://x/y.jpg") == "https://x/y.jpg"
    assert hellofresh.step_image_url(None) is None


def test_nutrition_extracted_and_bad_rows_dropped():
    r = hellofresh.parse(page(RICH))
    names = {n["name"]: n["amount"] for n in r["nutrition"]}
    assert names["Energy (kcal)"] == 750
    assert names["Protein"] == 42.5
    assert "Broken" not in names


def test_allergens_deduplicated_and_sorted():
    assert hellofresh.parse(page(RICH))["allergens"] == ["Fish", "Mustard"]


def test_utensils_extracted():
    assert hellofresh.parse(page(RICH))["utensils"] == ["Baking Tray", "Garlic Press"]


# --- bulk import ------------------------------------------------------------

LISTING = '''<html><body>
<a href="/recipes/korma-baked-salmon-6a05bfba204de353958f58b8">One</a>
<a href="/recipes/chorizo-penne-69bae02cd378378da7abd651">Two</a>
<a href="/recipes/korma-baked-salmon-6a05bfba204de353958f58b8">Dup</a>
<a href="/recipes/most-popular-recipes">Not a recipe</a>
<a href="/plans">Other</a>
</body></html>'''


def test_finds_recipe_links_on_a_listing_page():
    links = hellofresh.find_recipe_links(LISTING)
    assert len(links) == 2
    assert links[0].endswith("/recipes/korma-baked-salmon-6a05bfba204de353958f58b8")


def test_listing_links_are_deduplicated():
    assert len(hellofresh.find_recipe_links(LISTING)) == 2


def test_listing_ignores_non_recipe_links():
    joined = " ".join(hellofresh.find_recipe_links(LISTING))
    assert "most-popular-recipes" not in joined
    assert "/plans" not in joined


@pytest.mark.parametrize("url,is_recipe", [
    ("https://www.hellofresh.co.uk/recipes/thing-6a05bfba204de353958f58b8", True),
    ("https://www.hellofresh.co.uk/recipes/most-popular-recipes", False),
    ("https://www.hellofresh.co.uk/recipes/search?q=chicken", False),
])
def test_recipe_versus_listing_url(url, is_recipe):
    assert hellofresh._is_recipe_path(url) is is_recipe


@pytest.mark.parametrize("width,expected", [
    (200, "/w_200,"),
    (800, "/w_800,"),
])
def test_resize_rewrites_the_width(width, expected):
    url = "https://media.hellofresh.com/w_800,q_auto,f_auto/hellofresh_s3/image/x.jpg"
    out = hellofresh.resize_image_url(url, width)
    assert expected in out
    assert out.endswith("/hellofresh_s3/image/x.jpg")


def test_resize_only_touches_the_first_width():
    url = "https://media.hellofresh.com/w_800,q_auto/hellofresh_s3/w_800/x.jpg"
    assert hellofresh.resize_image_url(url, 200).count("/w_200,") == 1


def test_resize_handles_missing_url():
    assert hellofresh.resize_image_url(None, 200) is None
    assert hellofresh.resize_image_url("", 200) is None
