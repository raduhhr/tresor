#!/usr/bin/env python3
"""
steam-free-notifier v3.0 — simplified
Sources: Steam search API, Epic freeGamesPromotions API, GamerPower API
"""

import requests
import os
import json
import sys
import re
import time
from datetime import datetime

# =====================================================================
#  CONFIGURATION
# =====================================================================

WEBHOOK = os.getenv("DISCORD_WEBHOOK")

if not WEBHOOK:
    try:
        with open("/etc/cron.d/steam-free-notifier") as f:
            content = f.read()
            m = re.search(r"DISCORD_WEBHOOK=(\S+)", content)
            if m:
                WEBHOOK = m.group(1).strip("'\"")  # strip quotes from cron template
                os.environ["DISCORD_WEBHOOK"] = WEBHOOK
    except Exception:
        WEBHOOK = None

CACHE = "/opt/steam-free-notifier/seen.json"
CACHE_MAX_SIZE = 2000
HTTP_TIMEOUT = 20

STEAM_SEARCH_URL = "https://store.steampowered.com/search/results/?query&specials=1&maxprice=free&infinite=1"
EPIC_URL = "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US"
GAMERPOWER_URL = "https://www.gamerpower.com/api/giveaways?type=game&sort-by=date"

STEAM_TITLE_BLOCKLIST = [
    "soundtrack", "dlc", "add-on", "addon", "pack", "starter pack",
    "season pass", "expansion", "cosmetic", "skin", "weapon",
    "bundle", "gift", "demo", "test server", "beta",
]

# =====================================================================
#  HTTP SESSION
# =====================================================================

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "steam-free-notifier/3.0 (selfhosted bot)",
    "Accept": "*/*",
})

try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    retry = Retry(
        total=3, connect=3, read=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    SESSION.mount("https://", adapter)
    SESSION.mount("http://", adapter)
except Exception:
    pass


def http_get(url, headers=None, timeout=HTTP_TIMEOUT):
    r = SESSION.get(url, headers=headers, timeout=timeout)
    if r.status_code == 429:
        ra = r.headers.get("Retry-After")
        sleep_s = int(ra) if ra and ra.isdigit() else 15
        print(f"[HTTP] 429 rate limited, sleeping {sleep_s}s: {url[:80]}")
        time.sleep(sleep_s)
    return r


def http_post(url, payload, timeout=HTTP_TIMEOUT):
    return SESSION.post(url, json=payload, timeout=timeout)


# =====================================================================
#  UTILS
# =====================================================================

def safe_text(s, max_len):
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s.replace("\r", " ").replace("\n", " ")).strip()
    s = "".join(ch for ch in s if ch >= " " or ch == "\u200b")
    return s[:max_len - 1] + "…" if len(s) > max_len else s


def looks_like_junk(title):
    t = (title or "").lower()
    return any(k in t for k in STEAM_TITLE_BLOCKLIST)


def normalize_steam_url(url):
    if not url:
        return url
    url = url.split("?")[0].rstrip("/")
    m = re.match(r"(https://store\.steampowered\.com/(app|sub)/\d+)", url)
    return m.group(1) if m else url


# =====================================================================
#  STEAM — search API for -100% discounted games + appdetails validation
# =====================================================================

STEAM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://store.steampowered.com/",
}


def steam_app_is_paid_to_free(appid):
    """Validate via appdetails: must be type=game, original price > 0, current = 0."""
    try:
        r = http_get(f"https://store.steampowered.com/api/appdetails/?appids={appid}", timeout=10)
        data = r.json()
        blob = data.get(str(appid), {})
        if not blob.get("success"):
            return False
        d = blob.get("data", {})
        if (d.get("type") or "").lower() != "game":
            return False
        po = d.get("price_overview") or {}
        final = po.get("final")
        initial = po.get("initial")
        if final is None or initial is None:
            return False
        return final == 0 and initial > 0
    except Exception:
        return False


def fetch_steam():
    """Paginate Steam search for -100% specials, validate each hit."""
    from bs4 import BeautifulSoup

    games = []
    seen_ids = set()

    for page in range(5):  # 5 pages max, plenty for free promos
        start = page * 50
        url = f"{STEAM_SEARCH_URL}&start={start}&count=50"

        try:
            r = http_get(url, headers=STEAM_HEADERS)
            r.raise_for_status()
            html = (r.json().get("results_html") or "").strip()
            if not html:
                break

            soup = BeautifulSoup(html, "html.parser")
            rows = soup.select("a.search_result_row")
            if not rows:
                break

            for row in rows:
                title_el = row.select_one(".title")
                discount_el = row.select_one(".discount_pct")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                if not (discount_el and "-100%" in discount_el.get_text(strip=True)):
                    continue
                if looks_like_junk(title):
                    continue

                link = (row.get("href") or "").split("?")[0]
                m = re.search(r"/app/(\d+)", link)
                if not m:
                    continue

                appid = m.group(1)
                if appid in seen_ids:
                    continue
                seen_ids.add(appid)

                if not steam_app_is_paid_to_free(appid):
                    continue

                norm = normalize_steam_url(link)
                games.append({"name": title, "store": norm, "platform": "Steam"})
                time.sleep(0.3)

            time.sleep(0.5)

        except Exception as e:
            print(f"[Steam] Page {page} failed: {e}")
            continue

    print(f"[Steam] Found {len(games)} validated paid→free games.")
    return games


# =====================================================================
#  EPIC — official freeGamesPromotions API
# =====================================================================

def fetch_epic():
    games = []
    try:
        print("[Epic] Fetching free games promotions...")
        r = http_get(EPIC_URL, headers={"Accept": "application/json"})
        if r.status_code == 429:
            print("[Epic] Rate limited, skipping.")
            return []
        r.raise_for_status()

        elements = (
            r.json()
            .get("data", {})
            .get("Catalog", {})
            .get("searchStore", {})
            .get("elements", [])
        )

        for g in elements:
            try:
                # Must be currently free (active 100% promo)
                if not _epic_is_free_now(g):
                    continue
                # Skip DLC/add-ons
                ot = (g.get("offerType") or "").upper()
                if ot in ("ADD_ON", "DLC", "IN_GAME_ADD_ON"):
                    continue
                # Must have been paid (originalPrice > 0)
                if not _epic_is_paid_to_free(g):
                    continue

                title = g.get("title") or "Unknown Epic Game"
                link = _epic_build_link(g)
                until = _epic_free_until(g)

                item = {"name": title, "store": link, "platform": "Epic Games"}
                if until:
                    item["free_until"] = until
                games.append(item)

            except Exception as e:
                print(f"[Epic] Error processing element: {e}")

    except Exception as e:
        print(f"[Epic] Request failed: {e}")

    print(f"[Epic] Found {len(games)} free-to-keep games.")
    return games


def _epic_is_free_now(game):
    for block in (game.get("promotions") or {}).get("promotionalOffers") or []:
        for offer in block.get("promotionalOffers") or []:
            ds = offer.get("discountSetting") or {}
            if ds.get("discountType") == "PERCENTAGE" and ds.get("discountPercentage") == 100:
                return True
    return False


def _epic_free_until(game):
    for block in (game.get("promotions") or {}).get("promotionalOffers") or []:
        for offer in block.get("promotionalOffers") or []:
            ds = offer.get("discountSetting") or {}
            if ds.get("discountType") == "PERCENTAGE" and ds.get("discountPercentage") == 100:
                return offer.get("endDate")
    return None


def _epic_is_paid_to_free(game):
    try:
        tp = (game.get("price") or {}).get("totalPrice") or {}
        return tp.get("discountPrice") == 0 and (tp.get("originalPrice") or 0) > 0
    except Exception:
        return False


def _epic_extract_slug(game):
    candidates = []
    if game.get("productSlug"):
        slug = game["productSlug"].split("/")[-1]
        candidates.append(slug)
    for key in ("catalogNs", "offerMappings"):
        for m in (game.get(key) or {}).get("mappings", []) if key == "catalogNs" else (game.get(key) or []):
            if m.get("pageSlug"):
                candidates.append(m["pageSlug"])
    if game.get("urlSlug"):
        candidates.append(game["urlSlug"])

    for slug in candidates:
        if not slug:
            continue
        if re.match(r"^[0-9a-f]{16,}$", slug.lower()):
            continue
        if re.match(r"^[0-9]+$", slug):
            continue
        if re.match(r"^[a-z0-9-]+$", slug.lower()):
            return slug
    return None


def _epic_build_link(game):
    slug = _epic_extract_slug(game)
    return f"https://store.epicgames.com/p/{slug}" if slug else "https://store.epicgames.com/en-US/free-games"


# =====================================================================
#  GAMERPOWER — aggregator API (catches stuff the direct scrapers miss)
# =====================================================================

def fetch_gamerpower():
    """GamerPower aggregates free game giveaways. Filter to Steam + Epic only."""
    games = []
    try:
        print("[GamerPower] Fetching giveaways...")
        r = http_get(GAMERPOWER_URL, timeout=15)
        if r.status_code == 429:
            print("[GamerPower] Rate limited, skipping.")
            return []
        if r.status_code != 200:
            print(f"[GamerPower] HTTP {r.status_code}, skipping.")
            return []

        data = r.json()
        if not isinstance(data, list):
            return []

        for item in data:
            platforms = (item.get("platforms") or "").lower()
            giveaway_type = (item.get("type") or "").lower()

            # Only want actual full games on Steam or Epic
            if giveaway_type != "game":
                continue

            title = item.get("title") or ""
            # GamerPower appends "(Platform) Giveaway" to titles — strip it
            title = re.sub(r"\s*\((?:Steam|Epic Games|PC)\)\s*Giveaway\s*$", "", title, flags=re.IGNORECASE).strip()
            title = re.sub(r"\s*Giveaway\s*$", "", title, flags=re.IGNORECASE).strip()
            url = item.get("open_giveaway_url") or item.get("giveaway_url") or ""

            if looks_like_junk(title):
                continue

            if "steam" in platforms:
                # Try to extract a direct Steam store link
                store_url = _gamerpower_find_steam_link(item)
                if store_url:
                    games.append({"name": title, "store": store_url, "platform": "Steam"})

            elif "epic" in platforms:
                store_url = _gamerpower_find_epic_link(item)
                if store_url:
                    games.append({"name": title, "store": store_url, "platform": "Epic Games"})

    except Exception as e:
        print(f"[GamerPower] Failed: {e}")

    print(f"[GamerPower] Found {len(games)} Steam/Epic giveaways.")
    return games


def _gamerpower_find_steam_link(item):
    """Extract a clean Steam store URL from GamerPower item."""
    for field in ("open_giveaway_url", "giveaway_url", "description"):
        val = item.get(field) or ""
        m = re.search(r"https?://store\.steampowered\.com/app/(\d+)", val)
        if m:
            return f"https://store.steampowered.com/app/{m.group(1)}"
    # Fallback: return the giveaway URL (usually redirects to Steam)
    url = item.get("open_giveaway_url") or ""
    if "steampowered.com" in url:
        return normalize_steam_url(url)
    return url if url else None


def _gamerpower_find_epic_link(item):
    """Extract Epic store URL from GamerPower item."""
    for field in ("open_giveaway_url", "giveaway_url", "description"):
        val = item.get(field) or ""
        m = re.search(r"https?://store\.epicgames\.com/\S+", val)
        if m:
            return m.group(0).rstrip(".,;)")
    return item.get("open_giveaway_url") or None


# =====================================================================
#  CACHE
# =====================================================================

def load_seen():
    try:
        with open(CACHE, encoding="utf-8") as f:
            data = json.load(f)
            return set(data) if isinstance(data, list) else set()
    except FileNotFoundError:
        return set()
    except Exception as e:
        print(f"[Cache] Load failed: {e}")
        return set()


def save_seen(seen):
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    if len(seen) > CACHE_MAX_SIZE:
        seen = set(sorted(seen)[-CACHE_MAX_SIZE:])
        print(f"[Cache] Trimmed to {len(seen)} entries")
    tmp = CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sorted(list(seen)), f, indent=2)
    os.replace(tmp, CACHE)


# =====================================================================
#  DISCORD NOTIFICATION
# =====================================================================

PLATFORM_CONFIG = {
    "Steam": {
        "emoji": "🎮", "color": 0x1b2838,
        "icon": "https://cdn.cloudflare.steamstatic.com/steamcommunity/public/images/apps/steam/steamcommunity_32.png",
    },
    "Epic Games": {
        "emoji": "🎯", "color": 0x0078f2,
        "icon": "https://static-assets-prod.epicgames.com/epic-store/static/favicon.ico",
    },
}


def get_game_image(game):
    if game.get("platform") == "Steam":
        m = re.search(r"/app/(\d+)", game.get("store", ""))
        if m:
            return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{m.group(1)}/header.jpg"
    return None


def notify(game):
    """Send Discord embed. Returns True only if Discord accepted it."""
    if not WEBHOOK:
        print("⚠️  No DISCORD_WEBHOOK set, skipping.")
        return False

    platform = game.get("platform", "Unknown")
    name = safe_text(game.get("name", "Unknown"), 200)
    url = (game.get("store") or "").strip()

    cfg = PLATFORM_CONFIG.get(platform, {"emoji": "🎁", "color": 0x5865F2, "icon": None})
    image = get_game_image(game)

    until_line = ""
    if game.get("free_until"):
        until_line = f"\n\n⏳ Free until: `{safe_text(str(game['free_until']), 60)}`"

    embed = {
        "title": safe_text(f"{cfg['emoji']} {name}", 256),
        "description": safe_text(f"**Free to keep forever!**\n\n[🔗 Claim on {platform}]({url}){until_line}", 4096),
        "url": url,
        "color": cfg["color"],
        "footer": {"text": platform},
        "timestamp": datetime.utcnow().isoformat(),
    }
    if cfg.get("icon"):
        embed["footer"]["icon_url"] = cfg["icon"]
    if image:
        embed["image"] = {"url": image}

    payload = {
        "username": "Captain Hook",
        "avatar_url": "https://em-content.zobj.net/source/apple/391/hook_1fa9d.png",
        "embeds": [embed],
    }

    try:
        resp = http_post(WEBHOOK, payload, timeout=10)
        if resp.status_code not in (200, 204):
            print(f"⚠️  Discord POST failed ({resp.status_code}): {resp.text[:300]}")
            return False
        print(f"✅ Notified: {name} ({platform})")
        return True
    except Exception as e:
        print(f"⚠️  Notification failed: {e}")
        return False


# =====================================================================
#  MAIN
# =====================================================================

def make_key(game):
    plat = game.get("platform", "Unknown")
    url = game.get("store", "")
    return f"{plat}::{url}" if url else f"{plat}::{game.get('name')}"


def main():
    print(f"[{datetime.now()}] Starting free games scan...")

    seen = load_seen()
    print(f"[Cache] {len(seen)} previously seen games.")

    all_games = []
    sources_ok = 0

    # --- Steam ---
    try:
        all_games.extend(fetch_steam())
        sources_ok += 1
    except Exception as e:
        print(f"[Steam] FATAL: {e}")

    # --- Epic ---
    try:
        all_games.extend(fetch_epic())
        sources_ok += 1
    except Exception as e:
        print(f"[Epic] FATAL: {e}")

    # --- GamerPower (supplementary) ---
    try:
        all_games.extend(fetch_gamerpower())
        sources_ok += 1
    except Exception as e:
        print(f"[GamerPower] FATAL: {e}")

    if sources_ok == 0:
        print("ERROR: All sources failed.", file=sys.stderr)
        return 2

    # Dedupe by platform::url
    deduped = []
    seen_keys = set()
    for g in all_games:
        if g.get("platform") == "Steam":
            g["store"] = normalize_steam_url(g["store"])
        k = make_key(g)
        if k not in seen_keys:
            seen_keys.add(k)
            deduped.append(g)

    print(f"[All] {len(deduped)} games after dedupe.")

    new = [g for g in deduped if make_key(g) not in seen]

    if not new:
        print("✓ No new free-to-keep games.")
    else:
        print(f"[New] {len(new)} new games to notify!")
        for g in new:
            print(f"  → {g.get('name', '?')} ({g.get('platform')})")
            if notify(g):
                seen.add(make_key(g))
            time.sleep(1)

    save_seen(seen)
    print(f"[{datetime.now()}] Scan complete.")
    return 0


if __name__ == "__main__":
    rc = 0
    try:
        rc = main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        rc = 1
    sys.exit(rc)