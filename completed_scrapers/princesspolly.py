from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, Error as PWError
from playwright_stealth import Stealth
import re
import time
import random
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products

TABLE = "products_princesspolly"
COLLECTION_URL = "https://us.princesspolly.com/collections/clothing"
TILE_SEL = "div.product-tile"
PAGES_PER_BROWSER = 10
INTER_PAGE_DELAY = (8, 14)


class BrowserDead(Exception):
    """CF closed the browser/tab — caller should recycle."""


def get_total_pages(page):
    el = page.query_selector("[class*='pagination']")
    if el:
        match = re.search(r"of\s+(\d+)", el.inner_text())
        if match:
            return int(match.group(1))
    return 1


def extract_color_from_title(title):
    parts = title.strip().split()
    return parts[-1] if parts else "MISSING_COLOR"


def extract_products(page):
    tiles = page.query_selector_all(TILE_SEL)
    products = []
    for tile in tiles:
        try:
            name_el = tile.query_selector("a.product-tile__name")
            price_el = tile.query_selector("span.product-tile__price:not(.product-tile__sale-price)")
            link_el = tile.query_selector("a.product-tile__image-link")
            img_el = tile.query_selector("img.product-tile__image")

            title = name_el.inner_text().strip() if name_el else "MISSING_TITLE"
            price = price_el.inner_text().strip() if price_el else "MISSING_PRICE"

            url = (link_el.get_attribute("href") or "") if link_el else ""
            if url and not url.startswith("http"):
                url = "https://us.princesspolly.com" + url

            image = (img_el.get_attribute("src") or "") if img_el else ""
            color = extract_color_from_title(title)

            products.append({
                "title": title,
                "price": price,
                "color": color,
                "url": url or "MISSING_URL",
                "image": image or "MISSING_IMAGE",
            })
        except Exception as e:
            print(f"  Error on tile: {e}")
    return products


def wait_for_page_ready(page, timeout_sec=60):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        title = page.title().lower()
        if "just a moment" in title or "checking your browser" in title:
            time.sleep(3)
            continue
        if page.locator(TILE_SEL).count() > 0:
            return True
        time.sleep(2)
    return False


def navigate_with_retry(page, url, retries=3):
    for attempt in range(retries):
        try:
            page.goto(url, timeout=90000)
            return True
        except PWTimeout:
            print(f"    Timeout on attempt {attempt + 1}")
            time.sleep(15)
        except PWError as e:
            msg = str(e).lower()
            if "closed" in msg or "target" in msg:
                raise BrowserDead(str(e))
            raise
    return False


def open_fresh_browser(pw, start_page):
    browser = pw.chromium.launch(headless=False)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        viewport={"width": 1280, "height": 900},
    )
    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    navigate_with_retry(page, "https://us.princesspolly.com/")
    page.wait_for_timeout(random.randint(4000, 7000))

    url = f"{COLLECTION_URL}?page={start_page}"
    if not navigate_with_retry(page, url):
        browser.close()
        return None, None

    if not wait_for_page_ready(page, timeout_sec=60):
        browser.close()
        return None, None

    return browser, page


def main():
    all_products = []
    ensure_table(TABLE)

    with sync_playwright() as pw:
        print("Opening first browser ...")
        browser, page = open_fresh_browser(pw, 1)
        if page is None:
            print("Failed to load page 1 -- aborting.")
            return

        print(f"Title: {page.title()}")
        total_pages = get_total_pages(page)
        print(f"Total pages: {total_pages}")

        batch = extract_products(page)
        all_products.extend(batch)
        print(f"  Page 1: {len(batch)} products (total: {len(all_products)})")

        current_pg = 2
        pages_in_browser = 1

        def recycle(reason):
            nonlocal browser, page, pages_in_browser
            print(f"\n--- {reason} at page {current_pg} -- recycling browser ---")
            try:
                browser.close()
            except Exception:
                pass
            time.sleep(random.uniform(20, 30))
            browser, page = open_fresh_browser(pw, current_pg)
            pages_in_browser = 0

        while current_pg <= total_pages:
            # Scheduled recycle every PAGES_PER_BROWSER pages
            if pages_in_browser >= PAGES_PER_BROWSER:
                recycle("Scheduled CF reset")
                if page is None:
                    print("  Failed to open browser after scheduled recycle -- stopping.")
                    break
            else:
                # Normal navigation to next page
                time.sleep(random.uniform(*INTER_PAGE_DELAY))
                url = f"{COLLECTION_URL}?page={current_pg}"
                try:
                    nav_ok = navigate_with_retry(page, url)
                except BrowserDead:
                    recycle("Browser closed by CF")
                    if page is None:
                        print("  Still blocked after recycle -- stopping.")
                        break
                    nav_ok = True  # open_fresh_browser already loaded current_pg

                if not nav_ok:
                    print(f"  Page {current_pg}: navigation failed -- stopping.")
                    break

                if not wait_for_page_ready(page, timeout_sec=60):
                    recycle("CF challenge unresolved")
                    if page is None:
                        print("  Still blocked after recycle -- stopping.")
                        break

            batch = extract_products(page)
            if not batch:
                print(f"  Page {current_pg}: 0 products -- stopping.")
                break

            all_products.extend(batch)

            if current_pg % 5 == 0 or current_pg == total_pages:
                insert_products(TABLE, all_products)
                print(f"  Page {current_pg}/{total_pages}: {len(batch)} products (total: {len(all_products)}) [saved]")
            else:
                print(f"  Page {current_pg}/{total_pages}: {len(batch)} products (total: {len(all_products)})")

            current_pg += 1
            pages_in_browser += 1

        try:
            browser.close()
        except Exception:
            pass

    ins, skip = insert_products(TABLE, all_products)
    print(f"\nDone! {ins} inserted, {skip} skipped (already in DB).")


if __name__ == "__main__":
    main()
