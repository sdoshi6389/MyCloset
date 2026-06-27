from playwright.sync_api import sync_playwright
import time
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products

TABLE = "products_nike_mens"
BASE_URL = "https://www.nike.com"

CATEGORY_URLS = [
    "https://www.nike.com/w/mens-shoes-nik1zy7ok",
    "https://www.nike.com/w/mens-clothing-6ymx6znik1",
]


def scroll_and_load_all(page):
    """Scroll incrementally so Nike's intersection observer fires and loads each batch of 24."""
    print("📜 Scrolling to load all products...")
    prev_count = 0
    stagnant = 0

    while True:
        current_count = page.locator("div.product-card").count()
        print(f"  Products loaded: {current_count}")

        if current_count > prev_count:
            stagnant = 0
            prev_count = current_count
        else:
            stagnant += 1
            if stagnant >= 6:
                print("✅ No more products loading.")
                break

        # Scroll by ~1 viewport height so intersection observers fire on each new row
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        page.wait_for_timeout(1800)


def extract_products(page):
    cards = page.query_selector_all("div.product-card")
    print(f"🛍️  Extracting from {len(cards)} product cards...")
    products = []

    for card in cards:
        try:
            # Title
            title_elem = card.query_selector("div.product-card__title")
            title = title_elem.inner_text().strip() if title_elem else "MISSING_TITLE"

            # Subtitle (e.g. "Men's Shoes")
            subtitle_elem = card.query_selector("div.product-card__subtitle")
            subtitle = subtitle_elem.inner_text().strip() if subtitle_elem else ""

            # Price — data-testid is most stable
            price_elem = card.query_selector("[data-testid='product-price']")
            price = price_elem.inner_text().strip() if price_elem else "MISSING_PRICE"

            # URL — link-overlay already contains the full absolute URL
            link_elem = card.query_selector("a.product-card__link-overlay")
            url = link_elem.get_attribute("href") if link_elem else "MISSING_URL"
            if url and not url.startswith("http"):
                url = BASE_URL + url

            # Image
            img_elem = card.query_selector("img.product-card__hero-image")
            image = img_elem.get_attribute("src") if img_elem else "MISSING_IMAGE"

            # Color: Nike doesn't always surface a color chip on listing pages.
            # The colorway is often embedded in the title (e.g. "Air Jordan 1 ... 'Phantom and Pine Green'")
            # Use subtitle as the category label and leave color as the title itself.
            color_elem = card.query_selector("[data-testid='product-card__color-description']")
            color = color_elem.inner_text().strip() if color_elem else subtitle

            products.append({
                "title": title,
                "price": price,
                "color": color,
                "url": url,
                "image": image,
            })

        except Exception as e:
            print(f"⚠️  Error on card: {e}")

    print(f"✅ Extracted {len(products)} products.")
    return products


def scrape_category(context, cat_url):
    print(f"\n🌐 Visiting: {cat_url}")
    page = context.new_page()
    page.goto(cat_url, timeout=60000)
    page.wait_for_timeout(4000)

    scroll_and_load_all(page)
    products = extract_products(page)
    page.close()
    return products


def main():
    all_products = []
    seen_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )
        )

        for cat_url in CATEGORY_URLS:
            products = scrape_category(context, cat_url)
            for prod in products:
                if prod["url"] not in seen_urls:
                    seen_urls.add(prod["url"])
                    all_products.append(prod)

        browser.close()

    ensure_table(TABLE)
    ins, skip = insert_products(TABLE, all_products)
    print(f"\nDone! {ins} inserted, {skip} skipped (already in DB).")


if __name__ == "__main__":
    main()
