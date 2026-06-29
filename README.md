# Varianty produktů 2025 a 2026

Statický webový report nad prodeji variantních SKU za roky 2025 a 2026.

## Live

https://rkonfal.github.io/variant-report-2025-web/

## Zdroj dat

- `eshop_analytics.orders`
- `eshop_analytics.order_items`
- `eshop_analytics.product_variants`
- definice varianty: buď přímo prodané SKU končící ve tvaru `/dd`, nebo katalogová varianta mapovaná přes `product_variants.variant_code`

## Regenerace dat

```bash
python3 scripts/build_report.py
```

## Lokální spuštění

```bash
python3 -m http.server 8000
```

Pak otevři `http://localhost:8000`.
