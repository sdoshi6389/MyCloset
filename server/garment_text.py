"""Deciding whether a scrap of text off a clothing label is a brand or a size.

Both come from the same place -- GPT reading a care label, helped by OCR of the
tag -- and both used to be stored raw. Brand took whatever the tag said when GPT
found no brand, which is how "M/L", "G8", "1" and "Wcwtu 5oyhil BaWw" ended up
in the brand column. Size was never stored at all.
"""
import re

# Brands seen often enough to be worth spelling consistently. The key is the
# name with case and punctuation thrown away, so UNIQLO, Uniqlo and uniqlo all
# land on one row in the closet instead of three.
KNOWN_BRANDS = {
    "hm": "H&M", "handm": "H&M",
    "uniqlo": "Uniqlo", "zara": "Zara", "nike": "Nike", "adidas": "Adidas",
    "puma": "Puma", "reebok": "Reebok", "underarmour": "Under Armour",
    "newbalance": "New Balance", "converse": "Converse", "vans": "Vans",
    "levis": "Levi's", "wrangler": "Wrangler", "lee": "Lee",
    "gap": "Gap", "oldnavy": "Old Navy", "bananarepublic": "Banana Republic",
    "jcrew": "J.Crew", "abercrombiefitch": "Abercrombie & Fitch",
    "abercrombie": "Abercrombie & Fitch", "hollister": "Hollister",
    "americaneagle": "American Eagle", "aeropostale": "Aeropostale",
    "urbanoutfitters": "Urban Outfitters", "cottonon": "Cotton On",
    "primark": "Primark", "topman": "Topman", "asos": "ASOS",
    "boohoo": "boohoo", "boohooman": "boohooMAN", "prettylittlething": "PrettyLittleThing",
    "shein": "SHEIN", "romwe": "ROMWE", "forever21": "Forever 21",
    "gymshark": "Gymshark", "alphalete": "Alphalete", "lululemon": "lululemon",
    "champion": "Champion", "gildan": "Gildan", "fruitoftheloom": "Fruit of the Loom",
    "hanes": "Hanes", "carhartt": "Carhartt", "dickies": "Dickies",
    "patagonia": "Patagonia", "northface": "The North Face",
    "thenorthface": "The North Face", "columbia": "Columbia",
    "tommyhilfiger": "Tommy Hilfiger", "calvinklein": "Calvin Klein",
    "ralphlauren": "Ralph Lauren", "poloralphlauren": "Polo Ralph Lauren",
    "lacoste": "Lacoste", "nautica": "Nautica", "kennethcole": "Kenneth Cole",
    "guess": "GUESS", "diesel": "Diesel", "superdry": "Superdry",
    "jackjones": "Jack & Jones", "mango": "MANGO", "bershka": "Bershka",
    "pullbear": "Pull&Bear", "stradivarius": "Stradivarius",
    "massimodutti": "Massimo Dutti", "cos": "COS", "arket": "ARKET",
    "goodfellow": "Goodfellow & Co", "goodfellowco": "Goodfellow & Co",
    "mossimo": "Mossimo", "coofandy": "COOFANDY", "infantry": "INFANTRY",
    "disney": "Disney", "supreme": "Supreme", "stussy": "Stüssy",
    "carharttwip": "Carhartt WIP", "muji": "MUJI", "everlane": "Everlane",
}

# Words that turn up on labels but name no one.
NOT_A_BRAND = {
    "unknown", "none", "null", "na", "n/a", "brand", "nobrand", "generic",
    "man", "men", "mens", "woman", "women", "womens", "unisex", "kids",
    "comfort", "comfirt", "cotton", "polyester", "cottonblend", "size",
    "madeinchina", "madein", "regularfit", "slimfit", "relaxedfit",
    "machinewash", "care", "wash", "new", "original", "classic", "premium",
    "quality", "authentic", "collection", "design", "designed", "label",
}

# What a size looks like, so it is never mistaken for a brand.
_SIZE_WORD = re.compile(
    r"^(xx?x?s|s|m|l|xx?x?l|[2-6]x?l|o/?s|one ?size|free ?size|"
    r"s/m|m/l|l/xl|xs/s|xl/xxl|"
    # Two digits at least: a lone "1" or "9" off a garbled care label is noise,
    # not a size, and it was being stored as one.
    r"\d{2}(\.5)?|\d{2}\s*[xw]\s*\d{2}|\d{2}w(\s*\d{2}l)?)$",
    re.I)

_SIZE_WORDS = {
    "xs": "XS", "extrasmall": "XS", "xxs": "XXS",
    "s": "S", "small": "S", "m": "M", "medium": "M", "med": "M",
    "l": "L", "large": "L", "xl": "XL", "extralarge": "XL",
    "xxl": "XXL", "2xl": "XXL", "xxxl": "XXXL", "3xl": "XXXL",
    "4xl": "4XL", "os": "One Size", "onesize": "One Size",
    "freesize": "One Size", "sm": "S/M", "ml": "M/L", "lxl": "L/XL",
}

_VOWELS = set("aeiouy")


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def clean_brand(raw) -> str | None:
    """A display-ready brand, or None when the text does not name one.

    Conservative on purpose: an obscure brand that cannot be told apart from
    OCR noise is kept, because dropping a real one is the worse mistake and the
    user can edit it. Only the clear cases are rejected.
    """
    if not raw:
        return None
    text = re.sub(r"\s+", " ", str(raw)).strip(" \t\n.,:;-_|/\\\"'")
    if not text:
        return None

    key = _key(text)
    if not key:
        return None
    if key in KNOWN_BRANDS:
        return KNOWN_BRANDS[key]
    if key in NOT_A_BRAND or _SIZE_WORD.match(text):
        return None
    if len(key) < 3:                      # "BU", "VM", "1", "9"
        return None
    if key.isdigit():
        return None
    # A short mix of letters and digits is a label code, not a name: "G8", "e1 &8".
    if len(key) <= 6 and any(c.isdigit() for c in key) and any(c.isalpha() for c in key):
        return None
    if not (_VOWELS & set(key)):          # unpronounceable, so misread
        return None
    # A word with a digit buried inside it is OCR tripping over a glyph --
    # "Wcwtu 5oyhil BaWw". A bare number in a name ("7 For All Mankind") is
    # fine, so only mixed tokens are rejected.
    for token in re.split(r"[\s&/-]+", text):
        t = re.sub(r"[^A-Za-z0-9]", "", token)
        if len(t) > 1 and any(c.isdigit() for c in t) and any(c.isalpha() for c in t):
            return None

    # Leave a name that already carries its own capitalisation alone; title-case
    # the ones that arrive shouting.
    if text.isupper() and len(text) > 4:
        return text.title()
    if text.islower():
        return text.title()
    return text


def normalise_size(raw) -> str | None:
    """A tidy size label, or None. Keeps numeric and waist sizes as written."""
    if not raw:
        return None
    text = re.sub(r"\s+", " ", str(raw)).strip(" \t\n.,:;-_|")
    if not text:
        return None
    key = _key(text)
    if not key or key in ("unknown", "none", "na"):
        return None
    if key in _SIZE_WORDS:
        return _SIZE_WORDS[key]
    if _SIZE_WORD.match(text):
        return text.upper()
    return None
