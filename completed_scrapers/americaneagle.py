"""American Eagle scraper — SSR category pages + PDP HTML color fetch."""
import sys, os, re, json
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_americaneagle"
BASE = "https://www.ae.com"

# (category_id, path_fragment) for constructing URL
CATEGORIES = [
    # Men's
    ("cat6430041",  "men/bottoms/jeans"),
    ("cat90012",    "men/tops/t-shirts"),
    ("cat40005",    "men/tops/shirts-flannels"),
    ("cat5180435",  "men/bottoms/shorts"),
    ("cat10027",    "men/bottoms"),
    ("cat10032",    "men/underwear"),
    ("cat1100008",  "men/activewear"),
    ("cat130005",   "men/loungewear-pjs"),
    ("cat4840022",  "men/accessories-socks"),
    ("cat2490040",  "men/ae77-premium-collection"),
    ("clrmens",     "men/clearance"),
    # Women's
    ("cat6430042",  "women/bottoms/jeans"),
    ("cat380159",   "women/bottoms/shorts"),
    ("cat90030",    "women/tops/t-shirts"),
    ("cat380157",   "women/tops/tank-tops-tube-tops"),
    ("cat10049",    "women/tops"),
    ("cat1320034",  "women/dresses"),
    ("cat5920105",  "women/bottoms/skirts-skorts"),
    ("cat10051",    "women/bottoms"),
    ("cat730011",   "women/loungewear-pjs"),
    ("cat4840018",  "women/accessories-socks"),
    ("clrwomens",   "women/clearance"),
]

COLOR_RE = re.compile(r'"colorName"\s*:\s*"([^"]+)"')
PRICE_RE = re.compile(r'\$[\d,]+\.?\d*')


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def scroll_to_load_all(page):
    """Scroll category page until no new products appear."""
    prev = 0
    stable = 0
    for _ in range(30):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2500)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight - 500)")
        page.wait_for_timeout(500)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1500)
        count = page.evaluate("() => document.querySelectorAll('[data-product-id]').length")
        if count == prev:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        prev = count
    return count


def extract_products_from_dom(page, cat_path):
    """Extract product rows from category page DOM."""
    raw = page.evaluate("""
        () => {
            const seen = new Set();
            const results = [];
            const cards = document.querySelectorAll('[data-product-id]');
            for (const card of cards) {
                const pid = card.getAttribute('data-product-id');
                if (!pid || seen.has(pid)) continue;
                seen.add(pid);
                const linkEl = card.querySelector('a[href*="/us/en/p/"]');
                const href = linkEl ? linkEl.href : '';
                const titleEl = card.querySelector('[class*="title"], [class*="Title"], h2, h3');
                const rawTitle = titleEl ? titleEl.innerText.trim() : '';
                const priceEl = card.querySelector('[class*="price"], [class*="Price"]');
                const rawPrice = priceEl ? priceEl.innerText.trim() : '';
                const imgEl = card.querySelector('img[src*="scene7"]');
                const image = imgEl ? (imgEl.src || '').split('?')[0] : '';
                results.push({pid, href, rawTitle, rawPrice, image});
            }
            return results;
        }
    """)
    rows = []
    for r in raw:
        title = r.get('rawTitle', '').strip()
        url = r.get('href', '')
        pid = r.get('pid', '')
        image = r.get('image', '')
        # Parse price — take first dollar amount (sale price or regular)
        price_matches = PRICE_RE.findall(r.get('rawPrice', ''))
        price = price_matches[0] if price_matches else ''
        if title and url and pid:
            rows.append({'pid': pid, 'title': title, 'price': price, 'url': url, 'image': image, 'color': ''})
    return rows


def fetch_colors_batch(page, pids, batch_size=15):
    """Fetch PDP HTML in batches and extract color names."""
    color_map = {}
    for i in range(0, len(pids), batch_size):
        batch = pids[i:i + batch_size]
        js_batch = json.dumps([f"{BASE}/us/en/p/x/x/x/x/{pid}" for pid in batch])
        results = page.evaluate(f"""
            async () => {{
                const urls = {js_batch};
                const responses = await Promise.allSettled(
                    urls.map(url => fetch(url).then(r => r.text()).catch(() => ''))
                );
                return responses.map(r => r.status === 'fulfilled' ? r.value : '');
            }}
        """)
        for pid, html in zip(batch, results or []):
            m = COLOR_RE.search(html or '')
            color_map[pid] = m.group(1).strip() if m else ''
        page.wait_for_timeout(800)  # Polite delay between batches
    return color_map


def main():
    ensure_table(TABLE)
    total_ins = 0
    total_skip = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US", viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        Stealth().apply_stealth_sync(page)

        # Load homepage first for session + Akamai validation
        p("Loading homepage for session...")
        page.goto(BASE, timeout=60000)
        page.wait_for_timeout(5000)
        try:
            page.click('button:has-text("OK")', timeout=3000)
            page.wait_for_timeout(1000)
        except Exception:
            pass

        all_products = {}  # pid -> row dict (deduplicate across categories)

        for cat_id, cat_path in CATEGORIES:
            cat_url = f"{BASE}/us/en/c/{cat_path}/{cat_id}"
            p(f"\n[{cat_path}] {cat_url}")
            try:
                page.goto(cat_url, timeout=60000)
                page.wait_for_timeout(8000)
                final_count = scroll_to_load_all(page)
                rows = extract_products_from_dom(page, cat_path)
                new_pids = [r['pid'] for r in rows if r['pid'] not in all_products]
                for r in rows:
                    if r['pid'] not in all_products:
                        all_products[r['pid']] = r
                p(f"  {final_count} DOM products, {len(rows)} extracted, {len(new_pids)} new")
            except Exception as e:
                p(f"  ERROR: {e}")

        p(f"\nTotal unique products collected: {len(all_products)}")

        # Batch-fetch colors for all unique products
        p(f"\nFetching colors for {len(all_products)} products (batches of 15)...")
        all_pids = list(all_products.keys())
        color_map = fetch_colors_batch(page, all_pids)
        colored = sum(1 for c in color_map.values() if c)
        p(f"Colors found: {colored}/{len(all_pids)}")

        # Assign colors and build final rows
        final_rows = []
        for pid, row in all_products.items():
            color = color_map.get(pid, '')
            final_rows.append({
                'title': row['title'],
                'price': row['price'],
                'color': color,
                'url': row['url'],
                'image': row['image'],
            })

        # Insert to DB
        p(f"\nInserting {len(final_rows)} rows into {TABLE}...")
        ins, skip = insert_products(TABLE, final_rows)
        total_ins += ins
        total_skip += skip

        browser.close()

    p(f"\n{'='*50}")
    p(f"DONE! {total_ins} inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
