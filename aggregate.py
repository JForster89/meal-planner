"""Unit normalisation and cross-recipe ingredient aggregation.

The shopping list is only useful if "450 grams Potatoes" from one recipe and
"0.5 kg potatoes" from another collapse into a single "950 g potatoes" line.
That needs two things: a canonical unit (within a measurement dimension) and a
canonical ingredient name.
"""

import math
import re
from collections import OrderedDict

# Units you buy as whole things. Scaling a recipe can produce "1.5 can", which
# is not something a shop will sell you, so these round up. Weights, volumes
# and spoons keep their decimals - 675 g and 1.5 tbsp are both usable.
DISCRETE_UNITS = {
    "", "clove", "can", "pack", "sachet", "bunch", "punnet",
    "jar", "bottle", "slice", "pinch", "handful",
}

# unit alias -> (canonical unit, multiplier to canonical)
UNIT_ALIASES = {
    # mass, canonical grams
    "g": ("g", 1.0), "gram": ("g", 1.0), "grams": ("g", 1.0),
    "gramme": ("g", 1.0), "grammes": ("g", 1.0),
    "kg": ("g", 1000.0), "kilo": ("g", 1000.0),
    "kilogram": ("g", 1000.0), "kilograms": ("g", 1000.0),
    # volume, canonical millilitres
    "ml": ("ml", 1.0), "millilitre": ("ml", 1.0), "millilitres": ("ml", 1.0),
    "cl": ("ml", 10.0),
    "l": ("ml", 1000.0), "litre": ("ml", 1000.0), "litres": ("ml", 1000.0),
    # spoons stay their own dimension; converting them to ml produces
    # unshoppable numbers like "17 ml mayonnaise".
    "tsp": ("tsp", 1.0), "teaspoon": ("tsp", 1.0), "teaspoons": ("tsp", 1.0),
    "tbsp": ("tbsp", 1.0), "tablespoon": ("tbsp", 1.0), "tablespoons": ("tbsp", 1.0),
    # discrete counts
    "unit": ("", 1.0), "units": ("", 1.0), "unit(s)": ("", 1.0),
    "piece": ("", 1.0), "pieces": ("", 1.0), "x": ("", 1.0),
    "clove": ("clove", 1.0), "cloves": ("clove", 1.0),
    "can": ("can", 1.0), "cans": ("can", 1.0),
    "tin": ("can", 1.0), "tins": ("can", 1.0),
    "pack": ("pack", 1.0), "packs": ("pack", 1.0), "packet": ("pack", 1.0),
    "sachet": ("sachet", 1.0), "sachets": ("sachet", 1.0),
    "bunch": ("bunch", 1.0), "bunches": ("bunch", 1.0),
    "punnet": ("punnet", 1.0), "punnets": ("punnet", 1.0),
    "jar": ("jar", 1.0), "jars": ("jar", 1.0),
    "bottle": ("bottle", 1.0), "bottles": ("bottle", 1.0),
    "slice": ("slice", 1.0), "slices": ("slice", 1.0),
    "pinch": ("pinch", 1.0), "pinches": ("pinch", 1.0),
    "handful": ("handful", 1.0), "handfuls": ("handful", 1.0),
}

# Ingredient-name aliases. Deliberately small: over-aggressive merging is worse
# than a duplicate line, because you notice a duplicate but not a silent merge.
NAME_ALIASES = {
    "garlic clove": "garlic",
    "garlic cloves": "garlic",
    "spring onions": "spring onion",
    "salmon fillets": "salmon fillet",
    "chicken breasts": "chicken breast",
    "chicken thighs": "chicken thigh",
    "potatoes": "potato",
    "tomatoes": "tomato",
    "onions": "onion",
    "carrots": "carrot",
    "peppers": "pepper",
    "courgettes": "courgette",
    "mushrooms": "mushroom",
    "eggs": "egg",
    "lemons": "lemon",
    "limes": "lime",
}

_PARENTHETICAL = re.compile(r"\s*\([^)]*\)")
_WHITESPACE = re.compile(r"\s+")


def normalise_unit(unit):
    """Return (canonical_unit, multiplier). Unknown units pass through as-is."""
    if not unit:
        return ("", 1.0)
    key = unit.strip().lower().rstrip(".")
    if key in UNIT_ALIASES:
        return UNIT_ALIASES[key]
    return (key, 1.0)


def normalise_name(name):
    """Lowercase, drop allergen parentheticals, collapse whitespace, de-alias."""
    if not name:
        return ""
    cleaned = _PARENTHETICAL.sub("", name)
    cleaned = _WHITESPACE.sub(" ", cleaned).strip().lower()
    cleaned = cleaned.strip(",.")
    return NAME_ALIASES.get(cleaned, cleaned)


def display_name(name):
    """Title-ish casing for output without mangling words like 'and'."""
    cleaned = _PARENTHETICAL.sub("", name or "").strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else ""


def format_quantity(qty, unit):
    """Render a summed quantity in the friendliest unit for that dimension."""
    if qty is None:
        return ""

    # You can't buy 1.5 cans. Published quantities are whole numbers already,
    # so this only ever bumps values that scaling made fractional.
    if unit in DISCRETE_UNITS:
        qty = math.ceil(qty - 1e-9)

    if unit == "g" and qty >= 1000:
        qty, unit = qty / 1000.0, "kg"
    elif unit == "ml" and qty >= 1000:
        qty, unit = qty / 1000.0, "l"

    if abs(qty - round(qty)) < 0.01:
        num = str(int(round(qty)))
    else:
        num = f"{qty:.2f}".rstrip("0").rstrip(".")

    return f"{num} {unit}".strip()


def aggregate(rows, include_pantry=False):
    """Merge ingredient rows into shopping lines.

    `rows` are dict-likes with: quantity, unit, name, is_pantry, recipe_name,
    and `multiplier` (portions wanted / recipe's base servings).

    Lines are keyed on (canonical name, canonical unit) so that different
    dimensions of the same ingredient stay on separate lines rather than being
    nonsensically summed.
    """
    merged = OrderedDict()

    for row in rows:
        if row["is_pantry"] and not include_pantry:
            continue

        canon_name = normalise_name(row["name"])
        if not canon_name:
            continue

        canon_unit, factor = normalise_unit(row["unit"])
        key = f"{canon_name}|{canon_unit}"

        qty = row["quantity"]
        scaled = qty * factor * row["multiplier"] if qty is not None else None

        if key not in merged:
            merged[key] = {
                "key": key,
                "name": display_name(row["name"]),
                "unit": canon_unit,
                "quantity": scaled,
                "is_pantry": bool(row["is_pantry"]),
                "aisle": row.get("aisle") or "Other",
                "recipes": [],
                "unquantified": qty is None,
            }
        else:
            line = merged[key]
            if scaled is None:
                line["unquantified"] = True
            elif line["quantity"] is None:
                line["quantity"] = scaled
            else:
                line["quantity"] += scaled

        if row["recipe_name"] not in merged[key]["recipes"]:
            merged[key]["recipes"].append(row["recipe_name"])

    for line in merged.values():
        line["display_quantity"] = format_quantity(line["quantity"], line["unit"])

    return sorted(merged.values(), key=lambda l: l["name"].lower())
