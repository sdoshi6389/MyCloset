"""Club Monaco scraper — standard Shopify products.json via browser-context fetch.
Each product = one color (single Size variant dimension). Color name is embedded
in the tags[] array alongside category/season tags, so we match tags against a
known color-name set (scraped from the site's color_swatch metaobjects) to find it.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import json

from db_insert import insert_products, ensure_table

TABLE = "products_clubmonaco"
BASE  = "https://www.clubmonaco.com"
LIMIT = 250

COLOR_NAMES = {
    'Almond', 'Aloe', 'Antique White', 'Aqua', 'Army', 'Aster Pink', 'Azul', 'Banana', 'Basil',
    'Beige', 'Beige Mix', 'Birch', 'Birch Wood', 'Black', 'Black Base', 'Black Charcoal',
    'Black Cream', 'Black Denim', 'Black Grand Print', 'Black Grnd Stripe', 'Black Heather Grey',
    'Black Ivory', 'Black Mix', 'Black Olive', 'Black Shadow Print A', 'Black Stripe',
    'Blanc De Blanc', 'Blue', 'Blue Base', 'Blue Depths', 'Blue Haze', 'Blue Mix', 'Blue Opal',
    'Blue Print', 'Blue Stripe', 'Blue Topaz', 'Blue White Stripe', 'Blueberry Cream', 'Blush',
    'Bright White', 'Brown', 'Brown Mix', 'Brown Print', 'Brwon Mix', 'Burgundy', 'Burgundy Mix',
    'Burnt Orange', 'Butter Creme', 'Camel', 'Cannoli', 'Caramel', 'Carbon', 'Celestial Blue',
    'Cerulean Blue', 'Chambray Stripe', 'Champagne', 'Charcoal', 'Charcoal Base', 'Charcoal Heather',
    'Charcoal Mix', 'Chartreuse', 'Check - Black', 'Cherry', 'Chocolate', 'Cloud Pink',
    'Coastal Blue', 'Cool Grey', 'Coral', 'Cream', 'Cream Base', 'Cream Creme', 'Cream Pearl',
    'Crocodile', 'Dark Blue', 'Dark Blue Mix', 'Dark Brown', 'Dark Charcoal', 'Dark Green',
    'Dark Green Mix', 'Dark Grey', 'Dark Grey Mix', 'Dark Heather', 'Dark Navy', 'Dark Olive',
    'Dark Purple', 'Deep Chambray', 'Denim', 'Dk.Blue', 'Dk.Blue Mix', 'Dk.Green', 'Dk.Navy',
    'Dk.Purple', 'Doe', 'Dune', 'Dusk', 'Dusty Mauve', 'Dusty Olive', 'Dusty Pink', 'Dusty Rose',
    'Ebony', 'Eclipse', 'Ecru', 'Eggshell', 'Evergreen', 'Faded Jade', 'Fennel', 'Fern Green',
    'Flaxseed', 'Forrest', 'Foundation', 'French Blue', 'Fuchsia', 'Fuschia', 'Glacier', 'Glass',
    'Gold', 'Graphite Geo Print', 'Green', 'Green Base', 'Green Mix', 'Grey', 'Grey Grnd Stripe',
    'Grey Mist', 'Grey Mix', 'Gunmetal Black', 'Heather Blue', 'Heather Grey', 'Honey Wheat',
    'Horizon Blue', 'Hot Pink', 'Hunter', 'Indigo', 'Indigo Heather', 'Iron Grey', 'Ivory',
    'Ivory Dot', 'Ivory Mix', 'Khaki', 'Khaki Base', 'Khaki Mix', 'Khaki Stone', 'La Mer',
    'Lagoon', 'Latte', 'Lavender', 'Light Beige', 'Light Beige Mix', 'Light Blue',
    'Light Blue Base', 'Light Blue Mix', 'Light Brown', 'Light Brown Mix', 'Light Camel',
    'Light Denim', 'Light Gray', 'Light Green', 'Light Green Mix', 'Light Grey', 'Light Grey Mix',
    'Light Heather Grey', 'Light Khaki', 'Light Khaki Mix', 'Light Peach', 'Light Pink',
    'Light Purple', 'Light Purple Mix', 'Light Tan', 'Light Tan Mix', 'Light Yellow', 'Lt.Blue',
    'Lt.Denim', 'Mahogany', 'Maritime Navy', 'Maroon', 'Mauve', 'Med Grey Mix', 'Med Pewter',
    'Med.Blue Base', 'Med.Denim', 'Med.Grey Base', 'Med.Olive', 'Med.Purple', 'Medium Beige',
    'Medium Blue', 'Medium Blue Base', 'Medium Brown', 'Medium Denim', 'Medium Grey',
    'Medium Grey Base', 'Medium Heather Grey', 'Medium Olive', 'Medium Purple', 'Metallic',
    'Military Olive', 'Milk', 'Mint', 'Multi', 'Mushroom', 'Natural', 'Navy', 'Navy Base',
    'Navy Mix', 'Navy Print', 'Navy Stripe', 'Navy White Stripe', 'Neutral', 'New Chartreuse',
    'Night Fall', 'Oak', 'Oatmeal', 'Oatmeal Base', 'Oatmeal Heather', 'Oatmeal Mix', 'Oats',
    'Obsidian', 'Off White', 'Olive', 'Olive Drab', 'Olive Leaf', 'Olive Mix', 'Olive Pit',
    'Opal', 'Orange', 'Orange Mix', 'Oxford Blue', 'Pale Grey', 'Pale Heather Grey', 'Pale Pink',
    'Pale Rose', 'Pale Yellow', 'Paprika', 'Pattern', 'Peach', 'Peat Moss', 'Pecan Hthr',
    'Periwinkle', 'Petrol', 'Pink', 'Pink Mix', 'Pink Print', 'Plaid - Black', 'Port Blue',
    'Porto', 'Powder', 'Print', 'Pure White', 'Purple', 'Purple Base', 'Purple Mix',
    'Purple Print', 'Rain Print E', 'Red', 'Red Mix', 'Red Pattern', 'Rose', 'Ruby Wine', 'Sage',
    "Salt&Pepper Melange", 'Sand', 'Sand Dollar', 'Sandstone', 'Sea Glass', 'Sea Green',
    'Sea Spray', 'Sesame', 'Shell Blue', 'Silver', 'Silver Dove', 'Simply Taupe', 'Sky Light',
    'Slate Blue', 'Slate Grey', 'Snow White', 'Soft Blush', 'Soft Lavendar', 'Soft Lavender',
    'Soft Pearl', 'Soot Black', 'Steel Grey', 'Stone', 'Storm Dust', 'Straw', 'Stripe - Ivory',
    'Stripe - Light Blue', 'Stripe - Natural', 'Stripe - Orange', 'Sun Rise', 'Sunset',
    'Sweet Lilac', 'Tan', 'Tan Base', 'Tan Mix', 'Tan Stripe', 'Taupe', 'Teal', 'Terracotta',
    'Thyme', 'Toast Black Combo', 'Toasted Oat', 'Tortoise', 'Tortoise Amber', 'True Blue',
    'True Navy', 'Turquois Mix', 'Turtle Dove', 'Twighlight', 'Twilight Navy', 'Warm Camel',
    'Warm Sand', 'White', 'White Base', 'White Base Stripe', 'White Base Stripe #4',
    'White Grand Print', 'White Grand Stripe', 'White-Black', 'Wine', 'Wood Chip', 'Yellow',
    'Yellow Stripe',
}
COLOR_NAMES_LOWER = {c.lower(): c for c in COLOR_NAMES}


def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)


def find_color(tags):
    for tag in tags:
        match = COLOR_NAMES_LOWER.get(tag.strip().lower())
        if match:
            return match
    return ""


def parse_products(products):
    rows = []
    for prod in products:
        title = (prod.get("title") or "").strip()
        handle = prod.get("handle") or ""
        if not title or not handle:
            continue

        tags = prod.get("tags") or []
        color = find_color(tags)

        variants = prod.get("variants") or []
        price = ""
        if variants:
            try:
                price = f"${float(variants[0].get('price', 0)):.2f}"
            except (ValueError, TypeError):
                price = ""

        images = prod.get("images") or []
        image = images[0].get("src", "") if images else ""

        url = f"{BASE}/products/{handle}"

        rows.append({
            "title": title,
            "color": color,
            "price": price,
            "image": image,
            "url":   url,
        })
    return rows


def scrape_all(page):
    inserted = skipped = 0
    pg = 1
    while True:
        result = page.evaluate(f"""
            async () => {{
                const r = await fetch('/products.json?limit={LIMIT}&page={pg}');
                return await r.json();
            }}
        """)
        products = result.get("products") or []
        if not products:
            break

        rows = parse_products(products)
        ins, skip = insert_products(TABLE, rows) if rows else (0, 0)
        inserted += ins
        skipped  += skip
        p(f"  Page {pg}: {len(products)} products -> {len(rows)} rows -> {ins} inserted, {skip} skipped")

        if len(products) < LIMIT:
            break
        pg += 1

    return inserted, skipped


def main():
    p(f"Club Monaco scraper -> table: {TABLE}")
    ensure_table(TABLE)

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
        page = ctx.new_page()
        Stealth().apply_stealth_sync(page)

        p("Loading clubmonaco.com...")
        page.goto(BASE, timeout=60000)
        page.wait_for_timeout(5000)

        total_ins, total_skip = scrape_all(page)

        browser.close()

    p(f"\n{'='*60}")
    p(f"DONE! {total_ins} inserted, {total_skip} skipped")


if __name__ == "__main__":
    main()
