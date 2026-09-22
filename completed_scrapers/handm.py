"""H&M combined (women's + men's) scraper.
NOTE: headless=False required — H&M Cloudflare blocks headless browsers at the HTTP
level (HTTP 403). The browser window will be visible during the run.

Product data is extracted from __NEXT_DATA__ (Next.js SSR JSON) on each paginated
view-all page. ?page=N pagination works once a session is established.
Gallery images are stored in the `images` array (6+ per product); primary stored in `image`.
"""
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products

TABLE = "products_hm"
BASE  = "https://www2.hm.com"

HUBS = [
    f"{BASE}/en_us/women/products/view-all.html",
    f"{BASE}/en_us/men/products/view-all.html",
]

TEST = "--test" in sys.argv  # python handm.py --test  (1 page women's only, ~36 products)


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def make_page(context):
    page = context.new_page()
    Stealth().apply_stealth_sync(page)
    return page


def get_page_data(page):
    """Return (hits_list, total_pages) from __NEXT_DATA__ SSR JSON."""
    return page.evaluate("""() => {
        const nd = document.getElementById('__NEXT_DATA__');
        if (!nd) return [[], 1];
        try {
            const data = JSON.parse(nd.textContent);
            const pld = (
                data.props?.pageProps?.plpProps
                    ?.productListingSectionProps
                    ?.productListingData || {}
            );
            const hits = pld.hits || [];
            const totalPages = pld.pagination?.totalPages || 1;
            return [hits, totalPages];
        } catch(e) {
            return [[], 1];
        }
    }""")


def hits_to_rows(hits, gender):
    rows = []
    seen = set()
    for hit in hits:
        title = (hit.get("title") or "").strip()
        price = hit.get("regularPrice") or ""
        pdp   = hit.get("pdpUrl") or ""
        url   = BASE + pdp if pdp else ""
        if not url or not title:
            continue

        gallery   = [u for u in (hit.get("galleryImages") or []) if u]
        main_img  = hit.get("imageProductSrc") or (gallery[0] if gallery else "")
        color     = (hit.get("productColor") or {}).get("colorName") or ""

        key = (url, color)
        if key not in seen:
            seen.add(key)
            rows.append({
                "title": title, "price": price, "color": color,
                "url": url, "image": main_img, "images": gallery, "gender": gender,
            })
    return rows


def scrape_hub(page, hub_url):
    gender = "women" if "/women/" in hub_url else "men"
    p(f"\nHub: {hub_url} [{gender}]")
    page.goto(hub_url, timeout=60000)
    page.wait_for_timeout(4000)

    hits, total_pages = get_page_data(page)
    if not hits:
        p("  No __NEXT_DATA__ hits found — skipping")
        return

    page_limit = 1 if TEST else total_pages
    p(f"  Total pages: {total_pages} (scraping {page_limit})")

    total_ins = total_skip = 0
    for pg in range(1, page_limit + 1):
        if pg > 1:
            page.goto(f"{hub_url}?page={pg}", timeout=60000)
            page.wait_for_timeout(3000)
            hits, _ = get_page_data(page)

        rows = hits_to_rows(hits, gender)
        ins = skip = 0
        if rows:
            ins, skip = insert_products(TABLE, rows)
            total_ins  += ins
            total_skip += skip
        p(f"  [pg {pg}/{page_limit}] {len(rows)} rows -> {ins} ins, {skip} skip")

    p(f"  Hub done: {total_ins} ins, {total_skip} skip")


def main():
    ensure_table(TABLE)
    p(f"H&M scraper -> {TABLE}" + (" [TEST MODE]" if TEST else ""))
    p("NOTE: headless=False required (H&M Cloudflare blocks headless browsers)")

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
        page = make_page(ctx)

        hubs = HUBS[:1] if TEST else HUBS
        for hub in hubs:
            scrape_hub(page, hub)

        page.close()
        browser.close()

    p(f"\n{'='*60}")
    p("DONE!")


if __name__ == "__main__":
    main()
