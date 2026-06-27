from playwright.sync_api import sync_playwright
import time
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products

TABLE = "products_brandy_melville"
BASE_URL = "https://us.brandymelville.com"

CATEGORY_URLS = {
    "clothing": "https://us.brandymelville.com/collections/clothing",
    "intimates": "https://us.brandymelville.com/collections/intimates-pajamas",
    "cardigans": "https://us.brandymelville.com/collections/cardigans",
    "graphics": "https://us.brandymelville.com/collections/graphics",
    "accessories": "https://us.brandymelville.com/collections/accessories",
}

def infinite_scroll(page, max_scrolls=150, buffer_time=3):
    last_count = 0
    stagnant_scrolls = 0

    for i in range(max_scrolls):
        print(f"🔄 Scroll step {i + 1}")

        # Scroll to the 'load-more' div to trigger lazy loading
        page.evaluate("""
            () => {
                const loader = document.querySelector('.load-more');
                if (loader) {
                    loader.scrollIntoView({ behavior: 'smooth', block: 'end' });
                } else {
                    window.scrollBy(0, 1000);
                }
            }
        """)

        page.set_viewport_size({"width": 1200, "height": 720 + (i % 2)})
        time.sleep(buffer_time)

        current_count = page.locator("li.grid__item").count()
        print(f"🧮 Products loaded: {current_count}")

        if current_count == last_count:
            stagnant_scrolls += 1
            if stagnant_scrolls >= 5:
                print("✅ No more products loading.")
                break
        else:
            stagnant_scrolls = 0

        last_count = current_count

def extract_products(page, category):
    print(f"🛍️ Extracting products for category: {category}")
    cards = page.query_selector_all("li.grid__item")
    products = []

    for card in cards:
        try:
            title_elem = card.query_selector(".card-information__text")
            title = title_elem.inner_text().strip() if title_elem else "MISSING_TITLE"

            price_elem = card.query_selector(".price-item--regular, .price-item--sale")
            price = price_elem.inner_text().strip() if price_elem else "MISSING_PRICE"

            img_elem = card.query_selector("img")
            image_url = img_elem.get_attribute("src") if img_elem else "MISSING_IMAGE"
            if image_url and image_url.startswith("//"):
                image_url = "https:" + image_url

            color = img_elem.get_attribute("alt") or img_elem.get_attribute("data-uw-rm-alt-original") or "MISSING_COLOR"

            link_elem = card.query_selector("a.full-unstyled-link")
            href = link_elem.get_attribute("href") if link_elem else None
            full_url = f"{BASE_URL}{href}" if href else "MISSING_URL"

            products.append({
                "title": title,
                "price": price,
                "color": color,
                "url": full_url,
                "image": image_url
            })

        except Exception as e:
            print(f"⚠️ Error extracting a product: {e}")

    print(f"✅ Extracted {len(products)} products from {category}.")
    return products

def main():
    all_products = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()

        for category, url in CATEGORY_URLS.items():
            print(f"\n🚀 Scraping category: {category.upper()} → {url}")
            page = context.new_page()
            page.goto(url, timeout=60000)
            page.wait_for_timeout(3000)

            infinite_scroll(page)
            products = extract_products(page, category)
            all_products.extend(products)

            page.close()

        browser.close()

    ensure_table(TABLE)
    ins, skip = insert_products(TABLE, all_products)
    print(f"\nDone! {ins} inserted, {skip} skipped (already in DB).")

if __name__ == "__main__":
    main()
