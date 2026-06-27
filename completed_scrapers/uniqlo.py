from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from playwright_stealth import Stealth
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
import re
import time
import random

BASE_URL      = "https://www.uniqlo.com"
TABLE_WOMENS  = "products_uniqlo_womens"
TABLE_MENS    = "products_uniqlo_mens"
CARD_SEL      = "a.product-tile__link"

# (table, url) — table is determined by gender of the URL path
CATEGORY_URLS = [
    # Women's
    (TABLE_WOMENS, f"{BASE_URL}/us/en/women/tops"),
    (TABLE_WOMENS, f"{BASE_URL}/us/en/women/shirts-and-blouses"),
    (TABLE_WOMENS, f"{BASE_URL}/us/en/women/sweaters"),
    (TABLE_WOMENS, f"{BASE_URL}/us/en/women/bottoms"),
    (TABLE_WOMENS, f"{BASE_URL}/us/en/women/outerwear-and-blazers"),
    (TABLE_WOMENS, f"{BASE_URL}/us/en/women/dresses-and-skirts"),
    (TABLE_WOMENS, f"{BASE_URL}/us/en/women/innerwear"),
    (TABLE_WOMENS, f"{BASE_URL}/us/en/women/loungewear-and-home"),
    (TABLE_WOMENS, f"{BASE_URL}/us/en/women/sport-utility-wear"),
    # Men's
    (TABLE_MENS,   f"{BASE_URL}/us/en/men/tops"),
    (TABLE_MENS,   f"{BASE_URL}/us/en/men/shirts"),
    (TABLE_MENS,   f"{BASE_URL}/us/en/men/sweaters"),
    (TABLE_MENS,   f"{BASE_URL}/us/en/men/pants"),
    (TABLE_MENS,   f"{BASE_URL}/us/en/men/jeans"),
    (TABLE_MENS,   f"{BASE_URL}/us/en/men/shorts"),
    (TABLE_MENS,   f"{BASE_URL}/us/en/men/outerwear-and-blazers"),
    (TABLE_MENS,   f"{BASE_URL}/us/en/men/innerwear"),
    (TABLE_MENS,   f"{BASE_URL}/us/en/men/loungewear-and-home"),
    (TABLE_MENS,   f"{BASE_URL}/us/en/men/sport-utility-wear"),
]


def scroll_to_load_all(page):
    """Scroll until infinite scroll stops adding products."""
    prev = page.locator(CARD_SEL).count()
    stale = 0
    while stale < 2:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(3)
        cur = page.locator(CARD_SEL).count()
        if cur == prev:
            stale += 1
        else:
            print(f"    Loaded {cur - prev} more  (total={cur})", flush=True)
            stale = 0
            prev = cur
    return prev


def extract_products(page):
    cards = page.query_selector_all(CARD_SEL)
    products = []
    for card in cards:
        try:
            # H2 may contain "ProductName\nVariant" — split into title + color
            title_el = card.query_selector("h2[data-testid='ITOTypography']")
            h2_text  = title_el.inner_text().strip() if title_el else ""
            h2_parts = [p.strip() for p in re.split(r"[\n|]", h2_text) if p.strip()]
            title    = h2_parts[0] if h2_parts else ""
            color    = h2_parts[1] if len(h2_parts) > 1 else ""

            # Price — first content-alignment div containing $
            price = ""
            for el in card.query_selector_all("div[data-testid='ITOContentAlignment']"):
                txt = el.inner_text().strip()
                if "$" in txt:
                    m = re.search(r"\$[\d,.]+", txt)
                    price = m.group() if m else txt
                    break

            # Image — active swiper slide, fallback to first img
            img_el = card.query_selector("div.swiper-slide-active img.image__img")
            if not img_el:
                img_el = card.query_selector("img.image__img")
            image = (img_el.get_attribute("src") or "") if img_el else ""

            # URL
            href = card.get_attribute("href") or ""
            url  = (BASE_URL + href) if href.startswith("/") else href

            if title:
                products.append({"title": title, "price": price, "color": color, "url": url, "image": image})
        except Exception as e:
            print(f"  Card error: {e}", flush=True)
    return products


def scrape_category(page, url):
    print(f"\n  Loading: {url}", flush=True)
    try:
        page.goto(url, timeout=60000)
        page.wait_for_timeout(6000)

        initial = page.locator(CARD_SEL).count()
        if initial == 0:
            print(f"  No products found — skipping", flush=True)
            return []

        print(f"  Initial cards: {initial}", flush=True)
        total = scroll_to_load_all(page)
        print(f"  Total after scroll: {total}", flush=True)

        products = extract_products(page)
        print(f"  Scraped: {len(products)} products", flush=True)
        return products

    except PWTimeout:
        print(f"  Timeout — skipping", flush=True)
        return []
    except Exception as e:
        print(f"  Error: {e}", flush=True)
        return []


def main():
    print("Connecting to Supabase...", flush=True)
    ensure_table(TABLE_WOMENS)
    ensure_table(TABLE_MENS)
    print(f"Tables '{TABLE_WOMENS}' and '{TABLE_MENS}' ready.", flush=True)

    stats = {TABLE_WOMENS: [0, 0], TABLE_MENS: [0, 0]}  # [inserted, skipped]

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        print("Warming up on homepage...", flush=True)
        page.goto(BASE_URL + "/us/en/", timeout=60000)
        page.wait_for_timeout(5000)

        for table, url in CATEGORY_URLS:
            products = scrape_category(page, url)
            if products:
                ins, skip = insert_products(table, products)
                stats[table][0] += ins
                stats[table][1] += skip
                print(f"  DB: {ins} inserted, {skip} skipped  → {table}", flush=True)
            time.sleep(random.uniform(3, 7))

        browser.close()

    print("\n" + "=" * 55, flush=True)
    for tbl, (ins, skip) in stats.items():
        print(f"  {tbl}", flush=True)
        print(f"    Inserted : {ins}", flush=True)
        print(f"    Skipped  : {skip}  (already in DB)", flush=True)
    total_ins  = sum(v[0] for v in stats.values())
    total_skip = sum(v[1] for v in stats.values())
    print(f"  ── TOTAL ──", flush=True)
    print(f"    Inserted : {total_ins}", flush=True)
    print(f"    Skipped  : {total_skip}", flush=True)
    print("=" * 55, flush=True)


if __name__ == "__main__":
    main()
