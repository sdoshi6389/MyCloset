"""Banana Republic scraper — same Gap Inc Constructor.io-backed API as gap.py.
Uses api.gap.com/commerce/search/products/v2/cc via browser-context fetch, brand=br.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import json

from db_insert import insert_products, ensure_table

TABLE     = "products_bananarepublic"
BASE      = "https://bananarepublic.gap.com"
IMAGE_BASE = "https://bananarepublic.gap.com"
API_BASE  = "https://api.gap.com"
CLIENT_ID = "f6c0596d-df60-460b-9b1e-298a6bc8a4b6"
PAGE_SIZE = 200

CATEGORIES = [
    # (cid, label)
    ("1158705", "women/shop-all"),
    ("69883",   "women/dresses-jumpsuits"),
    ("5037",    "women/tops-shirts"),
    ("67595",   "women/pants"),
    ("5030",    "women/jeans"),
    ("48422",   "women/new-arrivals"),
    ("3016599", "women/best-sellers"),
    ("13846",   "men/new-arrivals"),
    ("44873",   "men/casual-shirts"),
    ("35878",   "men/chinos-casual-pants"),
    ("5389",    "men/jeans"),
    ("10894",   "men/polos"),
    ("1016720", "men/coats-jackets"),
    ("75310",   "men/suits"),
    ("44866",   "men/dress-shirts"),
    ("1072457", "men/dress-pants"),
    ("3016624", "men/best-sellers"),
]


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def make_api_url(cid, page_num):
    return (
        f"{API_BASE}/commerce/search/products/v2/cc"
        f"?pageSize={PAGE_SIZE}&pageNumber={page_num}&ignoreInventory=false&cid={cid}"
        f"&vendor=constructorio&client_id={CLIENT_ID}&session_id=1"
        f"&includeMarketingFlagsDetails=true&enableDynamicFacets=true"
        f"&enableDynamicPhoto=true&brand=br&locale=en_US&market=us"
    )


def parse_products(data):
    rows = []
    products = data.get("products") or []
    if isinstance(products, dict):
        products = products.values()
    for prod in products:
        style_id = prod.get("styleId", "")
        style_name = prod.get("styleName", "").strip()
        for color in prod.get("styleColors") or []:
            cc_id = color.get("ccId", "")
            cc_name = color.get("ccShortDescription") or color.get("ccName") or ""
            cc_name = cc_name.strip()

            eff = color.get("effectivePrice") or color.get("regularPrice") or ""
            try:
                price = f"${float(eff):.2f}"
            except (ValueError, TypeError):
                price = eff

            images = color.get("images") or []
            img_path = ""
            for img in images:
                if img.get("type") == "P01":
                    img_path = img.get("path", "")
                    break
            if not img_path and images:
                img_path = images[0].get("path", "")
            image = f"{IMAGE_BASE}{img_path}" if img_path else ""

            url = f"{BASE}/browse/product.do?pid={style_id}&vid={cc_id}"

            rows.append({
                "title": style_name,
                "color": cc_name,
                "price": price,
                "image": image,
                "url":   url,
            })
    return rows


def scrape_category(page, cid, label):
    p(f"\n{'='*60}")
    p(f"Category: {label} (cid={cid})")

    api_url_0 = make_api_url(cid, 0)
    result = page.evaluate(f"""
        async () => {{
            const r = await fetch({json.dumps(api_url_0)});
            const data = await r.json();
            return {{
                totalColors: data.totalColors,
                pageNumberTotal: (data.pagination || {{}}).pageNumberTotal,
            }};
        }}
    """)

    total_colors = int(result.get("totalColors") or 0)
    num_pages = int(result.get("pageNumberTotal") or 1)
    p(f"  totalColors={total_colors}, pages={num_pages}")

    cat_inserted = cat_skipped = 0

    for pg in range(num_pages):
        api_url = make_api_url(cid, pg)
        p(f"  Page {pg + 1}/{num_pages} ...")

        data = page.evaluate(f"""
            async () => {{
                const r = await fetch({json.dumps(api_url)});
                return await r.json();
            }}
        """)

        rows = parse_products(data)
        if not rows:
            p("    0 rows")
            continue

        ins, skip = insert_products(TABLE, rows)
        cat_inserted += ins
        cat_skipped  += skip
        p(f"    {len(rows)} parsed -> {ins} inserted, {skip} skipped")

    p(f"  Category total: {cat_inserted} inserted, {cat_skipped} skipped")
    return cat_inserted, cat_skipped


def main():
    p(f"Banana Republic scraper -> table: {TABLE}")
    ensure_table(TABLE)

    total_inserted = total_skipped = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
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

        p("Loading bananarepublic.gap.com...")
        page.goto(BASE, timeout=60000)
        page.wait_for_timeout(5000)

        for cid, label in CATEGORIES:
            ins, skip = scrape_category(page, cid, label)
            total_inserted += ins
            total_skipped  += skip

        browser.close()

    p(f"\n{'='*60}")
    p(f"DONE! Total: {total_inserted} inserted, {total_skipped} skipped")


if __name__ == "__main__":
    main()
