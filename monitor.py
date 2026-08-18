#!/usr/bin/env python3
"""
hoopwatch — tells you when a basketball card box is buyable at or near MSRP.

Core idea: Topps' own store sells at MSRP. Resellers don't. So:
  - Anything in stock on Topps direct, inside your price range, is a BUY.
  - Anything on a reseller is a BUY only if it's within your % over MSRP.
  - Reseller prices are also used to estimate the resale gap, so the alert
    can tell you roughly what the box is worth above what you'd pay.

Sends Telegram alerts. Buy alerts only — no chatter.
Runs unattended on a schedule; state.json makes it alert on change only.

CHANGES IN THIS VERSION
  1. Silence now means something. A source that starts failing sends you a
     message, and so does one that recovers. A weekly "still alive" note
     confirms the pipe works even when nothing is for sale.
  2. Browser-shaped requests, to get past the 403 blocks from Dave & Adam's
     and Steel City. Headers only — no extra libraries.
  3. MSRP is never learned from loose page text, only from the store's own
     structured product data. A shipping fee can no longer become your
     baseline and quietly bend every buy limit built on it.

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
     HOOPWATCH_TEST=1  -> send one test message and exit (proves Telegram)
"""

import datetime
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, "products.json")
STATE_FILE = os.path.join(HERE, "state.json")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TEST_MODE = os.environ.get("HOOPWATCH_TEST", "").strip() == "1"

HEARTBEAT_DAYS = 7

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")

# A bare urllib request looks nothing like a browser, which is what most
# storefront blockers key on. These headers are what a real Chrome tab sends.
# Accept-Encoding is pinned to identity on purpose: urllib will not unzip a
# compressed reply, and asking for gzip here would hand us binary garbage
# that reads as an empty page.
BROWSER_HEADERS = {
    "User-Agent": UA,
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-CH-UA": '"Chromium";v="127", "Not)A;Brand";v="99"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"macOS"',
    "Cache-Control": "max-age=0",
    "Connection": "keep-alive",
}

# Structured product data is checked before visible text. On a storefront the
# biggest dollar figure on the page is often a related product, not this one.
JSONLD_PRICE = re.compile(r'"price"\s*:\s*"?([0-9][0-9,]*\.?[0-9]{0,2})"?')
META_PRICE = re.compile(
    r'<meta[^>]+(?:og:price:amount|product:price:amount|itemprop=["\']price["\'])'
    r'[^>]+content=["\']([0-9][0-9,]*\.?[0-9]{0,2})["\']', re.I)
TEXT_PRICE = re.compile(r"\$\s?([0-9][0-9,]*\.?[0-9]{0,2})")
LAUNCH_HREF = re.compile(r'href=["\'](/en-US/launch/[a-z0-9\-]+)["\']', re.I)

# "launch closed" / "closed on" matter: a closed EQL page still carries
# "Pre-Order" in the PRODUCT TITLE. Treating that as a buy signal reported a
# launch that had ended two weeks earlier. Title text is not a button.
SOLD_OUT = ["sold out", "out of stock", "item isn't available", "notify me",
            "currently unavailable", "coming soon", "back in stock soon",
            "launch closed", "closed on", "launch has now closed",
            "has now closed", "entries closed"]

# Real, clickable actions only. "pre order" was removed deliberately — it
# appears in product names, not just buttons.
BUYABLE = ["add to cart", "buy now", "enter now", "enter launch",
           "enter for a chance", "add to bag", "cancel my entry"]


def log(m):
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    print(f"[{ts}] {m}", flush=True)


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def load_json(p, d):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return d


def save_json(p, d):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, sort_keys=True)
        f.write("\n")


def fetch(url, retries=3):
    """Return (html, error). error is None on success, else a short reason.

    Returning the reason instead of swallowing it is what makes a blocked
    site distinguishable from a quiet one further up.
    """
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=dict(BROWSER_HEADERS))
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", errors="ignore"), None
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            # A refusal is a decision, not a hiccup. Retrying an ordinary 403
            # just wastes time, but 429 and 5xx are worth another go.
            if e.code in (401, 403, 404, 410):
                break
            time.sleep(2 * (i + 1))
        except Exception as e:  # noqa: BLE001
            last = type(e).__name__
            time.sleep(2 * (i + 1))
    log(f"    fetch failed: {last}")
    return None, last or "unknown"


def clean(html):
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<!--.*?-->", " ", html)
    t = re.sub(r"(?s)<[^>]+>", " ", html)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&#039;", "'"),
                 ("&quot;", '"'), ("&rsquo;", "'"), ("&#8217;", "'")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip().lower()


def to_f(s):
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def extract_price(html, text, lo, hi):
    """Return (price, how). Structured data first, banded text second."""
    for rx in (JSONLD_PRICE, META_PRICE):
        for m in rx.finditer(html):
            v = to_f(m.group(1))
            if v is not None and lo <= v <= hi:
                return v, "structured"
    cands = sorted({v for v in (to_f(m.group(1))
                                for m in TEXT_PRICE.finditer(text))
                    if v is not None and lo <= v <= hi})
    return (cands[0], "text") if cands else (None, "none")


def is_available(text):
    """Sold-out language wins. Storefronts leave hidden cart buttons in the
    markup constantly, so a buy phrase alone is not evidence of stock."""
    blocked = [k for k in SOLD_OUT if k in text]
    if blocked:
        return False, blocked[0]
    hits = [k for k in BUYABLE if k in text]
    return (True, hits[0]) if hits else (False, "no buy button")


def notify(msg):
    if not BOT_TOKEN or not CHAT_ID:
        log("  !! no telegram creds; printing")
        print(msg)
        return False
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML",
        "disable_web_page_preview": "false"}).encode()
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
        log("  -> sent")
        return True
    except Exception as e:  # noqa: BLE001
        log(f"  !! telegram failed: {e}")
        return False


def money(v):
    return f"${v:,.0f}" if v is not None else "price unknown"


def discover(cfg, known_urls, index_html):
    """Pick up new basketball launches from the index we already fetched."""
    d = cfg.get("discovery", {})
    if not d.get("enabled") or not index_html:
        return []
    found = []
    for m in LAUNCH_HREF.finditer(index_html):
        slug = m.group(1)
        low = slug.lower()
        if not any(k in low for k in d.get("must_contain", [])):
            continue
        if any(k in low for k in d.get("must_not_contain", [])):
            continue
        url = "https://launches.topps.com" + slug
        if url not in known_urls:
            found.append(url)
    return sorted(set(found))


def report_health(state, failures, checked_labels):
    """Tell the user when a source starts failing and when it comes back.

    Without this, a blocked storefront and a calm market produce the exact
    same experience: nothing on your phone.
    """
    prev_bad = set(state.get("_failing", []))
    now_bad = set(failures)

    started = sorted(now_bad - prev_bad)
    recovered = sorted((prev_bad - now_bad) & set(checked_labels))

    if started:
        lines = ["⚠️ <b>hoopwatch — source not reachable</b>", ""]
        for lbl in started:
            lines.append(f"• {lbl} — {failures[lbl]}")
        lines.append("")
        lines.append("These are not being checked. A box could go buyable "
                     "there and you would not hear about it.")
        notify("\n".join(lines))

    if recovered:
        notify("✅ <b>hoopwatch — back online</b>\n\n"
               + "\n".join(f"• {lbl}" for lbl in recovered))

    state["_failing"] = sorted(now_bad)


def maybe_heartbeat(state, n_products, n_failing):
    """A weekly note proving the whole chain works, so quiet reads as quiet."""
    last = state.get("_heartbeat")
    now = now_utc()
    if last:
        try:
            prev = datetime.datetime.fromisoformat(last)
            if (now - prev).days < HEARTBEAT_DAYS:
                return
        except ValueError:
            pass
    msg = ["💤 <b>hoopwatch weekly check-in</b>", "",
           f"Watching {n_products} product(s). Nothing buyable at or near "
           f"MSRP right now."]
    if n_failing:
        msg.append(f"{n_failing} source(s) unreachable — see earlier warning.")
    msg.append("")
    msg.append("You'll get a BUY alert the moment that changes.")
    notify("\n".join(msg))
    state["_heartbeat"] = now.isoformat(timespec="seconds")


def main():
    if TEST_MODE:
        ok = notify("🏀 <b>hoopwatch test</b>\n\nIf you're reading this on "
                    "your phone, alerts work. Nothing else to do.")
        log(f"test message sent: {ok}")
        return 0 if ok else 1

    cfg = load_json(CONFIG_FILE, {})
    state = load_json(STATE_FILE, {})
    s = cfg.get("settings", {})
    lo_msrp = s.get("msrp_min", 300)
    hi_msrp = s.get("msrp_max", 4000)
    over_pct = s.get("max_over_msrp_pct", 15)
    gap_pct = s.get("min_reseller_gap_pct", 20)

    products = list(cfg.get("products", []))
    known = {src["url"] for p in products for src in p["sources"]}

    failures = {}
    checked_labels = []

    # Launches listed as live on the index are trusted over page-text
    # guessing. Anything not on that list cannot be a live EQL window.
    index_url = cfg.get("discovery", {}).get("index_url", "")
    index_html, index_err = fetch(index_url) if index_url else (None, None)
    checked_labels.append("Topps launch index")
    if index_err:
        failures["Topps launch index"] = index_err
        live_now = set()
    else:
        # Reuse the HTML already in hand rather than fetching the index twice.
        live_now = set(_live_from_html(index_html, cfg))
    log(f"Live basketball launches on index: {len(live_now)}")

    # Auto-pick-up of new basketball launches, so the list doesn't go stale.
    for url in discover(cfg, known, index_html):
        slug = url.rsplit("/", 1)[-1].replace("-", " ").title()
        log(f"NEW product discovered: {slug}")
        products.append({"name": f"{slug} (auto)", "msrp": None,
                         "sources": [{"label": "Topps (official)",
                                      "url": url, "role": "msrp"}]})
        state.setdefault("_discovered", []).append(url)

    alerts = []

    for p in products:
        name = p["name"]
        msrp = p.get("msrp")
        log(f"Product: {name}")

        readings = []
        for src in p["sources"]:
            label = f"{name} :: {src['label']}"
            checked_labels.append(label)
            html, err = fetch(src["url"])
            if html is None:
                failures[label] = err
                continue
            text = clean(html)
            avail, why = is_available(text)
            if "launches.topps.com" in src["url"]:
                if src["url"] in live_now:
                    avail, why = True, "live on Topps launch index"
                elif live_now:
                    # Index loaded fine and this launch wasn't on it.
                    avail, why = False, "not listed as live"
            # Band generously; msrp filtering happens after.
            price, how = extract_price(html, text, lo_msrp * 0.5, hi_msrp * 3)
            readings.append({**src, "available": avail, "why": why,
                             "price": price, "how": how})
            log(f"    {src['label']}: avail={avail} ({why}) {money(price)} [{how}]")

        # Topps direct price defines MSRP when we don't already know it —
        # but only from structured product data. A number scraped out of
        # visible text might be shipping, a bundle, or a neighbouring item,
        # and a wrong MSRP silently bends every buy limit built on top of it.
        for r in readings:
            if r["role"] == "msrp" and r["price"] and msrp is None:
                if r["how"] != "structured":
                    log(f"    not learning MSRP from {r['how']} — "
                        f"{money(r['price'])} unverified")
                    continue
                if lo_msrp <= r["price"] <= hi_msrp:
                    msrp = r["price"]
                    log(f"    learned MSRP = {money(msrp)}")

        if msrp is None:
            log("    no trusted MSRP — reseller limits can't be applied")

        if msrp is not None and not (lo_msrp <= msrp <= hi_msrp):
            log(f"    skip — MSRP {money(msrp)} outside ${lo_msrp}-${hi_msrp}")
            continue

        ceiling = msrp * (1 + over_pct / 100) if msrp else None
        asks = [r["price"] for r in readings
                if r["role"] == "market" and r["price"]]
        reseller = min(asks) if asks else None

        for r in readings:
            key = f"{name} :: {r['label']}"
            prev = state.get(key, {})

            if r["role"] == "msrp":
                # Topps sells at MSRP by definition. In stock = buy.
                buy = r["available"] and (r["price"] is None or
                                          lo_msrp <= r["price"] <= hi_msrp)
                pay = r["price"] if r["price"] else msrp
            else:
                buy = bool(r["available"] and r["price"] and ceiling
                           and r["price"] <= ceiling)
                pay = r["price"]

            if buy and not prev.get("buy"):
                lines = [f"🏀 <b>BUY — {name}</b>",
                         f"{r['label']}: <b>{money(pay)}</b>"]
                if msrp:
                    if pay and pay > msrp:
                        lines.append(f"MSRP {money(msrp)} · you're "
                                     f"{(pay - msrp) / msrp * 100:.0f}% over "
                                     f"(limit {over_pct}%)")
                    else:
                        lines.append(f"At MSRP ({money(msrp)})")
                if reseller and pay and reseller > pay * (1 + gap_pct / 100):
                    lines.append(f"Resellers asking ~{money(reseller)} → "
                                 f"gap ≈ <b>{money(reseller - pay)}</b>")
                lines.append(f"\n{r['url']}")
                alerts.append("\n".join(lines))

            prev.update({"buy": buy, "price": r["price"],
                         "available": r["available"]})
            state[key] = prev

        if msrp and p.get("msrp") is None:
            state.setdefault("_learned_msrp", {})[name] = msrp

    for a in alerts:
        notify(a)

    report_health(state, failures, checked_labels)
    if not alerts:
        maybe_heartbeat(state, len(products), len(failures))

    save_json(STATE_FILE, state)
    log(f"Done. {len(alerts)} buy alert(s), {len(failures)} unreachable source(s).")
    return 0


def _live_from_html(html, cfg):
    """Live-launch links, read from index HTML we already have."""
    if not html:
        return []
    d = cfg.get("discovery", {})
    low_html = html.lower()
    for cutoff in ("past launches", "closed launches", "previous launches",
                   "recent launches"):
        i = low_html.find(cutoff)
        if i != -1:
            html = html[:i]
            low_html = low_html[:i]
            break
    if "live launches" not in low_html:
        return []
    keep = set(d.get("must_contain", []))
    drop = set(d.get("must_not_contain", []))
    live = []
    for m in LAUNCH_HREF.finditer(html):
        slug = m.group(1)
        low = slug.lower()
        if keep and not any(k in low for k in keep):
            continue
        if any(k in low for k in drop):
            continue
        live.append("https://launches.topps.com" + slug)
    return sorted(set(live))


if __name__ == "__main__":
    sys.exit(main())
