"""Under Armour scraper — Constructor.io browse API via browser-context fetch."""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(__file__))
from db_insert import ensure_table, insert_products
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

TABLE = "products_underarmour"
BASE = "https://www.underarmour.com"
CNSTRC_KEY = "key_Gz4VzKsXbR7b7fSh"
CNSTRC_BASE = "https://ac.cnstrc.com"
GROUPS = ["men", "women"]
PAGE_SIZE = 100


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def to_price(val):
    if isinstance(val, list):
        val = val[0] if val else None
    try:
        return f"${float(val):.2f}" if val is not None else ''
    except (ValueError, TypeError):
        return ''


def parse_results(results, seen_keys):
    rows = []
    for res in results:
        title = (res.get('value') or '').strip()
        data = res.get('data') or {}
        product_id = data.get('id', '')
        base_url = BASE + (data.get('url') or '')

        # Lowest sale price for fallback
        sale_low = data.get('salePriceLow')
        list_low = data.get('listPriceLow')
        base_price = to_price(sale_low if sale_low is not None else list_low)

        # Expand colors from variations — deduplicate by colorWay
        variations = res.get('variations') or []
        seen_colors = set()

        for var in variations:
            vdata = var.get('data') or {}
            if vdata.get('hideColorWay'):
                continue
            color = (vdata.get('colorWay') or '').strip()
            if not color or color in seen_colors:
                continue
            seen_colors.add(color)

            key = f"{product_id}|{color}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            image = (vdata.get('image_url') or '').split('?')[0]  # strip query params
            var_url = BASE + (vdata.get('url') or data.get('url') or '')
            var_sale = vdata.get('salePrice')
            var_list = vdata.get('listPrice')
            var_price_raw = var_sale if var_sale is not None else var_list
            price = to_price(var_price_raw) or base_price

            rows.append({'title': title, 'price': price, 'color': color,
                         'url': var_url, 'image': image})

        # Fallback: if no valid variations, use top-level color
        if not seen_colors:
            color = (data.get('colorWay') or '').strip()
            key = f"{product_id}|{color}"
            if key not in seen_keys:
                seen_keys.add(key)
                image = (data.get('image_url') or '').split('?')[0]
                rows.append({'title': title, 'price': base_price, 'color': color,
                             'url': base_url, 'image': image})

    return rows


def main():
    ensure_table(TABLE)
    total_ins = 0
    total_skip = 0
    seen_keys = set()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            locale="en-US", viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        Stealth().apply_stealth_sync(page)

        p("Loading UA homepage to establish session...")
        page.goto(BASE, timeout=60000)
        page.wait_for_timeout(3000)

        for group in GROUPS:
            p(f"\n{'='*50}")
            p(f"Group: {group}")

            # Get total count
            first = page.evaluate("""
                async (args) => {
                    const url = args.base + '/browse/group_id/' + args.group +
                        '?key=' + args.key + '&c=ciojs-client-2.65.0&offset=0&num_results_per_page=1';
                    const r = await fetch(url, {headers: {'Accept': 'application/json'}});
                    const d = await r.json();
                    return {total: d.response && d.response.total_num_results, status: r.status};
                }
            """, {'base': CNSTRC_BASE, 'group': group, 'key': CNSTRC_KEY})

            total_products = first.get('total') or 0
            p(f"Total products in catalog: {total_products}")

            offset = 0
            group_rows = []

            while offset < total_products:
                batch = page.evaluate("""
                    async (args) => {
                        const url = args.base + '/browse/group_id/' + args.group +
                            '?key=' + args.key +
                            '&c=ciojs-client-2.65.0' +
                            '&offset=' + args.offset +
                            '&num_results_per_page=' + args.pageSize;
                        const r = await fetch(url, {headers: {'Accept': 'application/json'}});
                        const d = await r.json();
                        return d.response && d.response.results || [];
                    }
                """, {'base': CNSTRC_BASE, 'group': group, 'key': CNSTRC_KEY,
                      'offset': offset, 'pageSize': PAGE_SIZE})

                if not batch:
                    p(f"  offset={offset}: empty batch, stopping")
                    break

                rows = parse_results(batch, seen_keys)
                group_rows.extend(rows)
                p(f"  offset={offset:4d}: {len(batch):3d} products → {len(rows):4d} rows (running: {len(group_rows)})")
                offset += PAGE_SIZE
                page.wait_for_timeout(400)

            if group_rows:
                ins, skip = insert_products(TABLE, group_rows)
                total_ins += ins
                total_skip += skip
                p(f"Group {group}: {len(group_rows)} rows → {ins} inserted, {skip} skipped")
            else:
                p(f"Group {group}: no rows parsed")

        browser.close()

    p(f"\n{'='*50}")
    p(f"DONE! {total_ins} inserted, {total_skip} skipped (total processed)")


if __name__ == "__main__":
    main()
