"""J.Crew scraper — Salesforce Commerce Cloud Shop API, exposed directly under
www.jcrew.com/browse/... (not proxied). Search hits are one-per-color-variant
("hit_type": "variation_group") and never inline a human-readable color name,
only a defaultColorCode (e.g. "EM0212"). The readable name lives on the
per-master-product detail endpoint's variation_attributes[id=="color"], so we
fetch that once per unique master product id and cache it.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from db_insert import insert_products, ensure_table

TABLE = "products_jcrew"
BASE  = "https://www.jcrew.com"
COUNT = 60

CATEGORIES = [
    "womens|categories|clothing|dresses-and-jumpsuits",
    "womens|categories|clothing|pants",
    "womens|categories|clothing|jeans",
    "womens|categories|clothing|shirts-and-tops",
    "womens|categories|clothing|swim",
    "womens|categories|clothing|tees-and-tanks",
    "womens|categories|clothing|sweaters",
    "womens|categories|clothing|shorts",
    "womens|categories|clothing|skirts",
    "womens|categories|clothing|blazers",
    "womens|categories|clothing|coats-and-jackets",
    "womens|categories|clothing|sweatshirts-and-sweatpants",
    "womens|categories|clothing|pajamas-and-intimates",
    "womens|categories|clothing|matching-sets",
    "womens|categories|clothing|suiting",
    "womens|categories|accessories|home",
    "womens|categories|accessories|pet-accessories",
    "womens|categories|accessories|straw-accessories",
    "womens|categories|accessories|silk-scarves",
    "womens|categories|accessories|bags",
    "womens|categories|accessories|belts",
    "womens|categories|accessories|jewelry",
    "womens|categories|accessories|hats",
    "womens|categories|accessories|bag-charms",
    "womens|categories|accessories|socks-and-tights",
    "womens|categories|accessories|hair",
    "womens|categories|accessories|sunglasses-and-chains",
    "womens|categories|accessories|phone-chains",
    "womens|categories|accessories|suede-accessories",
    "womens|categories|accessories|scarves",
    "womens|categories|accessories|cashmere",
    "womens|categories|accessories|sarong",
    "womens|categories|accessories|pouch",
    "womens|categories|shoes|birkenstocks",
    "womens|categories|shoes|boots",
    "womens|categories|shoes|colbie",
    "womens|categories|shoes|shoelace-charms",
    "womens|categories|shoes|slippers",
    "womens|categories|shoes|ballets",
    "womens|categories|shoes|oxfords-and-loafers",
    "womens|categories|shoes|sandals",
    "womens|categories|shoes|heels",
    "womens|categories|shoes|espadrilles-shoes",
    "womens|categories|shoes|jelly",
    "womens|categories|shoes|sneakers",
    "womens|categories|shoes|puma",
    "womens|categories|shoes|new-balance",
    "womens|categories|shoes|made-in-spain",
    "womens|categories|shoes|made-in-italy",
    "mens|categories|clothing|sweaters",
    "mens|categories|clothing|pants-and-chinos",
    "mens|categories|clothing|jeans",
    "mens|categories|clothing|shirts",
    "mens|categories|clothing|dress-shirts",
    "mens|categories|clothing|suits-and-tuxedos",
    "mens|categories|clothing|blazers",
    "mens|categories|clothing|coats-and-jackets",
    "mens|categories|clothing|sweatshirts-and-sweatpants",
    "mens|categories|clothing|tshirts-and-polos",
    "mens|categories|clothing|pajamas-and-loungewear",
    "mens|categories|clothing|swim",
    "mens|categories|clothing|shorts",
    "mens|categories|clothing|underwear-and-boxers",
    "mens|categories|shoes|birkenstocks",
    "mens|categories|shoes|new-balance",
    "mens|categories|shoes|boat-shoes",
    "mens|categories|shoes|loafers-and-slip-ons",
    "mens|categories|shoes|dress-shoes",
    "mens|categories|shoes|sneakers",
    "mens|categories|shoes|sandals-and-flip-flops",
    "mens|categories|shoes|boots",
    "mens|categories|shoes|exclusives",
    "mens|categories|accessories|suiting-accessories",
    "mens|categories|accessories|hats",
    "mens|categories|accessories|socks",
    "mens|categories|accessories|belts",
    "mens|categories|accessories|sunglasses",
    "mens|categories|accessories|bags-and-wallets",
    "mens|categories|accessories|home",
    "mens|categories|accessories|watches-and-jewelry",
    "girls|categories|clothing|tops",
    "girls|categories|clothing|dresses",
    "girls|categories|clothing|bottoms",
    "girls|categories|clothing|active",
    "girls|categories|clothing|coats-and-jackets",
    "girls|categories|clothing|pajamas-and-underwear",
    "girls|categories|clothing|swim-and-rash-guards",
    "girls|categories|clothing|matching-sets",
    "girls|categories|clothing|baby",
    "girls|categories|accessories|cold-weather",
    "girls|categories|accessories|hair-accessories",
    "girls|categories|accessories|jewelry",
    "girls|categories|accessories|belts",
    "girls|categories|accessories|socks-and-tights",
    "girls|categories|accessories|bags",
    "girls|categories|accessories|sunglasses",
    "girls|categories|shoes|ballet-flats-and-loafers",
    "girls|categories|shoes|flip-flops-and-sandals",
    "girls|categories|shoes|sneakers",
    "girls|categories|shoes|boots",
    "girls|categories|shoes|slippers",
    "boys|categories|clothing|tops",
    "boys|categories|clothing|bottoms",
    "boys|categories|clothing|suiting",
    "boys|categories|clothing|active",
    "boys|categories|clothing|coats-and-jackets",
    "boys|categories|clothing|pajamas",
    "boys|categories|clothing|swim-and-rash-guards",
    "boys|categories|clothing|matching-sets",
    "boys|categories|clothing|baby",
    "boys|categories|accessories|hats",
    "boys|categories|accessories|socks",
    "boys|categories|accessories|ties-and-bow-ties",
    "boys|categories|accessories|backpacks",
    "boys|categories|shoes|sneakers",
    "boys|categories|shoes|flip-flops-and-sandals",
    "boys|categories|shoes|dress-shoes",
    "boys|categories|shoes|boots",
    "boys|categories|shoes|slippers",
    "baby|categories|baby-accessories",
    "baby|categories|baby-clothing",
]

color_name_cache = {}


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def fetch_color_name(page, master_id, color_code):
    """Resolve a colorCode -> human-readable name via the product detail endpoint, cached per master id."""
    if master_id in color_name_cache:
        return color_name_cache[master_id].get(color_code, "")

    result = page.evaluate(f"""
        async () => {{
            try {{
                const r = await fetch('/browse/products/{master_id}?country-code=US&currency=USD&expand=variations');
                if (!r.ok) return null;
                return await r.json();
            }} catch (e) {{ return null; }}
        }}
    """)

    mapping = {}
    if result:
        for attr in result.get("variation_attributes") or []:
            if attr.get("id") == "color":
                for val in attr.get("values") or []:
                    mapping[val.get("value")] = val.get("name") or ""

    color_name_cache[master_id] = mapping
    return mapping.get(color_code, "")


def parse_hits(page, hits):
    rows = []
    for hit in hits:
        title = (hit.get("product_name") or "").strip()
        product_id = hit.get("product_id") or ""
        if not title or not product_id:
            continue

        custom = (hit.get("c_customData") or {}).get("hitProductProperties") or {}
        master_id = custom.get("masterProductId") or ""
        color_code = custom.get("defaultColorCode") or ""
        color = fetch_color_name(page, master_id, color_code) if master_id else ""

        price = hit.get("price")
        price_str = f"${float(price):.2f}" if price is not None else ""

        image = (hit.get("image") or {}).get("link") or ""

        master_for_url = master_id or product_id.split("-")[0]
        url = f"{BASE}/p/{master_for_url}"

        rows.append({
            "title": title,
            "color": color,
            "price": price_str,
            "image": image,
            "url":   url,
        })
    return rows


def scrape_category(page, cgid):
    inserted = skipped = 0
    start = 0
    while True:
        result = page.evaluate(f"""
            async () => {{
                const r = await fetch('/browse/product_search?country-code=US&currency=USD&count={COUNT}&start={start}&refine=cgid={cgid}&refine_1=c_displayOn=standard_usd');
                if (!r.ok) return null;
                return await r.json();
            }}
        """)
        if not result:
            break

        hits = result.get("hits") or []
        if not hits:
            break

        rows = parse_hits(page, hits)
        ins, skip = insert_products(TABLE, rows) if rows else (0, 0)
        inserted += ins
        skipped  += skip

        total = result.get("total", 0)
        start += len(hits)
        if start >= total:
            break

    return inserted, skipped


def main():
    p(f"J.Crew scraper -> table: {TABLE}")
    ensure_table(TABLE)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        Stealth().apply_stealth_sync(page)

        p("Loading jcrew.com...")
        page.goto(BASE, timeout=60000)
        page.wait_for_timeout(5000)

        total_ins = total_skip = 0
        for i, cgid in enumerate(CATEGORIES, 1):
            ins, skip = scrape_category(page, cgid)
            total_ins += ins
            total_skip += skip
            p(f"  [{i}/{len(CATEGORIES)}] {cgid}: {ins} inserted, {skip} skipped")

        browser.close()

    p(f"\n{'='*60}")
    p(f"DONE! {total_ins} inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
