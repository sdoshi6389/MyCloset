"""Kate Spade scraper — Next.js RSC payload via browser-context fetch.
Each category page embeds a JSON-LD ItemList (schema.org Product entries) inside its React
Server Component payload. Full pagination requires replicating Next.js's internal
next-router-state-tree encoding (not attempted), so each category yields its first batch
(~16 products, matching the underlying SFCC default page size) — categories/subcategories
are combined to maximize total coverage instead.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import json

from db_insert import insert_products, ensure_table

TABLE = "products_katespade"
BASE  = "https://www.katespade.com"

CATEGORIES = [
    "/shop/new/view-all",
    "/shop/sale/view-all",
    "/shop/handbags/view-all",
    "/shop/wallets/view-all",
    "/shop/jewelry/view-all",
    "/shop/shoes/view-all",
    "/shop/clothing/view-all",
    "/shop/accessories/view-all",
    "/shop/home/view-all",
    "/shop/gifts/view-all",
    "/shop/new/handbags",
    "/shop/accessories/keychains-bag-accessories",
    "/shop/vacation-travel-shop",
    "/shop/red",
]


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def extract_json_ld_list(body):
    """Bracket-match the JSON-LD ItemList array embedded in the RSC payload text."""
    idx = body.find('[{"@type":"ListItem"')
    if idx == -1:
        return None
    depth = 0
    i = idx
    in_str = False
    esc = False
    while i < len(body):
        ch = body[i]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == '[':
                depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    return body[idx:i + 1]
        i += 1
    return None


def parse_items(items):
    rows = []
    for li in items:
        item = li.get("item") or {}
        title = (item.get("name") or "").strip()
        color = (item.get("color") or "").strip()
        url = item.get("url") or item.get("@id") or ""
        images = item.get("image") or []
        image = images[0] if images else ""
        offers = item.get("offers") or {}
        try:
            price = f"${float(offers.get('price', 0)):.2f}"
        except (ValueError, TypeError):
            price = ""

        if not title or not url:
            continue

        rows.append({
            "title": title,
            "color": color,
            "price": price,
            "image": image,
            "url":   url,
        })
    return rows


def scrape_category(page, path):
    p(f"\n  [{path}]")
    captured = []

    def on_response(resp):
        if "_rsc=" in resp.url and resp.status == 200:
            try:
                captured.append(resp.body().decode("utf-8", errors="replace"))
            except Exception:
                pass

    page.on("response", on_response)
    try:
        page.goto(BASE + path, timeout=60000)
        page.wait_for_timeout(7000)
    except Exception as e:
        p(f"    navigation error: {e}")
        page.remove_listener("response", on_response)
        return 0, 0
    page.remove_listener("response", on_response)

    if not captured:
        p("    no RSC payload captured")
        return 0, 0

    body = max(captured, key=len)
    json_ld = extract_json_ld_list(body)
    if not json_ld:
        p("    no JSON-LD found in payload")
        return 0, 0

    try:
        items = json.loads(json_ld)
    except Exception as e:
        p(f"    JSON parse error: {e}")
        return 0, 0

    rows = parse_items(items)
    p(f"    {len(items)} list items -> {len(rows)} rows")
    if not rows:
        return 0, 0

    ins, skip = insert_products(TABLE, rows)
    p(f"    {ins} inserted, {skip} skipped")
    return ins, skip


def main():
    p(f"Kate Spade scraper -> table: {TABLE}")
    ensure_table(TABLE)

    total_ins = total_skip = 0

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

        p("Loading katespade.com...")
        page.goto(BASE, timeout=60000)
        page.wait_for_timeout(5000)

        for path in CATEGORIES:
            ins, skip = scrape_category(page, path)
            total_ins  += ins
            total_skip += skip

        browser.close()

    p(f"\n{'='*60}")
    p(f"DONE! {total_ins} inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
