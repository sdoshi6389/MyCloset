"""H&M women's scraper.
NOTE: H&M uses Cloudflare Bot Management which blocks headless browsers at the HTTP
level (403). This scraper must run with headless=False. The browser window will be
visible during the run.

Category pages use a "Load next page" button for pagination.
Each product PDP exposes per-color swatch links — one row is inserted per color
with the color-specific URL.
"""
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products

TABLE     = "products_hm_womens"
BASE_URL  = "https://www2.hm.com"
START_URL = f"{BASE_URL}/en_us/women.html"

TEST = "--test" in sys.argv  # python handm_women.py --test  (1 category, 3 PDPs)


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def make_page(context):
    page = context.new_page()
    Stealth().apply_stealth_sync(page)
    return page


def get_category_links(page):
    p("Collecting women's category links...")
    page.goto(START_URL, timeout=60000)
    page.wait_for_timeout(3000)

    links = set()
    for a in page.query_selector_all("ul.be3030 li a"):
        href = a.get_attribute("href") or ""
        if "/en_us/women/products/" in href:
            links.add(BASE_URL + href)
    for a in page.query_selector_all("a[href*='/en_us/women/seasonal-trending/']"):
        href = a.get_attribute("href") or ""
        if href:
            links.add(href if href.startswith("http") else BASE_URL + href)

    # Fallback: scrape nav links if sidebar class changed
    if not links:
        p("  Sidebar class changed — falling back to nav link scan")
        for a in page.query_selector_all("a[href*='/en_us/women/products/']"):
            href = a.get_attribute("href") or ""
            if href:
                links.add(href if href.startswith("http") else BASE_URL + href)

    p(f"Found {len(links)} category links")
    return list(links)


def collect_product_links(page):
    product_urls = set()
    previous_count = -1

    while True:
        for li in page.query_selector_all("ul[data-elid='product-grid'] li"):
            a = li.query_selector("a[href*='/productpage.']")
            if a:
                href = a.get_attribute("href") or ""
                if href:
                    product_urls.add(href if href.startswith("http") else BASE_URL + href)

        if len(product_urls) == previous_count:
            break
        previous_count = len(product_urls)

        try:
            btn = page.query_selector("button[data-elid='pagination-hybrid-button']")
            if btn and btn.get_attribute("aria-disabled") == "false":
                p(f"  Loading next page ({len(product_urls)} so far)...")
                btn.click()
                page.wait_for_timeout(3000)
            else:
                break
        except Exception as e:
            p(f"  Pagination error: {e}")
            break

    return list(product_urls)


def scrape_product(page, url):
    try:
        page.goto(url, timeout=60000)
        page.wait_for_timeout(2000)

        title_el = page.query_selector("h1")
        title = title_el.inner_text().strip() if title_el else ""

        price_el = page.query_selector("span.e31b97")
        price = price_el.inner_text().strip() if price_el else ""

        img_el = page.query_selector("div[data-testid='next-image'] img")
        image  = img_el.get_attribute("src") if img_el else ""

        rows = []
        for swatch in page.query_selector_all("a[role='radio'][title][href*='/productpage.']"):
            color_name = swatch.get_attribute("title") or ""
            href = swatch.get_attribute("href") or ""
            color_url = href if href.startswith("http") else (BASE_URL + href if href else url)
            rows.append({"title": title, "price": price, "color": color_name,
                         "url": color_url, "image": image})

        if not rows:
            rows.append({"title": title, "price": price, "color": "", "url": url, "image": image})

        return rows

    except Exception as e:
        p(f"  Error: {e}")
        return []


def main():
    ensure_table(TABLE)
    p(f"H&M women's scraper -> {TABLE}" + (" [TEST MODE]" if TEST else ""))
    p("NOTE: running with visible browser (H&M blocks headless via Cloudflare)")

    all_products = []
    visited_urls = set()

    with sync_playwright() as pw:
        # headless=False required — H&M Cloudflare returns 403 for headless browsers
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )

        cat_page = make_page(ctx)
        category_links = get_category_links(cat_page)

        if not category_links:
            p("No categories found — H&M may have updated their nav structure. Exiting.")
            browser.close()
            return

        cat_limit = 1 if TEST else len(category_links)
        for cat_url in category_links[:cat_limit]:
            p(f"\nCategory: {cat_url}")
            cat_page.goto(cat_url, timeout=60000)
            cat_page.wait_for_timeout(2000)
            product_urls = collect_product_links(cat_page)
            p(f"  {len(product_urls)} products found")

            pdp_limit = 3 if TEST else len(product_urls)
            for i, pdp_url in enumerate(product_urls[:pdp_limit]):
                if pdp_url in visited_urls:
                    continue
                visited_urls.add(pdp_url)

                detail_page = make_page(ctx)
                rows = scrape_product(detail_page, pdp_url)
                detail_page.close()

                if rows:
                    ins, skip = insert_products(TABLE, rows)
                    all_products.extend(rows)
                    p(f"  [{i+1}/{min(pdp_limit, len(product_urls))}] {rows[0]['title']} | "
                      f"{len(rows)} color(s) | {ins} ins, {skip} skip")

        cat_page.close()
        browser.close()

    p(f"\n{'='*60}")
    p(f"DONE! {len(all_products)} total rows scraped")


if __name__ == "__main__":
    main()
