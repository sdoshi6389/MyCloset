from playwright.sync_api import sync_playwright
import time
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products

TABLE = "products_gymshark_mens"

def click_view_all_if_present(page):
    try:
        view_all = page.query_selector("a:has-text('View All')")
        if view_all:
            print("✅ Clicking 'View All'...")
            view_all.click()
            page.wait_for_timeout(3000)
            return
        load_more = page.query_selector("button:has-text('Load More')")
        if load_more:
            print("✅ Clicking 'Load More'...")
            load_more.click()
            page.wait_for_timeout(3000)
    except Exception as e:
        print(f"⚠️ View/Load button click error: {e}")

def scroll_to_bottom(page):
    previous_height = 0
    for i in range(30):
        page.mouse.wheel(0, 4000)
        time.sleep(1.5)
        current_height = page.evaluate("document.body.scrollHeight")
        if current_height == previous_height:
            break
        previous_height = current_height

def get_color_variant_urls(page):
    swatches = page.query_selector_all("a[aria-label][href*='/products/']")
    urls = set()
    for swatch in swatches:
        href = swatch.get_attribute("href")
        if href:
            if href.startswith("http"):
                urls.add(href)
            else:
                urls.add(f"https://www.gymshark.com{href}")
    return list(urls)

def get_collection_links(page):
    print("🔍 Finding all collection links on /shop-men page...")
    links = []
    tiles = page.query_selector_all("a:has-text('SHOP NOW')")

    for i, tile in enumerate(tiles):
        try:
            href = tile.get_attribute("href")
            if href and "/collections/" in href:
                full_url = f"https://www.gymshark.com{href}" if href.startswith("/") else href
                print(f"✅ Found collection #{i+1}: {full_url}")
                links.append(full_url)
        except Exception as e:
            print(f"❌ Error extracting collection link: {e}")
    
    return list(set(links))

def scrape_product_detail(page, url):
    try:
        page.goto(url, timeout=60000)
        page.wait_for_timeout(2000)

        # 🏷️ Title (use h1 or fallback)
        title_elem = page.query_selector("h1[data-testid='product-title']") or page.query_selector("h1")
        title = title_elem.inner_text().strip() if title_elem else "MISSING_TITLE"

        # 💵 Price (with cleanup)
        price_elem = page.query_selector("span[class*='product-price']") or page.query_selector("span[data-testid='product-price']")
        price = price_elem.inner_text().strip().replace("\n", " ") if price_elem else "MISSING_PRICE"

        # 🎨 Color
        color_elem = page.query_selector("p[data-testid^='plp-productColour'], span[data-testid^='product-colour']")
        color = color_elem.inner_text().strip() if color_elem else "MISSING_COLOR"

        # 🖼️ Product image – real one, not SVG/logo
        image_elem = page.query_selector("img[src*='cdn.shopify.com']")
        image_url = image_elem.get_attribute("src") if image_elem else "MISSING_IMAGE"

        print({
            "title": title,
            "price": price,
            "color": color,
            "url": url,
            "image": image_url
        })

        return {
            "title": title,
            "price": price,
            "color": color,
            "url": url,
            "image": image_url
        }

    except Exception as e:
        print(f"❌ Failed PDP scrape: {e}")
        return None

def scrape_products_from_collection(context, collection_url, visited_urls):
    print(f"\n🌐 Visiting collection: {collection_url}")
    page = context.new_page()
    page.goto(collection_url, timeout=60000)
    page.wait_for_timeout(3000)

    click_view_all_if_present(page)
    scroll_to_bottom(page)

    product_cards = page.query_selector_all("article[class^='product-card_product-card']")
    print(f"🧾 Found {len(product_cards)} base products")

    products = []
    pdp_urls = []

    for card in product_cards:
        pdp_link = card.query_selector("a[href*='/products/']")
        if not pdp_link:
            continue
        href = pdp_link.get_attribute("href")
        if not href:
            continue
        full_url = f"https://www.gymshark.com{href}" if href.startswith("/") else href
        pdp_urls.append(full_url)

    page.close()

    for i, pdp_url in enumerate(pdp_urls):
        if pdp_url in visited_urls:
            continue

        print(f"🛍️ Visiting base PDP #{i+1}: {pdp_url}")
        pdp_page = context.new_page()
        pdp_page.goto(pdp_url, timeout=60000)
        pdp_page.wait_for_timeout(2000)

        variant_urls = get_color_variant_urls(pdp_page)
        # Include the base PDP first
        variant_urls = [pdp_url] + [url for url in variant_urls if url != pdp_url]
        pdp_page.close()

        product_count_before = len(products)

        for variant_url in variant_urls:
            if variant_url in visited_urls:
                continue
            visited_urls.add(variant_url)

            try:
                print(f"🎨 Visiting color variant: {variant_url}")
                variant_page = context.new_page()
                info = scrape_product_detail(variant_page, variant_url)
                variant_page.close()
                if info:
                    products.append(info)
            except Exception as e:
                print(f"❌ Failed variant scrape: {e}")

        product_count_after = len(products)
        scraped_count = product_count_after - product_count_before

        if scraped_count == 0:
            print(f"❌ No color variants scraped for base PDP #{i+1}")
        else:
            print(f"✅ Scraped {scraped_count} variant(s) for base PDP #{i+1}")

    return products

def main():
    all_products = []
    visited_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # Step 1: Go to the shop-men page
        print("🌐 Opening: https://www.gymshark.com/pages/shop-men")
        page.goto("https://www.gymshark.com/pages/shop-men", timeout=60000)
        page.wait_for_timeout(3000)

        # Step 2: Extract all /collections links
        collection_links = get_collection_links(page)

        # Step 3: Scrape each collection page
        for collection_url in collection_links:
            products = scrape_products_from_collection(context, collection_url, visited_urls)
            all_products.extend(products)

        browser.close()

    # Step 4: Save to DB
    ensure_table(TABLE)
    ins, skip = insert_products(TABLE, all_products)
    print(f"\nDone! {ins} inserted, {skip} skipped (already in DB).")

if __name__ == "__main__":
    main()
