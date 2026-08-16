"""Import a recipe from a public HelloFresh recipe page.

The page ships a Next.js `__NEXT_DATA__` blob containing the recipe with
quantity and unit already separated, a `shipped` flag marking store-cupboard
items, and a published quantity table per portion count. That is a far better
source than the JSON-LD block (which flattens everything into strings and drops
the pantry distinction), so we prefer it and fall back to JSON-LD only if the
page layout changes.
"""

import html as html_mod
import json
import re

import requests

import taxonomy

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
TIMEOUT = 20

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>', re.S
)
_LD_JSON = re.compile(
    r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S
)
_TAGS = re.compile(r"<[^>]+>")
_ISO_DURATION = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?")
# "450 grams Potatoes" -> qty / unit / name
_LD_INGREDIENT = re.compile(r"^\s*([\d.,/]+)?\s*(\S+)?\s+(.+?)\s*$")


class ImportError_(Exception):
    """Raised when a URL cannot be turned into a recipe."""


MEDIA_BASE = "https://media.hellofresh.com"


def step_image_url(path, width=600):
    """Turn a stored image path into a CDN URL at a sensible size.

    Their media host takes transform parameters in the path, so asking for a
    width keeps a step photo around 30 KB rather than full resolution.
    """
    if not path:
        return None
    path = path.strip()
    if path.startswith("http"):
        return path
    return (
        f"{MEDIA_BASE}/w_{width},q_auto,f_auto,c_limit,fl_lossy"
        f"/hellofresh_s3{path if path.startswith('/') else '/' + path}"
    )


_WIDTH_PARAM = re.compile(r"/w_\d+,")


def resize_image_url(url, width):
    """Ask their CDN for a different size of an image we already have a URL for.

    A list thumbnail doesn't need the 800px version, and the transform lives
    in the path, so this is a rewrite rather than another lookup.
    """
    if not url:
        return None
    return _WIDTH_PARAM.sub(f"/w_{int(width)},", url, count=1)


def is_hellofresh_url(url):
    return bool(re.match(r"^https?://(www\.)?hellofresh\.[a-z.]+/recipes/", url.strip(), re.I))


def _minutes(iso):
    if not iso:
        return None
    m = _ISO_DURATION.match(iso)
    if not m:
        return None
    hours, mins = m.group(1), m.group(2)
    total = (int(hours) * 60 if hours else 0) + (int(mins) if mins else 0)
    return total or None


def _clean_text(raw):
    """Strip tags and decode entities from a HelloFresh instruction step."""
    if not raw:
        return ""
    text = _TAGS.sub("", raw)
    text = html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch(url):
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    if resp.status_code == 404:
        raise ImportError_("That recipe page doesn't exist (404). Check the URL.")
    if resp.status_code != 200:
        raise ImportError_(f"HelloFresh returned HTTP {resp.status_code}.")
    resp.encoding = resp.encoding or "utf-8"
    return resp.text


def _parse_next_data(html):
    m = _NEXT_DATA.search(html)
    if not m:
        return None
    try:
        blob = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None

    recipe = (
        blob.get("props", {})
        .get("pageProps", {})
        .get("ssrPayload", {})
        .get("recipe")
    )
    if not recipe or not recipe.get("ingredients"):
        return None

    name = (recipe.get("name") or "").strip()
    headline = (recipe.get("headline") or "").strip()
    if headline:
        name = f"{name} {headline}".strip()

    # The page's own totalTime/prepTime are sometimes swapped; take the larger
    # so we never understate how long a meal takes.
    times = [t for t in (_minutes(recipe.get("totalTime")), _minutes(recipe.get("prepTime"))) if t]
    cooking_time = max(times) if times else None

    by_id = {i.get("id"): i for i in recipe.get("ingredients", []) if i.get("id")}

    yields = {}
    for entry in recipe.get("yields", []):
        portions = entry.get("yields")
        if not portions:
            continue
        items = []
        for pos, line in enumerate(entry.get("ingredients", [])):
            info = by_id.get(line.get("id"))
            if not info or not info.get("name"):
                continue
            items.append(
                {
                    "quantity": line.get("amount"),
                    "unit": line.get("unit") or "",
                    "name": info["name"].strip(),
                    # `shipped: false` == "not included in your delivery",
                    # i.e. a store-cupboard item you probably already own.
                    "is_pantry": not info.get("shipped", True),
                    "position": pos,
                }
            )
        if items:
            yields[portions] = items

    if not yields:
        return None

    steps = []
    for raw in sorted(recipe.get("steps", []), key=lambda s: s.get("index", 0)):
        text = _clean_text(raw.get("instructions"))
        if not text:
            continue
        images = raw.get("images") or []
        first = images[0] if images else {}
        steps.append({
            "text": text,
            "image_url": step_image_url(first.get("path")),
            "caption": (first.get("caption") or "").strip() or None,
        })

    ingredient_names = [
        i.get("name", "") for i in recipe.get("ingredients", []) if i.get("name")
    ]

    nutrition = [
        {"name": n.get("name"), "amount": n.get("amount"), "unit": n.get("unit")}
        for n in recipe.get("nutrition", []) or []
        if n.get("name") and n.get("amount") is not None
    ]

    allergens = sorted({
        a["name"].strip()
        for a in (recipe.get("allergens") or [])
        if isinstance(a, dict) and a.get("name")
    })

    utensils = [
        u["name"].strip()
        for u in (recipe.get("utensils") or [])
        if isinstance(u, dict) and u.get("name")
    ]

    return {
        "name": name or "Untitled recipe",
        "cooking_time_mins": cooking_time,
        "servings": min(yields),
        "yields": yields,
        "instructions": steps,
        "nutrition": nutrition,
        "allergens": allergens,
        "utensils": utensils,
        "image_url": step_image_url(recipe.get("imagePath"), width=800),
        "tags": taxonomy.clean_tags(recipe.get("tags")),
        "cuisines": [
            c["name"].strip()
            for c in recipe.get("cuisines", []) or []
            if c.get("name")
        ],
        "protein": taxonomy.detect_protein(ingredient_names),
        "difficulty": recipe.get("difficulty"),
        "source": "next_data",
    }


def _parse_ld_json(html):
    """Fallback: schema.org Recipe block. Loses the pantry split."""
    for block in _LD_JSON.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict) or item.get("@type") != "Recipe":
                continue

            try:
                portions = int(item.get("recipeYield") or 2)
            except (TypeError, ValueError):
                portions = 2

            items = []
            for pos, raw in enumerate(item.get("recipeIngredient", [])):
                m = _LD_INGREDIENT.match(raw.strip())
                if not m:
                    items.append(
                        {"quantity": None, "unit": "", "name": raw.strip(),
                         "is_pantry": False, "position": pos}
                    )
                    continue
                qty_raw, unit, name = m.groups()
                try:
                    qty = float(qty_raw.replace(",", ".")) if qty_raw else None
                except ValueError:
                    qty = None
                items.append(
                    {"quantity": qty, "unit": (unit or "").strip(),
                     "name": (name or "").strip(), "is_pantry": False, "position": pos}
                )

            if not items:
                continue

            instructions = []
            for step in item.get("recipeInstructions", []):
                text = step.get("text") if isinstance(step, dict) else step
                cleaned = _clean_text(text)
                if cleaned:
                    instructions.append(cleaned)

            category = item.get("recipeCategory") or []
            cuisine = item.get("recipeCuisine") or []
            return {
                "name": (item.get("name") or "Untitled recipe").strip(),
                "cooking_time_mins": _minutes(item.get("totalTime")),
                "servings": portions,
                "yields": {portions: items},
                "instructions": [
                    {"text": t, "image_url": None, "caption": None}
                    for t in instructions
                ],
                "nutrition": [],
                "allergens": [],
                "utensils": [],
                "image_url": None,
                "tags": [category] if isinstance(category, str) else list(category),
                "cuisines": [cuisine] if isinstance(cuisine, str) else list(cuisine),
                "protein": taxonomy.detect_protein([i["name"] for i in items]),
                "difficulty": None,
                "source": "ld_json",
            }
    return None


def parse(html):
    recipe = _parse_next_data(html) or _parse_ld_json(html)
    if not recipe:
        raise ImportError_(
            "Couldn't find recipe data on that page. HelloFresh may have changed "
            "their page layout — add the recipe manually for now."
        )
    return recipe


# Listing pages render their cards client-side, so the recipe URLs are not in
# href attributes - they sit in the embedded JSON as websiteUrl/canonicalLink.
# Match both, since plain links do appear on some pages.
_RECIPE_LINK = re.compile(
    r'href="(/recipes/[a-z0-9-]+-[0-9a-f]{12,})"', re.I
)
_RECIPE_JSON_LINK = re.compile(
    r'"(?:websiteUrl|canonicalLink)":"(https?://[^"]*?/recipes/[a-z0-9-]+-[0-9a-f]{12,})"',
    re.I,
)


def is_listing_url(url):
    """A HelloFresh page that lists recipes rather than being one."""
    url = url.strip()
    if not re.match(r"^https?://(www\.)?hellofresh\.[a-z.]+/", url, re.I):
        return False
    return not _is_recipe_path(url)


def _is_recipe_path(url):
    """A recipe page ends in a long hex id; a listing page doesn't."""
    return bool(re.search(r"/recipes/[a-z0-9-]+-[0-9a-f]{12,}/?$", url.strip(), re.I))


def find_recipe_links(html_text, base="https://www.hellofresh.co.uk"):
    """Pull recipe URLs out of a category, search or collection page."""
    seen, out = set(), []

    def add(url):
        # Compare on path so an href and its JSON twin don't both count.
        key = re.sub(r"^https?://[^/]+", "", url).rstrip("/")
        if key not in seen:
            seen.add(key)
            out.append(url)

    for path in _RECIPE_LINK.findall(html_text):
        add(base.rstrip("/") + path)
    for url in _RECIPE_JSON_LINK.findall(html_text):
        add(url)

    return out


def list_recipes_on(url):
    """Fetch a listing page and return the recipe URLs it links to."""
    url = url.strip()
    if not re.match(r"^https?://(www\.)?hellofresh\.[a-z.]+/", url, re.I):
        raise ImportError_(
            "That doesn't look like a HelloFresh page. Try a URL starting "
            "https://www.hellofresh.co.uk/"
        )
    try:
        html_text = fetch(url)
    except requests.RequestException as exc:
        raise ImportError_(f"Couldn't reach HelloFresh: {exc}") from exc

    base = re.match(r"^(https?://[^/]+)", url).group(1)
    links = find_recipe_links(html_text, base)
    if not links:
        raise ImportError_(
            "No recipe links found on that page. Use a category or search page, "
            "for example hellofresh.co.uk/recipes/most-popular-recipes"
        )
    return links


def import_recipe(url):
    """Fetch and parse a HelloFresh recipe URL into a dict ready for saving."""
    url = url.strip()
    if not is_hellofresh_url(url):
        raise ImportError_(
            "That doesn't look like a HelloFresh recipe URL. It should start "
            "with https://www.hellofresh.co.uk/recipes/"
        )
    try:
        html = fetch(url)
    except requests.RequestException as exc:
        raise ImportError_(f"Couldn't reach HelloFresh: {exc}") from exc

    recipe = parse(html)
    recipe["source_url"] = url
    return recipe
