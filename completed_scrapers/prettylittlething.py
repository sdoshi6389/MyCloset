"""PrettyLittleThing scraper — Algolia API via browser-context fetch."""
import sys, os, json, math
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_prettylittlething"
BASE = "https://www.prettylittlething.com"
ALGOLIA_APP_ID = "PBL6WQH9VL"
ALGOLIA_API_KEY = "aca5366ccc1a1abd3118258c97c7322f"
ALGOLIA_INDEX = "prettylittlething-dbz-prod"
ALGOLIA_URL = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/*/queries"
HITS_PER_PAGE = 100


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def fetch_page(page, pg_num):
    body = json.dumps({
        "requests": [{
            "indexName": ALGOLIA_INDEX,
            "params": "&".join([
                f"hitsPerPage={HITS_PER_PAGE}",
                f"page={pg_num}",
                "distinct=true",
                "facetFilters=" + json.dumps([["brand:prettylittlething"]]),
            ])
        }]
    })
    result = page.evaluate(f"""
        async () => {{
            const r = await fetch({json.dumps(ALGOLIA_URL)}, {{
                method: "POST",
                headers: {{
                    "Content-Type": "application/json",
                    "x-algolia-application-id": "{ALGOLIA_APP_ID}",
                    "x-algolia-api-key": "{ALGOLIA_API_KEY}",
                }},
                body: {json.dumps(body)}
            }});
            return await r.json();
        }}
    """)
    if 'results' not in result:
        p(f"  Page {pg_num} error: {str(result)[:200]}")
        return [], 0
    res0 = result['results'][0]
    hits = res0.get('hits', [])
    nb_pages = res0.get('nbPages', 0)
    return hits, nb_pages


def parse_hits(hits):
    out = []
    for h in hits:
        name = (h.get('name') or '').strip()
        slug = (h.get('slug') or '').strip()
        if not name or not slug:
            continue

        color = (h.get('colourFacet') or h.get('colour') or '').strip()

        price_raw = h.get('price')
        try:
            price = f"${float(price_raw):.2f}" if price_raw is not None else ''
        except (ValueError, TypeError):
            price = ''

        images = h.get('images') or []
        image = images[0] if images else ''

        url = f"{BASE}/{slug}.html"

        out.append({'title': name, 'price': price, 'color': color, 'url': url, 'image': image})
    return out


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
        pg = ctx.new_page()
        Stealth().apply_stealth_sync(pg)

        p("Loading homepage to establish session...")
        pg.goto(BASE, timeout=60000)
        pg.wait_for_timeout(4000)

        page_num = 0
        nb_pages = None
        total_hits = 0

        while True:
            hits, nb = fetch_page(pg, page_num)
            if nb_pages is None:
                nb_pages = nb
                p(f"Total pages: {nb_pages}")

            if not hits:
                p(f"  Page {page_num}: no hits — stopping")
                break

            products = parse_hits(hits)
            total_hits += len(hits)
            ins, skip = insert_products(TABLE, products)
            total_ins += ins
            total_skip += skip
            p(f"  Page {page_num}: {len(hits)} hits -> {ins} inserted, {skip} skipped")

            page_num += 1
            if page_num >= nb_pages:
                p(f"  Reached last page ({page_num} >= {nb_pages})")
                break
            pg.wait_for_timeout(150)

        browser.close()

    p(f"\n{'='*50}")
    p(f"DONE! Total hits: {total_hits}, {total_ins} inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
