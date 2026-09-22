"""Alo Yoga men's scraper — custom GraphQL API at api.aloyoga.com.
Each node in GetCollectionData is already one-per-color-variant; title includes
" - Color" suffix which is stripped. Pagination uses offset increments of LIMIT.
"""
import sys, os, json, urllib.parse
sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from db_insert import insert_products, ensure_table

TABLE  = "products_alo_mens"
BASE   = "https://www.aloyoga.com"
LIMIT  = 100
HASH   = "1647816df62eafdb2ef8305209f54c5c24a715ee12af8e0a86721913abb10dd1"
HANDLE = "mens-shop-all"


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def api_url(offset):
    variables  = json.dumps({"handle": HANDLE, "offset": offset, "limit": LIMIT,
                              "sortKey": "DEFAULT", "filters": [], "countryCode": "US"})
    extensions = json.dumps({"persistedQuery": {"version": 1, "sha256Hash": HASH}})
    return (
        "https://api.aloyoga.com/product-service/graphql"
        "?opName=GetCollectionData&operationName=GetCollectionData"
        f"&variables={urllib.parse.quote(variables)}"
        f"&extensions={urllib.parse.quote(extensions)}"
    )


def fetch_page(page, offset):
    url = api_url(offset)
    result = page.evaluate(f"""
        async () => {{
            const r = await fetch({json.dumps(url)});
            if (!r.ok) return null;
            return await r.json();
        }}
    """)
    if not result:
        return [], 0
    col   = (result.get("data") or {}).get("productsByCollectionHandle") or {}
    prods = col.get("products") or {}
    nodes = prods.get("nodes") or []
    total = prods.get("totalCount") or 0
    return nodes, total


def parse_node(node):
    title_raw = (node.get("title") or "").strip()
    title = title_raw.rsplit(" - ", 1)[0] if " - " in title_raw else title_raw

    color = ""
    for opt in node.get("options") or []:
        if opt.get("name") == "Color":
            vals = opt.get("values") or []
            color = vals[0] if vals else ""
            break

    amount = (node.get("priceRange") or {}).get("minVariantPrice", {}).get("amount")
    try:
        price = f"${float(amount):.2f}" if amount is not None else ""
    except (ValueError, TypeError):
        price = ""

    images = node.get("images") or []
    image  = images[0] if images else ""

    url = node.get("onlineStoreUrl") or ""

    return {"title": title, "color": color, "price": price, "image": image, "images": images, "url": url}


def main():
    p(f"Alo Yoga men's scraper -> table: {TABLE}")
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

        p("Loading aloyoga.com...")
        page.goto(BASE, timeout=60000)
        page.wait_for_timeout(5000)

        total_ins = total_skip = 0
        offset = 0
        total  = None

        while True:
            nodes, count = fetch_page(page, offset)
            if not nodes:
                break
            if total is None:
                total = count
                p(f"Total products: {total}")

            rows = [parse_node(n) for n in nodes]
            rows = [r for r in rows if r["title"] and r["url"]]

            ins, skip = insert_products(TABLE, rows) if rows else (0, 0)
            total_ins  += ins
            total_skip += skip

            end = offset + len(nodes)
            p(f"  offset {offset}-{end}: {ins} inserted, {skip} skipped")

            offset += LIMIT
            if offset >= (total or 0):
                break

        browser.close()

    p(f"\n{'='*60}")
    p(f"DONE! {total_ins} inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
