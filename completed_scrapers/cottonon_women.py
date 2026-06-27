from playwright.sync_api import sync_playwright
import time
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products

TABLE = "products_cottonon_womens"
BASE_URL = "https://cottonon.com/US/co/women/"

def scrape_cottonon_women():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        print("🌐 Visiting Cotton On women's clothing page...")
        page.goto(BASE_URL, timeout=60000)

        while True:
            try:
                load_more = page.query_selector('a.load-more-btn')
                if not load_more or not load_more.is_visible():
                    print("✅ No more 'Load More' button found.")
                    break

                print("🔄 Clicking 'Load More'...")
                page.evaluate("document.querySelector('a.load-more-btn').click()")
                time.sleep(3)  # Wait for new products to load
            except Exception as e:
                print(f"⚠️ Error during scrolling: {e}")
                break

        print("📦 Collecting product data...")
        products = []
        product_cards = page.query_selector_all("li.grid-tile.pagination-item.columns.gtm-product-data-container")

        for product in product_cards:
            try:
                # Get product title
                title_el = product.query_selector("div.product-name a")
                title = title_el.inner_text().strip() if title_el else "N/A"

                # Get price
                price_el = product.query_selector("span.product-sales-price")
                price = price_el.inner_text().strip() if price_el else "N/A"

                # Get all color names from span class names
                color_spans = product.query_selector_all("div.product-colours-available span")
                colors = []
                for span in color_spans:
                    classes = span.get_attribute("class")
                    if classes and "swatch-" in classes:
                        for cls in classes.split():
                            if cls.startswith("swatch-") and cls != "swatch":
                                color_name = cls.replace("swatch-", "").replace("_", " ")
                                colors.append(color_name.title())
                color = ", ".join(colors) if colors else "N/A"

                # Get product link
                link_el = product.query_selector("a")
                url = link_el.get_attribute("href") if link_el else ""
                if url and not url.startswith("http"):
                    url = "https://cottonon.com" + url

                # Get image
                img_el = product.query_selector("img")
                image = img_el.get_attribute("src") if img_el else ""

                products.append({
                    "title": title,
                    "price": price,
                    "color": color,
                    "url": url,
                    "image": image
                })
            except Exception as e:
                print(f"⚠️ Skipping product due to: {e}")

        browser.close()
        ensure_table(TABLE)
        ins, skip = insert_products(TABLE, products)
        print(f"\nDone! {ins} inserted, {skip} skipped (already in DB).")

if __name__ == "__main__":
    scrape_cottonon_women()
