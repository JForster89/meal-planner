"""Grouping recipes by what's actually in them.

HelloFresh publishes tags and a cuisine, but nothing that says "this is a
chicken dish". That has to be inferred from the ingredients, which is mostly
easy and occasionally a trap: a chorizo pasta listing "Chicken Stock Powder" is
a pork dish, not a chicken one.
"""

import re

# Named meats and fish, checked before anything generic. Patterns allow a
# trailing plural: "King Prawns" and "Salmon Fillets" must both match.
PROTEIN_RULES = [
    ("Pork",    [r"\bpork\b", r"\bbacon\b", r"\bchorizos?\b", r"\bsausages?\b",
                 r"\bham\b", r"\bpancetta\b", r"\bgammon\b", r"\bsalami\b",
                 r"\bprosciutto\b"]),
    ("Beef",    [r"\bbeef\b", r"\bsteaks?\b", r"\bbrisket\b", r"\bmeatballs?\b"]),
    ("Chicken", [r"\bchickens?\b", r"\bpoultry\b"]),
    ("Turkey",  [r"\bturkeys?\b"]),
    ("Lamb",    [r"\blamb\b"]),
    ("Fish",    [r"\bsalmon\b", r"\bcod\b", r"\btunas?\b", r"\bhaddock\b",
                 r"\bbasa\b", r"\bpollock\b", r"\bsea ?bass\b",
                 r"\btrout\b", r"\bmackerel\b", r"\bfish\b"]),
    ("Seafood", [r"\bprawns?\b", r"\bshrimps?\b", r"\bsquid\b",
                 r"\bmussels?\b", r"\bscallops?\b", r"\bcrabs?\b"]),
]

# Words that imply a meat but don't say which. Only consulted when no named
# meat matched, so "Pork Mince" is pork and "Lamb Mince" is lamb - putting a
# bare "mince" in the Beef rule made both of those beef.
GENERIC_RULES = [
    ("Beef", [r"\bmince\b", r"\bminced meat\b"]),
]

# An ingredient whose name contains one of these is a flavouring, not the
# protein of the dish. "Chicken Stock Powder" must not make a dish chicken.
FLAVOURING_HINTS = [
    "stock", "powder", "bouillon", "cube", "gravy", "seasoning", "rub",
    "spice", "paste", "sauce", "marinade", "broth", "granules",
]

VEGGIE = "Veggie"

# Tags HelloFresh marks displayLabel=false are internal (SEO, taxonomy codes).
# A couple of them are still useful to a human, so allow them explicitly.
USEFUL_HIDDEN_TAGS = {"quick-and-easy", "under-30-minutes", "one-pot", "veggie", "vegan"}

# Never surface these, whatever their flag says.
JUNK_TAG_SLUGS = {"seo", "classic-plates", "clonedfrom"}


def is_flavouring(name):
    lowered = (name or "").lower()
    return any(hint in lowered for hint in FLAVOURING_HINTS)


def detect_protein(ingredient_names):
    """Best guess at the protein, ignoring stocks and seasonings."""
    real = [n for n in ingredient_names if n and not is_flavouring(n)]
    haystack = " ; ".join(real).lower()

    for rules in (PROTEIN_RULES, GENERIC_RULES):
        for label, patterns in rules:
            for pattern in patterns:
                if re.search(pattern, haystack):
                    return label
    return VEGGIE


def clean_tags(raw_tags):
    """Pick the tags worth showing from HelloFresh's mixed bag."""
    out = []
    for tag in raw_tags or []:
        name = (tag.get("name") or "").strip()
        slug = (tag.get("slug") or "").strip().lower()
        if not name or slug in JUNK_TAG_SLUGS:
            continue
        if tag.get("displayLabel") or slug in USEFUL_HIDDEN_TAGS:
            if name not in out:
                out.append(name)
    return out


def difficulty_label(value):
    return {1: "Easy", 2: "Medium", 3: "Hard"}.get(value)
