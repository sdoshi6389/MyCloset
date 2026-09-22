"""Inspect J.Crew — find platform, product API, data structure, check for bot walls."""
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import time

BASE = "https://www.jcrew.com"

def p(*args):
    try:
        print(*args, flush=True)
    except UnicodeEncodeError:
        print(*(str(a).encode("ascii", "replace").decode() for a in args), flush=True)

api_calls = []
product_responses = []

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=False)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        locale="en-US", viewport={"width": 1280, "height": 900},
    )
    page = ctx.new_page()
    Stealth().apply_stealth_sync(page)

    def on_request(req):
        url = req.url
        if req.resource_type in ('xhr', 'fetch'):
            if not any(x in url for x in ['google', 'facebook', 'analytics', 'doubleclick',
                                           'onetrust', 'hotjar', 'tiktok', 'pinterest',
                                           'clarity.ms', 'sentry', 'newrelic', 'akam',
                                           'forter', 'px-cloud', 'klaviyo', 'gladly']):
                api_calls.append({'url': url[:500], 'method': req.method})

    def on_response(resp):
        url = resp.url
        if resp.status == 200:
            ct = resp.headers.get('content-type', '')
            if 'json' in ct:
                try:
                    body = resp.body().decode('utf-8', errors='replace')
                    if any(x in body for x in ['"product"', '"products"', '"price"',
                                                '"color"', '"sku"', '"variant"', '"name"']):
                        product_responses.append({'url': url[:400], 'body': body[:2000]})
                        p(f"  >>> JSON: {url[:180]}")
                except Exception:
                    pass

    page.on("request", on_request)
    page.on("response", on_response)

    p("Loading jcrew.com...")
    try:
        page.goto(BASE, timeout=60000)
    except Exception as e:
        p(f"goto error: {e}")
    page.wait_for_timeout(6000)
    p(f"URL: {page.url}")
    p(f"Title: {page.evaluate('() => document.title')[:80]}")

    blocked = page.evaluate("""
        () => {
            const t = document.body.innerText.toLowerCase();
            return {
                pressHold: t.includes('press & hold') || t.includes('press and hold'),
                captcha: document.documentElement.outerHTML.toLowerCase().includes('captcha'),
                accessDenied: t.includes('access denied'),
                handsFull: t.includes('hands full') || t.includes('sit tight'),
            };
        }
    """)
    p(f"Bot-wall check: {blocked}")

    platform = page.evaluate("""
        () => ({
            nextData: !!document.getElementById('__NEXT_DATA__'),
            shopify: !!(window.Shopify || document.querySelector('script[src*="shopify"]')),
            demandware: !!document.querySelector('script[src*="demandware"]') || location.href.includes('demandware'),
            isNextJsRSC: !!document.querySelector('script[src*="_next"]'),
        })
    """)
    p(f"Platform: {platform}")

    # J.Crew is owned by the same corporate family as Madewell; historically SFCC/Demandware
    demandware = page.evaluate("""
        () => {
            const scripts = [...document.querySelectorAll('script[src]')].map(s => s.src);
            return scripts.filter(s => s.includes('demandware') || s.includes('cquotient') || s.includes('dwstatic'));
        }
    """)
    p(f"Demandware-related scripts: {demandware}")

    dom = page.evaluate("""
        () => {
            const tests = {
                '[data-pid]': '[data-pid]',
                '[class*="product-tile"]': '[class*="product-tile"]',
                '[class*="product-card"]': '[class*="product-card"]',
                'a[href*="/p/"]': 'a[href*="/p/"]',
                'img': 'img',
            };
            const res = {};
            for (const [k, sel] of Object.entries(tests)) res[k] = document.querySelectorAll(sel).length;
            return res;
        }
    """)
    p(f"\nDOM selectors (homepage): {dom}")

    p(f"\n\nAll API calls ({len(api_calls)}):")
    for c in api_calls[:30]:
        p(f"  [{c['method']}] {c['url']}")

    p(f"\nProduct JSON responses ({len(product_responses)}):")
    for r in product_responses[:4]:
        p(f"\n[{r['url'][:200]}]")
        p(f"  {r['body'][:600]}")

    time.sleep(2)
    browser.close()
    p("\nINSPECT_DONE")
