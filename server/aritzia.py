from playwright.sync_api import sync_playwright, TimeoutError
import pandas as pd
import time
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from utils.generate_clip_embeddings_for_data import process_csv

START_URL = "https://www.aritzia.com/us/en/clothing"
BASE_URL = "https://www.aritzia.com"
OUTPUT_CSV = "aritzia_women_products.csv"
BRAND = "aritzia"

def infinite_scroll(page, max_scrolls=200, buffer_time=5):
    print("📜 Scrolling to load all products...")
    last_count = 0
    stagnant_scrolls = 0

    for i in range(max_scrolls):
        print(f"🔄 Scroll step {i + 1}")
        page.mouse.wheel(0, 1200)
        time.sleep(buffer_time)

        current_count = page.locator('[data-testid^="plp-product-tile-"]').count()
        print(f"🧮 Products loaded: {current_count}")

        if current_count == last_count:
            stagnant_scrolls += 1

            # Anti-stuck trick: scroll up slightly if stuck for 2+ tries
            if stagnant_scrolls >= 2:
                print("🧱 Possibly stuck — scrolling up to trigger lazy load...")
                page.mouse.wheel(0, -600)
                time.sleep(5)  # let it reposition
                page.mouse.wheel(0, 1200)
                time.sleep(buffer_time)

        else:
            stagnant_scrolls = 0

        last_count = current_count

        if stagnant_scrolls >= 10:
            print("✅ No more products loading. Done scrolling.")
            break


def extract_products(page):
    print("🛍️ Extracting product data...")
    cards = page.query_selector_all('[data-testid^="plp-product-tile-"]')
    products = []

    for card in cards:
        try:
            # Title
            title_elem = card.query_selector('[data-testid="plp-product-name"]')
            title = title_elem.inner_text().strip() if title_elem else "MISSING_TITLE"

            # Price: prefer sale price, fallback to original
            price_elem = card.query_selector('[data-testid="plp-sale-price-text"]') or card.query_selector('[data-testid="plp-list-price-text"]')
            price = price_elem.inner_text().strip() if price_elem else "MISSING_PRICE"

            # URL
            url_elem = card.query_selector("a._13qupa2j")
            href = url_elem.get_attribute("href") if url_elem else None
            full_url = BASE_URL + href if href else "MISSING_URL"

            # Image
            img_elem = card.query_selector('img[data-testid^="plp-product-image-"]')
            image_url = img_elem.get_attribute("src") if img_elem else "MISSING_IMAGE"

            # Colors
            color_buttons = card.query_selector_all('button[data-testid^="tile-color-"]')
            colors = []
            for btn in color_buttons:
                label = btn.get_attribute("data-testid")
                if label and label.startswith("tile-color-"):
                    colors.append(label.replace("tile-color-", "").replace("-", " ").title())
            color_string = ", ".join(sorted(set(colors))) if colors else "MISSING_COLOR"

            products.append({
                "title": title,
                "price": price,
                "color": color_string,
                "url": full_url,
                "image": image_url
            })

        except Exception as e:
            print(f"⚠️ Error extracting product: {e}")

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

        infinite_scroll(page)
        all_products = extract_products(page)

        browser.close()

    df = pd.DataFrame(all_products)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"🎉 Scraped {len(all_products)} products. Saved to {OUTPUT_CSV}")

    print("\n⚙️  Generating CLIP embeddings and uploading to Supabase…")
    process_csv(os.path.abspath(OUTPUT_CSV), BRAND)

    try:
        from callable_faiss import notify_rebuild_needed
        notify_rebuild_needed()
    except Exception:
        pass

if __name__ == "__main__":
    main()
