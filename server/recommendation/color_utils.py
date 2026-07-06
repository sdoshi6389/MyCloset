"""Color harmony scoring for outfit recommendations."""

# Map color keywords to a color family
_FAMILIES = {
    "neutral":   ["black","white","gray","grey","cream","beige","ivory","off-white","charcoal","nude","ecru","off white","light gray","dark gray","heather","stone","oatmeal"],
    "navy":      ["navy","navy blue","dark blue","midnight blue","midnight"],
    "blue":      ["blue","cobalt","royal blue","cornflower","periwinkle","baby blue","sky blue","denim","slate blue","slate","indigo","powder blue","light blue"],
    "earth":     ["brown","tan","camel","khaki","sand","taupe","rust","terracotta","mocha","coffee","chocolate","walnut","sienna","clay","warm brown","light brown","dark brown"],
    "olive":     ["olive","army green","military green","dark olive","dark khaki","moss"],
    "green":     ["green","sage","mint","emerald","teal","seafoam","kelly green","lime","hunter green","forest green","forest","light green","bright green"],
    "warm":      ["red","orange","yellow","coral","amber","gold","mustard","ochre","saffron","lemon","neon yellow"],
    "burgundy":  ["burgundy","wine","maroon","oxblood","crimson","bordeaux","brick red"],
    "pink":      ["pink","blush","rose","salmon","peach","dusty rose","mauve","hot pink","light pink"],
    "purple":    ["purple","lavender","lilac","plum","violet","grape","periwinkle purple"],
}

# Build reverse map: keyword → family
_COLOR_TO_FAMILY: dict[str, str] = {}
for family, keywords in _FAMILIES.items():
    for kw in keywords:
        _COLOR_TO_FAMILY[kw] = family

# Compatibility scores between family pairs (symmetric)
# 1.0 = perfect, 0.5 = neutral, 0.3 = clash
_COMPAT: dict[tuple[str,str], float] = {
    ("neutral",  "neutral"):  1.00,
    ("neutral",  "navy"):     1.00,
    ("neutral",  "blue"):     0.95,
    ("neutral",  "earth"):    1.00,
    ("neutral",  "olive"):    0.95,
    ("neutral",  "green"):    0.90,
    ("neutral",  "warm"):     0.90,
    ("neutral",  "burgundy"): 0.95,
    ("neutral",  "pink"):     0.90,
    ("neutral",  "purple"):   0.85,
    ("navy",     "earth"):    0.90,
    ("navy",     "olive"):    0.85,
    ("navy",     "burgundy"): 0.80,
    ("navy",     "pink"):     0.75,
    ("navy",     "blue"):     0.70,
    ("navy",     "green"):    0.75,
    ("navy",     "warm"):     0.55,
    ("navy",     "purple"):   0.70,
    ("earth",    "earth"):    0.90,
    ("earth",    "olive"):    0.90,
    ("earth",    "warm"):     0.85,
    ("earth",    "burgundy"): 0.85,
    ("earth",    "green"):    0.80,
    ("earth",    "pink"):     0.70,
    ("earth",    "blue"):     0.75,
    ("olive",    "earth"):    0.90,
    ("olive",    "warm"):     0.75,
    ("olive",    "burgundy"): 0.80,
    ("olive",    "green"):    0.75,
    ("olive",    "blue"):     0.70,
    ("blue",     "earth"):    0.75,
    ("blue",     "burgundy"): 0.70,
    ("blue",     "green"):    0.65,
    ("warm",     "burgundy"): 0.60,
    ("warm",     "warm"):     0.55,
    ("green",    "navy"):     0.75,
    ("green",    "earth"):    0.80,
    ("burgundy", "navy"):     0.80,
    ("burgundy", "earth"):    0.85,
    ("pink",     "navy"):     0.75,
    ("pink",     "earth"):    0.70,
    ("pink",     "purple"):   0.75,
    ("purple",   "navy"):     0.70,
    ("purple",   "earth"):    0.65,
}

def _get_family(color: str) -> str | None:
    if not color:
        return None
    c = color.lower().strip()
    if c in _COLOR_TO_FAMILY:
        return _COLOR_TO_FAMILY[c]
    # Substring match
    for kw, family in _COLOR_TO_FAMILY.items():
        if kw in c or c in kw:
            return family
    return None

def color_harmony_score(color_a: str, color_b: str) -> float:
    """Return 0.0–1.0 compatibility between two color strings."""
    fa = _get_family(color_a)
    fb = _get_family(color_b)
    if fa is None or fb is None:
        return 0.65  # unknown → neutral guess
    if fa == fb:
        return 0.90
    key = (fa, fb) if (fa, fb) in _COMPAT else (fb, fa)
    return _COMPAT.get(key, 0.55)
