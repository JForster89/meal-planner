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


# --- supermarket aisles -----------------------------------------------------

# Roughly the order you walk a UK supermarket: fresh round the outside first,
# then the middle aisles. Grouping the shopping list this way saves doubling
# back, which alphabetical order guarantees you will do.
AISLE_ORDER = [
    "Fruit & Veg",
    "Meat & Fish",
    "Dairy & Eggs",
    "Bakery",
    "Frozen",
    "Cupboard",
    "Other",
]

AISLE_RULES = [
    ("Fruit & Veg", [
        r"\bpotato", r"\bonion", r"\bshallot", r"\bgarlic\b", r"\bcarrot",
        r"\bbroccoli", r"\bpepper(s)?\b", r"\bcourgette", r"\bmushroom",
        r"\btomato", r"\bcucumber", r"\blettuce", r"\bspinach", r"\bkale\b",
        r"\bcabbage", r"\bleek", r"\bcelery", r"\bcoriander", r"\bparsley",
        r"\bbasil\b", r"\bmint\b", r"\bthyme\b", r"\brosemary\b", r"\bchilli",
        r"\bginger\b", r"\blemon", r"\blime", r"\bapple", r"\bavocado",
        r"\bsweetcorn\b", r"\bpeas?\b", r"\bgreen beans?\b", r"\bsalad\b",
        r"\bsprouts?\b", r"\bparsnip", r"\bswede\b", r"\bsquash\b", r"\baubergine",
        r"\bspring onion", r"\bbeetroot\b", r"\bradish", r"\brocket\b",
    ]),
    ("Meat & Fish", [
        r"\bchicken\b", r"\bbeef\b", r"\bpork\b", r"\blamb\b", r"\bturkey\b",
        r"\bmince\b", r"\bsteak", r"\bbacon\b", r"\bchorizo", r"\bsausage",
        r"\bham\b", r"\bsalmon\b", r"\bcod\b", r"\bprawn", r"\btuna\b",
        r"\bhaddock\b", r"\bbasa\b", r"\bfillet", r"\bpancetta\b", r"\bsalami\b",
    ]),
    ("Dairy & Eggs", [
        r"\bmilk\b", r"\bbutter\b", r"\bcheese", r"\bcheddar\b", r"\bmozzarella\b",
        r"\bparmesan\b", r"\bcreme fraiche\b", r"\bcr[eè]me fra[iî]che\b",
        r"\bcream\b", r"\byoghurt\b", r"\byogurt\b", r"\begg(s)?\b",
        r"\bhalloumi\b", r"\bfeta\b", r"\bmascarpone\b", r"\bsoured cream\b",
    ]),
    ("Bakery", [
        r"\bbread\b", r"\bbun(s)?\b", r"\broll(s)?\b", r"\bbaguette\b",
        r"\bciabatta\b", r"\bbrioche\b", r"\bpitta\b", r"\btortilla",
        r"\bwrap(s)?\b", r"\bnaan\b", r"\bpanko\b", r"\bbreadcrumb",
    ]),
    ("Frozen", [
        r"\bfrozen\b", r"\bice cream\b", r"\bpeas \(frozen\)",
    ]),
    ("Cupboard", [
        r"\bpasta\b", r"\bpenne\b", r"\bspaghetti\b", r"\bfusilli\b",
        r"\bnoodle", r"\brice\b", r"\bcouscous\b", r"\bquinoa\b", r"\blentil",
        r"\bflour\b", r"\bsugar\b", r"\bsalt\b", r"\bpepper\b", r"\boil\b",
        r"\bvinegar\b", r"\bstock\b", r"\bpassata\b", r"\bchopped tomatoes\b",
        r"\bbean(s)?\b", r"\bchickpea", r"\bcoconut milk\b", r"\bhoney\b",
        r"\bmustard\b", r"\bketchup\b", r"\bmayonnaise\b", r"\bchutney\b",
        r"\bcurry\b", r"\bspice", r"\bpaprika\b", r"\bcumin\b", r"\bturmeric\b",
        r"\bcinnamon\b", r"\bseed(s)?\b", r"\bnut(s)?\b", r"\bstock powder\b",
        r"\bsauce\b", r"\bpaste\b", r"\bwater\b",
    ]),
]


# Checked before everything else, because the plain ingredient word would
# otherwise win: "Dried Thyme" is a jar in the cupboard, not a fresh herb, and
# "Finely Chopped Tomatoes" is a tin, not produce.
AISLE_OVERRIDES = [
    ("Frozen", [r"\bfrozen\b"]),
    ("Cupboard", [
        r"\bdried\b", r"\btinned\b", r"\bcanned\b", r"\bchopped tomatoes\b",
        r"\bplum tomatoes\b", r"\bpassata\b", r"\bsun-?dried\b", r"\bpickled\b",
        r"\bground\b", r"\bflakes?\b", r"\bpuree\b", r"\bpurée\b",
    ]),
]


def detect_aisle(name):
    """Which part of the shop an ingredient lives in.

    Order matters. Flavourings resolve first ("Chicken Stock Powder" is a
    cupboard item, not meat), then preserved forms ("Dried Thyme"), and only
    then the plain ingredient word.
    """
    lowered = (name or "").strip().lower()
    if not lowered:
        return "Other"

    if is_flavouring(lowered):
        return "Cupboard"

    for aisle, patterns in AISLE_OVERRIDES:
        for pattern in patterns:
            if re.search(pattern, lowered):
                return aisle

    for aisle, patterns in AISLE_RULES:
        for pattern in patterns:
            if re.search(pattern, lowered):
                return aisle
    return "Other"


def aisle_sort_key(aisle):
    try:
        return AISLE_ORDER.index(aisle)
    except ValueError:
        return len(AISLE_ORDER)
