from playwright.sync_api import sync_playwright
import time
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products

TABLE = "products_forever21_womens"

START_URL = "https://www.forever21.com/collections/womens-clothing"
BASE_URL = "https://www.forever21.com"

def load_all_products(page):
    print("📜 Clicking 'Show More' until all products are loaded...")
    max_attempts = 50
    for i in range(max_attempts):
        try:
            show_more = page.query_selector("a[data-load-more]")
            if show_more:
                print(f"🔄 Clicking Show More... ({i+1})")
                show_more.scroll_into_view_if_needed()
                show_more.click()
                page.wait_for_timeout(3000)
            else:
                print("✅ No more 'Show More' button found.")
                break
        except Exception as e:
            print(f"⚠️ Error during pagination: {e}")
            break

def extract_products(page):
    print("🛍️ Extracting product data...")
    cards = page.query_selector_all("li.product")
    products = []

    for card in cards:
        try:
            # Title
            title_elem = card.query_selector("a.card-title")
            title = title_elem.get_attribute("data-product-title") if title_elem else "MISSING_TITLE"

            # Price
            price_elem = card.query_selector(".price__last .price-item")
            price = price_elem.inner_text().strip() if price_elem else "MISSING_PRICE"

            # URL
            url = title_elem.get_attribute("href") if title_elem else None
            full_url = BASE_URL + url if url else "MISSING_URL"

            # Image
            img_elem = card.query_selector("img")
            image_url = "https:" + img_elem.get_attribute("src") if img_elem else "MISSING_IMAGE"

            # Color(s)
            swatch_labels = card.query_selector_all(".swatch-label")
            colors = [label.get_attribute("data-value") for label in swatch_labels if label.get_attribute("data-value")]
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

    print(f"✅ Extracted {len(products)} products.")
    return products

def main():
    all_products = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(START_URL, timeout=60000)
        page.wait_for_timeout(3000)

        load_all_products(page)
        all_products = extract_products(page)

        browser.close()

    ensure_table(TABLE)
    ins, skip = insert_products(TABLE, all_products)
    print(f"\nDone! {ins} inserted, {skip} skipped (already in DB).")

if __name__ == "__main__":
    main()
