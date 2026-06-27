from playwright.sync_api import sync_playwright
import time
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products

TABLE = "products_abercrombie_womens"
START_URL = "https://www.abercrombie.com/shop/us/womens"
BASE_URL = "https://www.abercrombie.com"

def extract_products(page):
    print("🛍️ Extracting products...")
    product_cards = page.query_selector_all("li[data-testid='catalog-product-card']")
    products = []

    for card in product_cards:
        try:
            # Title
            title_elem = card.query_selector('h2[data-testid="catalog-product-card-name"]')
            title = title_elem.inner_text().strip() if title_elem else "MISSING_TITLE"

            # Price
            price_elem = card.query_selector('span[data-testid="product-price"] span.product-price-text')
            price = price_elem.inner_text().strip() if price_elem else "MISSING_PRICE"

            # URL
            url_elem = card.query_selector('a.catalog-productCard-module__product-content-link')
            href = url_elem.get_attribute("href") if url_elem else None
            full_url = BASE_URL + href if href else "MISSING_URL"

            # Main Image
            img_elem = card.query_selector("img.catalog-productCard-module__productCardImage_1")
            image_url = img_elem.get_attribute("src") if img_elem else "MISSING_IMAGE"

            # Colors
            swatch_labels = card.query_selector_all('div[data-testid="catalog-product-card-swatch-tile"] label.screen-reader-text')
            colors = [lbl.inner_text().replace(" swatch", "").strip() for lbl in swatch_labels]
            color_string = ", ".join(colors) if colors else "MISSING_COLOR"

            products.append({
                "title": title,
                "price": price,
                "color": color_string,
                "url": full_url,
                "image": image_url
            })

        except Exception as e:
            print(f"⚠️ Error extracting a product: {e}")

    print(f"✅ Extracted {len(products)} products on this page.")
    return products

def click_next_page(page):
    next_button = page.query_selector('button[aria-label="Go to next page"]')
    if next_button and not next_button.is_disabled():
        next_button.scroll_into_view_if_needed()
        next_button.click()
        page.wait_for_timeout(3000)
        return True
    return False

def main():
    all_products = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(START_URL, timeout=60000)
        page.wait_for_timeout(3000)

        while True:
            all_products += extract_products(page)
            if not click_next_page(page):
                print("🚫 No more pages to navigate.")
                break

        browser.close()

    ensure_table(TABLE)
    ins, skip = insert_products(TABLE, all_products)
    print(f"\nDone! {ins} inserted, {skip} skipped (already in DB).")

if __name__ == "__main__":
    main()
