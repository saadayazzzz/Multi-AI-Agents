"""Agent 3 - Original brand + Next.js site.

Reads the aggregated market data collected by agents 1-2 and uses it to design a
NEW, original skincare/cosmetics brand: name, positioning, palette, voice, and a
synthesised catalogue. It then generates a runnable Next.js (App Router + TS +
Tailwind) project under OUTPUT_DIR/<slug>/.

Nothing scraped is copied verbatim - the scraped data informs pricing bands,
category mix, and ingredient vocabulary only. All names and copy are generated.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from agents.llm import generate_text, json_out, parse_file_blocks
from agents.reporter import report
from config import settings
from db import get_conn


# --------------------------------------------------------------------------- #
# 1. Aggregate what agents 1-2 collected
# --------------------------------------------------------------------------- #
def _market_summary() -> dict[str, Any]:
    with get_conn() as conn:
        categories = conn.execute(
            """
            SELECT category, COUNT(*) n,
                   ROUND(AVG(price)::numeric, 2) avg_price,
                   ROUND(MIN(price)::numeric, 2) min_price,
                   ROUND(MAX(price)::numeric, 2) max_price
            FROM products WHERE category IS NOT NULL AND price IS NOT NULL
            GROUP BY category ORDER BY n DESC LIMIT 20
            """
        ).fetchall()
        ingredients = conn.execute(
            """
            SELECT lower(ing) ing, COUNT(*) n
            FROM products, unnest(ingredients) ing
            GROUP BY 1 ORDER BY n DESC LIMIT 40
            """
        ).fetchall()
        benefits = conn.execute(
            """
            SELECT lower(b) benefit, COUNT(*) n
            FROM products, unnest(benefits) b
            GROUP BY 1 ORDER BY n DESC LIMIT 25
            """
        ).fetchall()
        tones = conn.execute(
            "SELECT s.name, bp.tone, bp.positioning, bp.price_tier, bp.tagline_samples "
            "FROM brand_profiles bp JOIN sites s ON s.id = bp.site_id"
        ).fetchall()
        totals = conn.execute(
            "SELECT COUNT(*) products, COUNT(DISTINCT site_id) sites FROM products"
        ).fetchone()

    return {
        "totals": totals,
        "categories": categories,
        "top_ingredients": [r["ing"] for r in ingredients],
        "top_benefits": [r["benefit"] for r in benefits],
        "competitor_tone": tones,
    }


# --------------------------------------------------------------------------- #
# 2. Design an original brand
# --------------------------------------------------------------------------- #
_BRAND_SYSTEM = (
    "You are a brand strategist and creative director for beauty startups. "
    "You design distinctive, original brands - never a clone of an existing one."
)

_BRAND_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "slug": {"type": "string", "pattern": "^[a-z0-9-]+$"},
        "tagline": {"type": "string"},
        "mission": {"type": "string"},
        "positioning": {"type": "string"},
        "target_customer": {"type": "string"},
        "price_tier": {"type": "string", "enum": ["budget", "mid", "premium", "luxury"]},
        "voice": {"type": "array", "items": {"type": "string"}},
        "palette": {
            "type": "object",
            "properties": {
                "bg": {"type": "string"}, "surface": {"type": "string"},
                "ink": {"type": "string"}, "primary": {"type": "string"},
                "accent": {"type": "string"}, "muted": {"type": "string"},
            },
            "required": ["bg", "surface", "ink", "primary", "accent", "muted"],
            "additionalProperties": False,
        },
        "typography": {
            "type": "object",
            "properties": {"headings": {"type": "string"}, "body": {"type": "string"}},
            "required": ["headings", "body"],
            "additionalProperties": False,
        },
        "product_lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "theme": {"type": "string"},
                },
                "required": ["name", "theme"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "name", "slug", "tagline", "mission", "positioning", "target_customer",
        "price_tier", "voice", "palette", "typography", "product_lines",
    ],
    "additionalProperties": False,
}

_CATALOG_SCHEMA = {
    "type": "object",
    "properties": {
        "products": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "pattern": "^[a-z0-9-]+$"},
                    "name": {"type": "string"},
                    "line": {"type": "string"},
                    "category": {"type": "string"},
                    "tagline": {"type": "string"},
                    "description": {"type": "string"},
                    "price": {"type": "number"},
                    "size": {"type": "string"},
                    "hero_ingredients": {"type": "array", "items": {"type": "string"}},
                    "benefits": {"type": "array", "items": {"type": "string"}},
                    "skin_types": {"type": "array", "items": {"type": "string"}},
                    "how_to_use": {"type": "string"},
                },
                "required": [
                    "slug", "name", "line", "category", "tagline", "description",
                    "price", "size", "hero_ingredients", "benefits", "skin_types",
                    "how_to_use",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["products"],
    "additionalProperties": False,
}


def _design_brand(summary: dict) -> dict:
    return json_out(
        _BRAND_SYSTEM,
        "Using this aggregated view of competitor skincare/cosmetics sites, design ONE "
        "original brand that fills a clear gap. Pick a memorable invented name (check it "
        "does not match any competitor listed). Ground the price tier and product mix in "
        "the data.\n\n" + json.dumps(summary, default=str, indent=2),
        _BRAND_SCHEMA,
        max_tokens=8000,
    )


def _build_catalog(brand: dict, summary: dict) -> list[dict]:
    data = json_out(
        _BRAND_SYSTEM,
        "Create a launch catalogue of 18-24 products for this brand. Spread them across "
        "the brand's product_lines and across the categories seen in the market data. "
        "Prices must sit in the brand's tier. Use the ingredient vocabulary from the "
        "market data where it fits, but all product names and copy must be original.\n\n"
        f"BRAND:\n{json.dumps(brand, indent=2)}\n\n"
        f"MARKET DATA:\n{json.dumps(summary, default=str, indent=2)}",
        _CATALOG_SCHEMA,
        max_tokens=20000,
    )
    return data["products"]


# --------------------------------------------------------------------------- #
# 3. Generate the Next.js project
# --------------------------------------------------------------------------- #
_CODE_SYSTEM = (
    "You are a senior front-end engineer. You write clean, type-safe Next.js 14 "
    "App Router code (TypeScript, Tailwind CSS v3, no other UI libraries).\n"
    "Rules:\n"
    "- Data comes from `@/lib/data`, which exports `brand`, `products`, `productLines`, "
    "and the `Product` type. Import from there; never redefine them.\n"
    "- Any file that uses onClick/onChange/useState/useEffect/useRouter or a browser "
    "API MUST start with the line: 'use client';\n"
    "- For navigation/filtering, prefer <a href> or next/link so page.tsx files stay "
    "server components. Do not put onClick on a server component.\n"
    "- `brand` fields are snake_case (brand.product_lines, brand.target_customer).\n"
    "- Every product has `image` (an absolute path string, e.g. /img/products/x.svg). "
    "Show it as the product photo everywhere a product appears - in ProductCard, the "
    "product grid, and the product detail page - with a plain <img> "
    '(className=\"w-full h-full object-cover\") inside an aspect-square wrapper. '
    "Never leave a product without its image.\n"
    "Output ONLY file blocks in this exact format, nothing else:\n"
    "=== FILE: relative/path ===\n<file contents>\n=== END FILE ===\n"
)

# tsconfig / next.config / postcss / tailwind are written deterministically below,
# so they are deliberately NOT in this list.
_SCAFFOLD_FILES = [
    "package.json", "app/globals.css", "app/layout.tsx",
    "lib/products.ts", "lib/brand.ts", ".gitignore", "README.md",
]
_COMPONENT_FILES = [
    "components/SiteHeader.tsx", "components/SiteFooter.tsx", "components/Hero.tsx",
    "components/ProductCard.tsx", "components/ProductGrid.tsx", "components/Newsletter.tsx",
]
_PAGE_FILES = [
    "app/page.tsx", "app/products/page.tsx", "app/products/[slug]/page.tsx",
    "app/about/page.tsx", "app/not-found.tsx",
]


def _codegen(prompt_files: list[str], brand: dict, extra: str = "") -> dict[str, str]:
    body = generate_text(
        _CODE_SYSTEM,
        f"BRAND SPEC (JSON):\n{json.dumps(brand, indent=2)}\n\n{extra}\n\n"
        f"Generate exactly these files, each as one file block:\n"
        + "\n".join(f"- {f}" for f in prompt_files),
        max_tokens=64000,
    )
    return parse_file_blocks(body)


def _data_module(brand: dict, catalog: list[dict]) -> str:
    return (
        "// AUTO-GENERATED by agent 3. Original brand data.\n"
        f"export const brand = {json.dumps(brand, indent=2)} as const;\n\n"
        f"export type Product = (typeof products)[number];\n\n"
        f"export const products = {json.dumps(catalog, indent=2)} as const;\n\n"
        "export const productLines = brand.product_lines;\n"
        "export type ProductLine = (typeof productLines)[number];\n"
    )


# Canonical config files - written deterministically so the site always builds,
# regardless of what the model emitted for them.
_TSCONFIG = """\
{
  "compilerOptions": {
    "target": "ES2021",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "baseUrl": ".",
    "paths": { "@/*": ["./*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
"""

_NEXT_CONFIG = """\
/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  images: { unoptimized: true },
};
export default nextConfig;
"""

# Shown while agent 4 hasn't generated a real photo yet.
_PLACEHOLDER_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600">'
    '<rect width="600" height="600" fill="{surface}"/>'
    '<circle cx="300" cy="260" r="120" fill="{primary}" opacity="0.18"/>'
    '<text x="300" y="470" font-family="sans-serif" font-size="28" fill="{ink}" '
    'text-anchor="middle" opacity="0.6">{label}</text></svg>'
)

# Next 14 only reads a CommonJS postcss.config.js (not .mjs).
_POSTCSS_CONFIG = """\
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
"""


def _tailwind_config(brand: dict) -> str:
    p = brand.get("palette", {})
    t = brand.get("typography", {})
    colors = {
        "bg": p.get("bg", "#ffffff"), "surface": p.get("surface", "#f4f4f5"),
        "ink": p.get("ink", "#18181b"), "primary": p.get("primary", "#4f46e5"),
        "accent": p.get("accent", "#f59e0b"), "muted": p.get("muted", "#a1a1aa"),
    }
    return (
        'import type { Config } from "tailwindcss";\n\n'
        "const config: Config = {\n"
        "  content: [\n"
        '    "./app/**/*.{ts,tsx,js,jsx,mdx}",\n'
        '    "./components/**/*.{ts,tsx,js,jsx}",\n'
        '    "./lib/**/*.{ts,tsx,js,jsx}",\n'
        "  ],\n"
        "  theme: {\n"
        f"    extend: {{\n      colors: {json.dumps(colors, indent=8)[:-1]}      }},\n"
        f'      fontFamily: {{\n'
        f'        headings: [{json.dumps(t.get("headings", "ui-sans-serif"))}, "ui-sans-serif", "sans-serif"],\n'
        f'        body: [{json.dumps(t.get("body", "ui-sans-serif"))}, "ui-sans-serif", "sans-serif"],\n'
        "      },\n"
        "    },\n"
        "  },\n"
        "  plugins: [],\n"
        "};\n\nexport default config;\n"
    )


def persist_data(root: Path, brand: dict, catalog: list[dict]) -> None:
    """Write the brand + catalogue to disk. Shared by agent 3 and agent 4."""
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "brand.json").write_text(json.dumps(brand, indent=2), encoding="utf-8")
    (data_dir / "products.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    (root / "lib").mkdir(parents=True, exist_ok=True)
    (root / "lib" / "data.ts").write_text(_data_module(brand, catalog), encoding="utf-8")


def _write_project(slug: str, files: dict[str, str], brand: dict, catalog: list[dict]) -> Path:
    root = Path(settings.output_dir) / slug
    if root.exists():
        shutil.rmtree(root)
    for rel, content in files.items():
        rel = rel.strip().lstrip("/")
        if ".." in rel:
            continue
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")

    # Real generated data, written deterministically (not model-transcribed).
    persist_data(root, brand, catalog)

    # Force known-good config: `@/*` resolution, no stale next.config keys, a
    # CommonJS postcss config (Next 14 ignores .mjs), and a tailwind config whose
    # `content` covers components/ and whose colours match the brand palette.
    (root / "tsconfig.json").write_text(_TSCONFIG, encoding="utf-8")
    (root / "next.config.mjs").write_text(_NEXT_CONFIG, encoding="utf-8")
    (root / "postcss.config.js").write_text(_POSTCSS_CONFIG, encoding="utf-8")
    (root / "postcss.config.mjs").unlink(missing_ok=True)
    (root / "tailwind.config.ts").write_text(_tailwind_config(brand), encoding="utf-8")

    # Image slots: one placeholder SVG per product so `product.image` always
    # resolves. Agent 4 overwrites these with real photos (as .png).
    p = brand.get("palette", {})
    img_dir = root / "public" / "img" / "products"
    img_dir.mkdir(parents=True, exist_ok=True)
    for prod in catalog:
        svg = _PLACEHOLDER_SVG.format(
            surface=p.get("surface", "#eee"), primary=p.get("primary", "#888"),
            ink=p.get("ink", "#222"), label=prod["name"][:24],
        )
        (img_dir / f"{prod['slug']}.svg").write_text(svg, encoding="utf-8")
    return root


def build(with_images: bool = False) -> dict:
    summary = _market_summary()
    if not summary["totals"] or not summary["totals"]["products"]:
        raise SystemExit("agent3: no products in the database - run agents 1 and 2 first")

    report(f"agent3: designing a brand from {summary['totals']['products']} products "
          f"across {summary['totals']['sites']} sites")
    brand = _design_brand(summary)
    slug = re.sub(r"[^a-z0-9-]", "", brand["slug"].lower()) or "new-brand"
    report(f"  brand: {brand['name']}  ({brand['tagline']})")

    catalog = _build_catalog(brand, summary)
    for p in catalog:  # image slot filled by agent 4; placeholder until then
        p["image"] = f"/img/products/{p['slug']}.svg"
    report(f"  catalogue: {len(catalog)} products")

    files: dict[str, str] = {}
    files.update(_codegen(_SCAFFOLD_FILES, brand,
                          extra="This chunk: config + data loaders. `lib/data.ts` "
                                "(exporting `brand` and `products`) is provided separately - "
                                "import from it; do not redefine it."))
    report(f"  scaffold: {len(files)} files")
    files.update(_codegen(_COMPONENT_FILES, brand,
                          extra="This chunk: presentational components. Import types/data "
                                "from `@/lib/data`."))
    report(f"  components: {len(files)} files total")
    component_src = "\n\n".join(
        f"// {p}\n{files[p]}" for p in _COMPONENT_FILES if p in files
    )
    files.update(_codegen(_PAGE_FILES, brand,
                          extra=f"This chunk: routes. Product detail uses `generateStaticParams`. "
                                f"Import and reuse these already-generated components as-is "
                                f"(match their prop signatures exactly):\n{component_src}\n\n"
                                f"Catalogue sample:\n{json.dumps(catalog[:3], indent=2)}"))
    report(f"  pages: {len(files)} files total")

    root = _write_project(slug, files, brand, catalog)

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO generated_brand (slug, spec, catalog, output_path)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
                spec = EXCLUDED.spec, catalog = EXCLUDED.catalog,
                output_path = EXCLUDED.output_path, created_at = now()
            """,
            (slug, Jsonb(brand), Jsonb(catalog), str(root)),
        )

    report(f"\nagent3: wrote {len(files) + 3} files to {root}")

    images = 0
    if with_images:
        from agents.agent4_images import generate_images

        images = generate_images(slug).get("generated", 0)

    report(f"  cd {root} && npm install && npm run dev")
    return {
        "slug": slug, "path": str(root), "brand": brand,
        "files": len(files) + 3, "images": images,
    }


if __name__ == "__main__":
    import sys

    build(with_images="--images" in sys.argv)
