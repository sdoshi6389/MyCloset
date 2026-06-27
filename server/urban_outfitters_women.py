from playwright.sync_api import sync_playwright
import pandas as pd
import time
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from utils.generate_clip_embeddings_for_data import process_csv

BASE_URL = "https://www.urbanoutfitters.com/womens-clothing"
OUTPUT_CSV = "urbanoutfitters_women_products.csv"
BRAND = "urban_outfitters_womens"

def scrape_urban_outfitters():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        print(f"🌐 Visiting Urban Outfitters women's clothing page...")
        page.goto(BASE_URL, timeout=60000)
        time.sleep(3)

        products = []
        current_page = 1

        while True:
            print(f"📄 Scraping page {current_page}...")
            page.wait_for_selector("div.c-pwa-tile-grid-inner >> div[data-qa-product-tile]", timeout=10000)
            product_cards = page.query_selector_all("div.c-pwa-tile-grid-inner > div[data-qa-product-tile]")

            for card in product_cards:
                try:
                    # Title
                    title_el = card.query_selector("p.o-pwa-product-tile__heading")
                    title = title_el.inner_text().strip() if title_el else "N/A"

                    # Price
                    price_el = card.query_selector("span.c-pwa-product-price__current")
                    price = price_el.inner_text().strip() if price_el else "N/A"

                    # URL
                    link_el = card.query_selector("a.o-pwa-product-tile__link")
                    relative_url = link_el.get_attribute("href") if link_el else ""
                    url = f"https://www.urbanoutfitters.com{relative_url}" if relative_url else ""

                    # Image
                    img_el = card.query_selector("img.o-pwa-image__img")
                    image = img_el.get_attribute("src") if img_el else ""

                    # Colors
                    swatches = card.query_selector_all("label.c-pwa-custom-radio__label > img")
                    colors = [swatch.get_attribute("alt") for swatch in swatches if swatch.get_attribute("alt")]
                    color = ", ".join(colors) if colors else "N/A"

                    products.append({
                        "title": title,
                        "price": price,
                        "color": color,
                        "url": url,
                        "image": image
                    })
                except Exception as e:
                    print(f"⚠️ Skipping product due to: {e}")

            # Check for next page button
            next_btn = page.query_selector("a[aria-label='Next']")
            if not next_btn or "disabled" in next_btn.get_attribute("class"):
                print("✅ No more pages. Scraping complete.")
                break

            try:
                print("➡️ Moving to next page...")
                next_btn.click()
                current_page += 1
                time.sleep(4)  # Wait for next page to load
            except Exception as e:
                print(f"❌ Error clicking next: {e}")
                break

        browser.close()
        output_csv = os.path.join(os.path.dirname(__file__), OUTPUT_CSV)
        pd.DataFrame(products).to_csv(output_csv, index=False)
        print(f"✅ Scraped {len(products)} products. Saved to {output_csv}")

        print("\n⚙️  Generating CLIP embeddings and uploading to Supabase…")
        process_csv(output_csv, BRAND)

        try:
            from callable_faiss import notify_rebuild_needed
            notify_rebuild_needed()
        except Exception:
            pass

if __name__ == "__main__":
    scrape_urban_outfitters()


#we have an issue where it thinks im a bot so have to get around that security or see if theres an api