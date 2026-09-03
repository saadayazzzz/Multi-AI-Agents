"""Agent 2 - Scrape & store.

For each site discovered by agent 1:
  1. fetch the homepage (robots-aware, rate-limited)
  2. follow on-site product / collection links
  3. have Claude extract structured product records from the page text
  4. derive a brand profile (palette hints, tone, positioning) from the homepage
  5. persist everything to Postgres
"""
from __future__ import annotations

import json
from typing import Any

from bs4 import BeautifulSoup
from psycopg.types.json import Jsonb

from agents.llm import json_out
from agents.reporter import report
from config import settings
from db import get_conn
from scraper import PoliteFetcher

_PRODUCT_KEYWORDS = ("/product", "/products/", "/shop", "/collections", "/p/", "/item")

_EXTRACT_SYSTEM = (
    "You extract structured product data from the visible text of a skincare or "
    "cosmetics web page. Only report what is present in the text. If the page is "
    "not a product page, return an empty products list."
)

_PRODUCT_SCHEMA = {
    "type": "object",
    "properties": {
        "is_product_page": {"type": "boolean"},
        "products": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "brand": {"type": "string"},
                    "category": {"type": "string"},
                    "subcategory": {"type": "string"},
                    "description": {"type": "string"},
                    "price": {"type": ["number", "null"]},
                    "currency": {"type": "string"},
                    "size": {"type": "string"},
                    "ingredients": {"type": "array", "items": {"type": "string"}},
                    "benefits": {"type": "array", "items": {"type": "string"}},
                    "skin_types": {"type": "array", "items": {"type": "string"}},
                    "rating": {"type": ["number", "null"]},
                },
                "required": [
                    "name", "brand", "category", "subcategory", "description",
                    "price", "currency", "size", "ingredients", "benefits",
                    "skin_types", "rating",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["is_product_page", "products"],
    "additionalProperties": False,
}

_BRAND_SCHEMA = {
    "type": "object",
    "properties": {
        "palette": {"type": "array", "items": {"type": "string"}},
        "typography": {
            "type": "object",
            "properties": {"headings": {"type": "string"}, "body": {"type": "string"}},
            "required": ["headings", "body"],
            "additionalProperties": False,
        },
        "tone": {"type": "string"},
        "tagline_samples": {"type": "array", "items": {"type": "string"}},
        "positioning": {"type": "string"},
        "price_tier": {"type": "string", "enum": ["budget", "mid", "premium", "luxury"]},
    },
    "required": ["palette", "typography", "tone", "tagline_samples", "positioning", "price_tier"],
    "additionalProperties": False,
}


def _store_page(conn, site_id: int, url: str, kind: str, status: int, text: str) -> None:
    conn.execute(
        """
        INSERT INTO pages (site_id, url, kind, http_status, raw_text)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (site_id, url) DO UPDATE SET
            kind = EXCLUDED.kind, http_status = EXCLUDED.http_status,
            raw_text = EXCLUDED.raw_text, fetched_at = now()
        """,
        (site_id, url, kind, status, text),
    )


def _store_products(conn, site_id: int, url: str, products: list[dict[str, Any]]) -> int:
    n = 0
    for p in products:
        if not p.get("name"):
            continue
        conn.execute(
            """
            INSERT INTO products
                (site_id, source_url, name, brand, category, subcategory, description,
                 price, currency, size, ingredients, benefits, skin_types, rating, raw)
            VALUES
                (%(site_id)s, %(source_url)s, %(name)s, %(brand)s, %(category)s,
                 %(subcategory)s, %(description)s, %(price)s, %(currency)s, %(size)s,
                 %(ingredients)s, %(benefits)s, %(skin_types)s, %(rating)s, %(raw)s)
            ON CONFLICT (site_id, name, size) DO UPDATE SET
                price = EXCLUDED.price, description = EXCLUDED.description,
                ingredients = EXCLUDED.ingredients, benefits = EXCLUDED.benefits
            """,
            {
                "site_id": site_id,
                "source_url": p.get("source_url") or url,
                "name": p["name"],
                "brand": p.get("brand") or None,
                "category": (p.get("category") or "").lower() or None,
                "subcategory": p.get("subcategory") or None,
                "description": p.get("description") or None,
                "price": p.get("price"),
                "currency": p.get("currency") or None,
                "size": p.get("size") or "",
                "ingredients": p.get("ingredients") or [],
                "benefits": p.get("benefits") or [],
                "skin_types": p.get("skin_types") or [],
                "rating": p.get("rating"),
                "raw": Jsonb(p),
            },
        )
        n += 1
    return n


def _shopify_products(base: str, fetcher: PoliteFetcher) -> list[dict[str, Any]]:
    """Fast path: most beauty storefronts run Shopify and expose /products.json."""
    out: list[dict[str, Any]] = []
    for page in (1, 2, 3):
        data = fetcher.get_json(f"{base}/products.json?limit=250&page={page}")
        items = (data or {}).get("products") or []
        if not items:
            break
        for p in items:
            desc = " ".join(
                BeautifulSoup(p.get("body_html") or "", "html.parser").get_text(" ").split()
            )
            variant = (p.get("variants") or [{}])[0]
            size = variant.get("title") or ""
            if size in ("Default Title", None):
                size = ""
            out.append({
                "name": p.get("title"),
                "brand": p.get("vendor") or None,
                "category": (p.get("product_type") or "").lower() or None,
                "subcategory": None,
                "description": (desc[:2000] or None),
                "price": float(variant["price"]) if variant.get("price") else None,
                "currency": None,
                "size": size,
                "ingredients": [],
                "benefits": [],
                "skin_types": [],
                "rating": None,
                "image_url": (p.get("images") or [{}])[0].get("src"),
                "source_url": f"{base}/products/{p.get('handle', '')}",
                "tags": p.get("tags"),
            })
    return out


def _scrape_site(site: dict, fetcher: PoliteFetcher) -> None:
    site_id, base = site["id"], site["url"]
    report(f"agent2: scraping [{site_id}] {site['name']} ({base})")

    with get_conn() as conn:
        conn.execute("UPDATE sites SET status = 'scraping', error = NULL WHERE id = %s", (site_id,))

    home = fetcher.get(base)
    if home is None:
        with get_conn() as conn:
            conn.execute(
                "UPDATE sites SET status = 'failed', error = 'homepage unreachable' WHERE id = %s",
                (site_id,),
            )
        return

    home_text = fetcher.clean_text(home.text)
    links = fetcher.find_links(home.text, base, _PRODUCT_KEYWORDS)[: settings.max_pages_per_site]

    with get_conn() as conn:
        _store_page(conn, site_id, base, "home", home.status_code, home_text)

        # brand profile from the homepage
        try:
            brand = json_out(
                _EXTRACT_SYSTEM.replace("product data", "brand identity signals"),
                f"Homepage of {site['name']} ({base}). Infer the brand's visual and verbal "
                f"identity from this text. Guess hex colours from colour words if needed.\n\n{home_text}",
                _BRAND_SCHEMA,
            )
            conn.execute(
                """
                INSERT INTO brand_profiles
                    (site_id, palette, typography, tone, tagline_samples, positioning, price_tier, raw)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (site_id) DO UPDATE SET
                    palette = EXCLUDED.palette, typography = EXCLUDED.typography,
                    tone = EXCLUDED.tone, tagline_samples = EXCLUDED.tagline_samples,
                    positioning = EXCLUDED.positioning, price_tier = EXCLUDED.price_tier
                """,
                (
                    site_id, Jsonb(brand["palette"]), Jsonb(brand["typography"]),
                    brand["tone"], brand["tagline_samples"], brand["positioning"],
                    brand["price_tier"], Jsonb(brand),
                ),
            )
        except Exception as e:  # noqa: BLE001
            report(f"    brand profile failed: {e}")

    total = 0

    # Fast path: Shopify JSON feed (accurate, no LLM needed).
    shopify = _shopify_products(base, fetcher)
    if shopify:
        with get_conn() as conn:
            total += _store_products(conn, site_id, base, shopify)
        report(f"    shopify: stored {total} products via products.json")

    # Fallback: crawl candidate pages and let the model extract.
    if total == 0:
        for url in links:
            resp = fetcher.get(url)
            if resp is None:
                continue
            text = fetcher.clean_text(resp.text)
            try:
                data = json_out(
                    _EXTRACT_SYSTEM,
                    f"Page URL: {url}\n\nVisible text:\n{text}",
                    _PRODUCT_SCHEMA,
                )
            except Exception as e:  # noqa: BLE001
                report(f"    extract failed {url}: {e}")
                continue
            kind = "product" if data["is_product_page"] else "collection"
            with get_conn() as conn:
                _store_page(conn, site_id, url, kind, resp.status_code, text)
                total += _store_products(conn, site_id, url, data["products"])
        report(f"    stored {total} products from {len(links)} pages")

    with get_conn() as conn:
        conn.execute("UPDATE sites SET status = 'scraped' WHERE id = %s", (site_id,))


def scrape(limit: int | None = None) -> None:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, url FROM sites WHERE status IN ('discovered', 'failed') "
            "ORDER BY score DESC NULLS LAST, id LIMIT %s",
            (limit or settings.max_sites,),
        ).fetchall()

    if not rows:
        report("agent2: nothing to scrape (run agent 1 first)")
        return

    with PoliteFetcher() as fetcher:
        for site in rows:
            try:
                _scrape_site(site, fetcher)
            except Exception as e:  # noqa: BLE001
                report(f"    site failed: {e}")
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE sites SET status = 'failed', error = %s WHERE id = %s",
                        (str(e)[:500], site["id"]),
                    )


if __name__ == "__main__":
    scrape()
