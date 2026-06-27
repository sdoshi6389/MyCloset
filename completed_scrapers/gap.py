"""Gap scraper — uses api.gap.com/commerce/search/products/v2/cc via browser-context fetch.
Each page returns a 'products' dict with full color/price/image data.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import json

from db_insert import insert_products, ensure_table

TABLE = "products_gap"
BASE = "https://www.gap.com"
IMAGE_BASE = "https://www.gap.com"
API_BASE = "https://api.gap.com"
CLIENT_ID = "f866e274-31be-4eef-9ea0-db7250ef0a70"
PAGE_SIZE = 200

CATEGORIES = [
    # (cid, label, extra_params)
    ("1127944", "men/shop-all-styles",   "department=75"),
    ("1127938", "women/shop-all-styles", ""),
]


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def make_api_url(cid, page_num, extra=""):
    url = (
        f"{API_BASE}/commerce/search/products/v2/cc"
        f"?pageSize={PAGE_SIZE}&pageNumber={page_num}&ignoreInventory=false&cid={cid}"
        f"&vendor=constructorio&client_id={CLIENT_ID}&session_id=1"
        f"&includeMarketingFlagsDetails=true&enableDynamicFacets=true"
        f"&enableDynamicPhoto=true&brand=gap&locale=en_US&market=us"
    )
    if extra:
        url += f"&{extra}"
    return url


def parse_products(data):
    """Extract rows from the 'products' dict in the API response."""
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

            # Price: prefer effectivePrice (already accounts for promotions)
            eff = color.get("effectivePrice") or color.get("regularPrice") or ""
            try:
                price = f"${float(eff):.2f}"
            except (ValueError, TypeError):
                price = eff

            # Image: prefer P01 type (front-facing product photo)
            images = color.get("images") or []
            img_path = ""
            for img in images:
                if img.get("type") == "P01":
                    img_path = img.get("path", "")
                    break
            if not img_path and images:
                img_path = images[0].get("path", "")
            image = f"{IMAGE_BASE}{img_path}" if img_path else ""

            # URL: product page with specific color variant
            url = f"{BASE}/browse/product.do?pid={style_id}&vid={cc_id}"

            rows.append({
                "title": style_name,
                "color": cc_name,
                "price": price,
                "image": image,
                "url": url,
            })
    return rows


def scrape_category(page, cid, label, extra, total_inserted, total_skipped):
    p(f"\n{'='*60}")
    p(f"Category: {label} (cid={cid})")

    # Fetch page 0 first to get pagination info
    api_url_0 = make_api_url(cid, 0, extra)
    result = page.evaluate(f"""
        async () => {{
            const r = await fetch({json.dumps(api_url_0)});
            const data = await r.json();
            return {{
                totalColors: data.totalColors,
                pageNumberTotal: (data.pagination || {{}}).pageNumberTotal,
                status: r.status,
            }};
        }}
    """)

    total_colors = int(result.get("totalColors") or 0)
    num_pages = int(result.get("pageNumberTotal") or 1)
    p(f"  totalColors={total_colors}, pages={num_pages}")

    cat_inserted = 0
    cat_skipped = 0

    for pg in range(num_pages):
        api_url = make_api_url(cid, pg, extra)
        p(f"  Page {pg + 1}/{num_pages} ...")

        data = page.evaluate(f"""
            async () => {{
                const r = await fetch({json.dumps(api_url)});
                return await r.json();
            }}
        """)

        rows = parse_products(data)
        if not rows:
            p("0 rows")
            continue

        ins, skip = insert_products(TABLE, rows)
        cat_inserted += ins
        cat_skipped += skip
        p(f"{len(rows)} parsed → {ins} inserted, {skip} skipped")

    p(f"  Category total: {cat_inserted} inserted, {cat_skipped} skipped")
    return total_inserted + cat_inserted, total_skipped + cat_skipped


def main():
    p(f"Gap scraper starting → table: {TABLE}")
    ensure_table(TABLE)

    total_inserted = 0
    total_skipped = 0

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

        p("Loading gap.com homepage...")
        page.goto(BASE, timeout=60000)
        page.wait_for_timeout(5000)

        for cid, label, extra in CATEGORIES:
            total_inserted, total_skipped = scrape_category(
                page, cid, label, extra, total_inserted, total_skipped
            )

        browser.close()

    p(f"\n{'='*60}")
    p(f"DONE! Total: {total_inserted} inserted, {total_skipped} skipped")


if __name__ == "__main__":
    main()
