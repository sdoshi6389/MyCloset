from playwright.sync_api import sync_playwright, TimeoutError
import time
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products

TABLE = "products_alo_mens"
START_URL = "https://www.aloyoga.com/collections/mens-shop-all"
BASE_URL = "https://www.aloyoga.com"

def infinite_scroll(page, max_scrolls=500, wait=3.5):
    print("Scrolling to load all products...", flush=True)

    prev_count = 0
    stall = 0
    step = 0

    while step < max_scrolls:
        step += 1

        # Always jump to the actual bottom of the document so new batches trigger
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(wait)

        count = page.locator(".PlpTile").count()
        print(f"  Scroll {step}: {count} products", flush=True)

        if count > prev_count:
            stall = 0
            prev_count = count
        else:
            stall += 1
            if stall >= 4:
                # One last nudge: scroll up slightly then back to bottom
                page.evaluate("window.scrollBy(0, -400)")
                time.sleep(1)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(wait)
                final = page.locator(".PlpTile").count()
                if final > prev_count:
                    print(f"  Scroll {step} (nudge): {final} products", flush=True)
                    prev_count = final
                    stall = 0
                else:
                    print(f"  Stopped — no new products after {stall} stalls.", flush=True)
                    break

def extract_products(page):
    print("🛍️ Extracting product data...")
    cards = page.query_selector_all(".PlpTile")
    products = []

    for card in cards:
        try:
            # Title: from product name inside <p class="body semibold">
            title_elem = card.query_selector("p.body.semibold")
            title = title_elem.inner_text().strip() if title_elem else "MISSING_TITLE"

            # Price: from <span class="product-price regular__price">
            price_elem = card.query_selector("span.product-price")
            price = price_elem.inner_text().strip() if price_elem else "MISSING_PRICE"

            # URL
            link_elem = card.query_selector("a[href]")
            url = link_elem.get_attribute("href") if link_elem else None
            full_url = BASE_URL + url if url else "MISSING_URL"

            # Image: get first <img> inside the swiper
            img_elem = card.query_selector("img")
            image_url = img_elem.get_attribute("src") if img_elem else "MISSING_IMAGE"

            # Color(s): grab all swatch buttons under .swatches-wrapper
            swatch_buttons = card.query_selector_all(".swatches-wrapper button[aria-label]")
            colors = [btn.get_attribute("aria-label") for btn in swatch_buttons if btn.get_attribute("aria-label")]
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
        page.wait_for_timeout(6000)

        infinite_scroll(page)
        all_products = extract_products(page)

        browser.close()

    ensure_table(TABLE)
    ins, skip = insert_products(TABLE, all_products)
    print(f"\nDone! {ins} inserted, {skip} skipped (already in DB).")

if __name__ == "__main__":
    main()
