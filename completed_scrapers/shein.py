"""Shein scraper — DOM-based (API is risk-control gated; PLP tiles render via SSR/CSR).
Handles: GeeTest CAPTCHA (manual solve on first run, cookies reused after),
coupon-dialog popup that blocks scroll (closed/bypassed via scrollIntoView),
and incremental scroll-based lazy loading.
"""
import sys, os, re, json
sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from db_insert import insert_products, ensure_table

TABLE   = "products_shein"
BASE    = "https://us.shein.com"
COOKIE_FILE = os.path.join(os.path.dirname(__file__), "shein_cookies.json")

CATEGORIES = [
    ("/women-clothing-c-1727.html", "women"),
    ("/RecommendSelection/Men-Clothing-sc-017172963.html", "men"),
]

MAX_SCROLLS = 40


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def load_cookies():
    if os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE) as f:
            return json.load(f)
    return None


def save_cookies(ctx):
    with open(COOKIE_FILE, "w") as f:
        json.dump(ctx.cookies(), f)


def close_popups(page):
    """Close coupon-dialog / promo modals that set body{overflow:hidden}.
    Selectors for the close button vary/are unreliable, so also forcibly hide
    any large fixed/absolute high-z-index overlay covering the viewport.
    """
    page.evaluate("""
        () => {
            const closeSelectors = [
                '.sui-dialog .sui-dialog__close', '.sui-dialog [class*="close"]',
                '.coupon-dialog [class*="close"]', '[class*="dialog"] [class*="close"]',
            ];
            for (const sel of closeSelectors) {
                document.querySelectorAll(sel).forEach(el => { try { el.click(); } catch(e) {} });
            }
            // Forcibly hide any big high-z-index overlay still blocking the page
            document.querySelectorAll('div').forEach(d => {
                const s = getComputedStyle(d);
                if ((s.position === 'fixed' || s.position === 'absolute') &&
                    parseInt(s.zIndex || 0) > 100 &&
                    d.offsetWidth > 300 && d.offsetHeight > 300 &&
                    s.display !== 'none') {
                    d.style.display = 'none';
                }
            });
            document.body.style.overflow = 'auto';
            document.documentElement.style.overflow = 'auto';
        }
    """)


def extract_tiles(page):
    return page.evaluate("""
        () => {
            const cards = document.querySelectorAll('.product-card');
            const seen = new Set();
            const results = [];
            for (const card of cards) {
                const link = card.querySelector('a[href*="-p-"]');
                if (!link) continue;
                const m = link.href.match(/-p-(\\d+)/);
                const pid = m ? m[1] : null;
                if (!pid || seen.has(pid)) continue;
                seen.add(pid);
                const img = card.querySelector('img');
                const priceEl = card.querySelector('[class*="price"]');
                let priceText = priceEl ? priceEl.innerText.trim() : '';
                results.push({
                    pid,
                    url: link.href.split('?')[0],
                    alt: img ? (img.alt || '') : '',
                    img: img ? (img.src || img.getAttribute('data-src') || '') : '',
                    priceText,
                });
            }
            return results;
        }
    """)


PRICE_RE = re.compile(r'\$\d+\.\d{2}')


def parse_rows(tiles):
    rows = []
    for t in tiles:
        alt = t["alt"].strip()
        # Title/color: Shein alt text is "Title, tag1,tag2..." — first comma segment is the title
        if ", " in alt:
            title, _, rest = alt.partition(", ")
            color = rest.split(",")[0].strip()
        else:
            title, color = alt, ""

        prices = PRICE_RE.findall(t["priceText"])
        price = prices[0] if prices else ""

        if not title or not t["url"]:
            continue

        rows.append({
            "title": title.strip(),
            "color": color,
            "price": price,
            "image": t["img"],
            "url":   t["url"],
        })
    return rows


def scrape_category(page, path, label):
    p(f"\n  [{label}] {path}")
    page.goto(BASE + path, timeout=60000)
    page.wait_for_timeout(8000)

    has_captcha = page.evaluate(
        "() => document.body.innerText.toLowerCase().includes('click the following icons')"
    )
    if has_captcha:
        p("  CAPTCHA detected! Please solve it manually in the browser window now.")
        p("  Waiting up to 180s for product tiles to appear...")
        try:
            page.wait_for_selector('a[href*="-p-"]', timeout=180000)
        except Exception:
            p("  Timed out waiting for CAPTCHA solve. Skipping category.")
            return 0, 0
        save_cookies(page.context)
        p("  Solved! Cookies saved for future runs.")

    close_popups(page)
    page.wait_for_timeout(1500)

    prev_count = 0
    stable = 0
    for i in range(MAX_SCROLLS):
        page.evaluate("""
            () => {
                const cards = document.querySelectorAll('.product-card');
                if (cards.length) cards[cards.length - 1].scrollIntoView({block: 'end'});
                window.scrollBy(0, 1500);
            }
        """)
        page.wait_for_timeout(1800)
        close_popups(page)

        count = page.evaluate("() => document.querySelectorAll('.product-card a[href*=\"-p-\"]').length")
        if count == prev_count:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
        prev_count = count

    p(f"  Scroll done, {prev_count} links in DOM")

    tiles = extract_tiles(page)
    rows = parse_rows(tiles)
    p(f"  Extracted {len(tiles)} unique products -> {len(rows)} valid rows")

    if not rows:
        return 0, 0
    ins, skip = insert_products(TABLE, rows)
    p(f"  [{label}] {ins} inserted, {skip} skipped")
    return ins, skip


def main():
    p(f"Shein scraper -> table: {TABLE}")
    ensure_table(TABLE)

    total_ins = total_skip = 0
    cookies = load_cookies()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1280, "height": 900},
        )
        if cookies:
            ctx.add_cookies(cookies)
            p(f"Loaded {len(cookies)} saved cookies")

        page = ctx.new_page()
        Stealth().apply_stealth_sync(page)

        for path, label in CATEGORIES:
            ins, skip = scrape_category(page, path, label)
            total_ins  += ins
            total_skip += skip

        browser.close()

    p(f"\n{'='*60}")
    p(f"DONE! {total_ins} inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
