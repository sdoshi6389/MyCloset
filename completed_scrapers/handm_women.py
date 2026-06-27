from playwright.sync_api import sync_playwright
import time
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products

TABLE = "products_hm_womens"

START_URL = "https://www2.hm.com/en_us/women.html"
BASE_URL = "https://www2.hm.com"

def get_category_links(page):
    print("🔍 Collecting all women category + seasonal links...")
    page.goto(START_URL, timeout=60000)
    page.wait_for_timeout(3000)

    category_links = set()

    # === A. Main category links from sidebar menu ===
    sidebar_anchors = page.query_selector_all("ul.be3030 li a")
    for a in sidebar_anchors:
        href = a.get_attribute("href")
        if href and "/en_us/women/products/" in href:
            category_links.add(BASE_URL + href)

    # === B. Seasonal/curated collection links ===
    seasonal_anchors = page.query_selector_all("a[href*='/en_us/women/seasonal-trending/']")
    for a in seasonal_anchors:
        href = a.get_attribute("href")
        if href:
            full_url = BASE_URL + href if href.startswith("/") else href
            category_links.add(full_url)

    print(f"✅ Found {len(category_links)} total category/seasonal links")
    print(category_links)
    return list(category_links)


def scroll_and_collect_product_links(page):
    print("📜 Starting product collection with pagination...")

    product_urls = set()
    previous_count = -1

    while True:
        # 🧾 Collect product links
        lis = page.query_selector_all("ul[data-elid='product-grid'] li")
        print(f"🔍 Found {len(lis)} products so far...")
        for li in lis:
            a_tag = li.query_selector("a[href*='/productpage.']")
            if a_tag:
                href = a_tag.get_attribute("href")
                if href:
                    full_url = href if href.startswith("http") else BASE_URL + href
                    product_urls.add(full_url)

        # Stop if no new products were added
        if len(product_urls) == previous_count:
            print("✅ No new products loaded. Done with this category.")
            break
        previous_count = len(product_urls)

        # Click "Load next page" if available
        try:
            next_btn = page.query_selector("button[data-elid='pagination-hybrid-button']")
            if next_btn:
                is_disabled = next_btn.get_attribute("aria-disabled")
                if is_disabled == "false":
                    print("🔄 Clicking 'Load next page'...")
                    next_btn.click()
                    page.wait_for_timeout(3000)
                else:
                    print("⛔ Button exists but is disabled. Done.")
                    break
            else:
                print("🚫 No pagination button found.")
                break
        except Exception as e:
            print(f"⚠️ Pagination error: {e}")
            break

    print(f"🧾 Total unique product URLs collected: {len(product_urls)}")
    return list(product_urls)


def scrape_product_detail(page, url):
    try:
        page.goto(url, timeout=60000)
        page.wait_for_timeout(2000)

        # 🏷️ Title
        title_elem = page.query_selector("h1")
        title = title_elem.inner_text().strip() if title_elem else "MISSING_TITLE"

        # 💵 Price
        price_elem = page.query_selector("span.e31b97")
        price = price_elem.inner_text().strip() if price_elem else "MISSING_PRICE"

        # 🎨 All color variants
        color_swatches = page.query_selector_all("a[role='radio'][title][href*='/productpage.']")
        color_set = set()
        for swatch in color_swatches:
            color_name = swatch.get_attribute("title")
            if color_name:
                color_set.add(color_name)
        colors = list(color_set)


        # 🖼️ Primary image (current swatch)
        img_elem = page.query_selector("div[data-testid='next-image'] img")
        image_url = img_elem.get_attribute("src") if img_elem else "MISSING_IMAGE"

        print({
            "title": title,
            "price": price,
            "colors": colors,
            "url": url,
            "image": image_url
        })

        return {
            "title": title,
            "price": price,
            "colors": ", ".join(colors),
            "url": url,
            "image": image_url
        }

    except Exception as e:
        print(f"❌ Failed scraping {url}: {e}")
        return None


def main():
    all_products = []
    visited_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # Step 1: Get all category links
        category_links = get_category_links(page)

        # Step 2: Visit each category and collect product URLs
        for cat_url in category_links:
            print(f"\n🌐 Visiting category: {cat_url}")
            page.goto(cat_url, timeout=60000)
            page.wait_for_timeout(2000)

            product_urls = scroll_and_collect_product_links(page)

            for i, pdp_url in enumerate(product_urls):
                if pdp_url in visited_urls:
                    continue
                visited_urls.add(pdp_url)

                print(f"🛍️ Scraping product {i+1}/{len(product_urls)}: {pdp_url}")
                detail_page = context.new_page()
                data = scrape_product_detail(detail_page, pdp_url)
                detail_page.close()

                if data:
                    all_products.append(data)

        browser.close()

    # Save to DB
    ensure_table(TABLE)
    ins, skip = insert_products(TABLE, all_products)
    print(f"\nDone! {ins} inserted, {skip} skipped (already in DB).")

if __name__ == "__main__":
    main()
