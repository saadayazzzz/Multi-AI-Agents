"""Agent 4 - Product imagery.

For each product in a generated brand's catalogue, generate a photorealistic
product shot from the product name (informed by category + brand aesthetic) and
drop it into the site's `public/img/products/` folder. Agent 3 has already wired
`product.image` into the components, so the pictures appear as soon as they land.

Falls back to the per-product placeholder SVG (written by agent 3) when image
generation is unavailable or fails, so the site never shows a broken image.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from agents.agent3_brand_builder import persist_data
from agents.llm import PROVIDER, generate_image
from agents.reporter import report
from config import settings
from db import get_conn


def _prompt(product: dict[str, Any], brand: dict[str, Any]) -> str:
    palette = brand.get("palette", {})
    voice = ", ".join(brand.get("voice", [])[:3]) or "clean, modern"
    return (
        f"Photorealistic e-commerce product photograph of a skincare / cosmetics "
        f"product: \"{product['name']}\" "
        f"({product.get('category', 'skincare')}, {product.get('size', '')}). "
        f"{product.get('tagline', '')}. "
        f"A single unbranded {product.get('category', 'skincare')} container "
        f"(bottle, jar, tube or dropper as appropriate), centred, floating on a "
        f"seamless studio background in the colour {palette.get('bg', '#f4f4f5')}, "
        f"soft diffused lighting, subtle shadow, {voice} aesthetic, accent colour "
        f"{palette.get('primary', '#4f46e5')}. Square composition. "
        f"No text, no logos, no lettering, no packaging copy, no hands, no people."
    )


def _load_brand(slug: str | None) -> dict[str, Any]:
    with get_conn() as conn:
        if slug:
            row = conn.execute(
                "SELECT slug, spec, catalog, output_path FROM generated_brand WHERE slug = %s",
                (slug,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT slug, spec, catalog, output_path FROM generated_brand "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
    if not row:
        raise SystemExit("agent4: no generated brand found - run agent 3 first")
    return row


def generate_images(
    slug: str | None = None, *, limit: int | None = None, overwrite: bool = False
) -> dict[str, Any]:
    row = _load_brand(slug)
    slug = row["slug"]
    brand: dict[str, Any] = row["spec"]
    catalog: list[dict[str, Any]] = list(row["catalog"] or [])
    root = Path(row["output_path"])
    img_dir = root / "public" / "img" / "products"
    img_dir.mkdir(parents=True, exist_ok=True)

    cap = min(limit or settings.max_images, settings.max_images)
    report(f"agent4: generating up to {cap} product images for '{slug}' via {PROVIDER}")

    generated = placeholders = 0
    for i, product in enumerate(catalog):
        pslug = product["slug"]
        png = img_dir / f"{pslug}.png"
        prompt = _prompt(product, brand)

        if png.exists() and not overwrite:
            product["image"] = f"/img/products/{pslug}.png"
            generated += 1
            continue

        if i >= cap:
            product["image"] = f"/img/products/{pslug}.svg"
            placeholders += 1
            continue

        kind = "photo"
        try:
            data = generate_image(prompt, size=settings.image_size)
            png.write_bytes(data)
            product["image"] = f"/img/products/{pslug}.png"
            generated += 1
            report(f"  [{i + 1}/{len(catalog)}] {product['name']}")
        except Exception as e:  # noqa: BLE001
            kind = "placeholder"
            product["image"] = f"/img/products/{pslug}.svg"
            placeholders += 1
            report(f"  [{i + 1}/{len(catalog)}] {product['name']} - placeholder ({e})")

        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO generated_images (brand_slug, product_slug, prompt, rel_path, kind)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (brand_slug, product_slug) DO UPDATE SET
                    prompt = EXCLUDED.prompt, rel_path = EXCLUDED.rel_path,
                    kind = EXCLUDED.kind, created_at = now()
                """,
                (slug, pslug, prompt, product["image"], kind),
            )

    persist_data(root, brand, catalog)
    with get_conn() as conn:
        conn.execute(
            "UPDATE generated_brand SET catalog = %s WHERE slug = %s",
            (Jsonb(catalog), slug),
        )

    report(f"agent4: {generated} photos, {placeholders} placeholders -> {img_dir}")
    return {
        "slug": slug, "generated": generated, "placeholders": placeholders,
        "path": str(img_dir),
    }


if __name__ == "__main__":
    generate_images()
