from playwright.sync_api import sync_playwright
import time
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products

TABLE = "products_essentials_womens"

def get_all_page_links(page, base_url="https://fearofgod.com/collections/essentials-women"):
    print("🔍 Detecting pagination range...")
    page.wait_for_selector("div.pagination", timeout=10000)

    last_page = 1
    pagination_items = page.query_selector_all("div.pagination ul li")

    for item in pagination_items:
        try:
            # grab either <a> or <span>
            text = item.inner_text().strip()
            if text.isdigit():
                last_page = max(last_page, int(text))
        except:
            continue

    print(f"✅ Detected last page as: {last_page}")

    # Generate all page URLs
    page_urls = [f"{base_url}?page={i}" for i in range(1, last_page + 1)]
    return page_urls

def extract_products_from_page(page):
    print("📦 Extracting products...")

    try:
        page.wait_for_selector("div.grid-item", timeout=10000)
    except:
        print("⚠️ Timeout waiting for product cards.")
        return []

    product_cards = page.query_selector_all("div.grid-item")
    products = []

    for card in product_cards:
        try:
            # 🏷️ Title
            title_elem = card.query_selector("h3.title")
            title = title_elem.inner_text().strip() if title_elem else "MISSING_TITLE"

            # 💵 Price
            price_elem = card.query_selector("span.price")
            price = price_elem.inner_text().strip().replace("$", "").strip() if price_elem else "MISSING_PRICE"

            # 🔗 URL
            link_elem = card.query_selector("a")
            href = link_elem.get_attribute("href") if link_elem else ""
            url = f"https://fearofgod.com{href}" if href else "MISSING_URL"

            # 🖼️ Image
            img_elem = card.query_selector("img.picture__img")
            image = "https:" + img_elem.get_attribute("src") if img_elem else "MISSING_IMAGE"

            products.append({
                "title": title,
                "price": f"${price}",
                "image": image,
                "url": url
            })
        except Exception as e:
            print(f"❌ Failed to extract product: {e}")

    print(f"✅ Found {len(products)} products on this page.")
    return products


def main():
    all_products = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # Load first page
        base_url = "https://fearofgod.com/collections/essentials-women"
        print(f"🌐 Visiting: {base_url}")
        page.goto(base_url, timeout=60000)
        page.wait_for_timeout(3000)

        all_pages = get_all_page_links(page)

        for i, url in enumerate(all_pages):
            print(f"\n🔄 Scraping page {i+1}/{len(all_pages)}: {url}")
            page.goto(url, timeout=60000)
            page.wait_for_timeout(3000)
            products = extract_products_from_page(page)
            all_products.extend(products)

        browser.close()

    ensure_table(TABLE)
    ins, skip = insert_products(TABLE, all_products)
    print(f"\nDone! {ins} inserted, {skip} skipped (already in DB).")

if __name__ == "__main__":
    main()
