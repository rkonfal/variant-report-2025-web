#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import shlex
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
REPORT_JSON = DATA_DIR / "report.json"
EXPORTS_DIR = ROOT.parent / "exports" / "variant-report-2025"

SSH_HOST = "root@70.34.246.98"
SSH_KEY = Path.home() / ".ssh" / "rudolf_tiande_key"
DATABASE = "eshop_analytics"
MONTHS = [f"2025-{month:02d}" for month in range(1, 13)]
MONTH_LABELS = {
    "2025-01": "leden",
    "2025-02": "unor",
    "2025-03": "brezen",
    "2025-04": "duben",
    "2025-05": "kveten",
    "2025-06": "cerven",
    "2025-07": "cervenec",
    "2025-08": "srpen",
    "2025-09": "zari",
    "2025-10": "rijen",
    "2025-11": "listopad",
    "2025-12": "prosinec",
}
EXCLUDED_SUFFIXES = {"/01"}


@dataclass
class VariantSku:
    sku: str
    base_sku: str
    title: str
    product_title: str
    months: dict[str, float] = field(default_factory=lambda: defaultdict(float))

    @property
    def total(self) -> float:
        return sum(self.months.values())


def ssh_prefix() -> list[str]:
    cmd = ["ssh", "-o", "StrictHostKeyChecking=accept-new"]
    if SSH_KEY.exists():
        cmd.extend(["-i", str(SSH_KEY)])
    cmd.append(SSH_HOST)
    return cmd


def run_psql(query: str) -> list[list[str]]:
    compact = " ".join(query.split())
    remote = (
        f"docker exec postgres-main psql -U postgres -d {shlex.quote(DATABASE)} "
        f"-AtF '|' -c {shlex.quote(compact)}"
    )
    output = subprocess.check_output([*ssh_prefix(), remote], text=True)
    return [line.split("|") for line in output.splitlines() if line.strip()]


def normalize_label(value: str) -> str:
    return (
        value.replace("Počet kusů:", "")
        .replace("1ks", "1 ks")
        .replace("3ks", "3 ks")
        .replace("5ks", "5 ks")
        .replace("7ks", "7 ks")
        .replace("8ks", "8 ks")
        .replace("10ks", "10 ks")
        .strip(" -")
        .strip()
    )


def build_title(product_title: str, variant_title: str, sku: str) -> str:
    product_title = (product_title or "").strip()
    variant_title = normalize_label(variant_title or "")

    if product_title and variant_title and variant_title != product_title:
        return f"{product_title} - {variant_title}"
    if product_title:
        return product_title
    if variant_title:
        return variant_title
    return sku


def is_excluded_variant(variant_code: str) -> bool:
    return any(variant_code.endswith(suffix) for suffix in EXCLUDED_SUFFIXES)


def fetch_variant_rows() -> dict[str, VariantSku]:
    rows = run_psql(
        """
        SELECT
            COALESCE(NULLIF(pv.variant_code, ''), NULLIF(oi.product_code, '')) AS variant_code,
            COALESCE(NULLIF(oi.product_code, ''), NULLIF(p.product_code, ''), '') AS raw_product_code,
            COALESCE(NULLIF(oi.variant_name, ''), NULLIF(pv.variant_name, ''), '') AS variant_title,
            COALESCE(NULLIF(oi.product_name, ''), NULLIF(p.product_name, ''), '') AS product_title,
            to_char(timezone('Europe/Prague', o.order_created_at), 'YYYY-MM') AS month,
            SUM(COALESCE(oi.quantity, 0)) AS quantity
        FROM order_items oi
        JOIN orders o ON o.order_id = oi.order_id
        LEFT JOIN product_variants pv ON pv.variant_id = oi.variant_id
        LEFT JOIN products p ON p.product_id = oi.product_id
        WHERE o.is_counted = TRUE
          AND timezone('Europe/Prague', o.order_created_at) >= TIMESTAMP '2025-01-01 00:00:00'
          AND timezone('Europe/Prague', o.order_created_at) < TIMESTAMP '2026-01-01 00:00:00'
          AND COALESCE(NULLIF(pv.variant_code, ''), NULLIF(oi.product_code, '')) ~ '/[0-9]{2}$'
        GROUP BY 1, 2, 3, 4, 5
        ORDER BY 1, 5
        """
    )

    variants: dict[str, VariantSku] = {}
    for variant_code, raw_product_code, variant_title, product_title, month, quantity in rows:
        if is_excluded_variant(variant_code):
            continue
        base_sku = variant_code.split("/", 1)[0]
        sku = variants.get(variant_code)
        if sku is None:
            sku = VariantSku(
                sku=variant_code,
                base_sku=base_sku,
                title=build_title(product_title, variant_title, variant_code),
                product_title=product_title or base_sku,
            )
            variants[variant_code] = sku
        sku.months[month] += float(quantity)
    return variants


def fetch_all_units_by_month() -> dict[str, float]:
    rows = run_psql(
        """
        SELECT
            to_char(timezone('Europe/Prague', o.order_created_at), 'YYYY-MM') AS month,
            SUM(COALESCE(oi.quantity, 0)) AS quantity
        FROM order_items oi
        JOIN orders o ON o.order_id = oi.order_id
        WHERE o.is_counted = TRUE
          AND timezone('Europe/Prague', o.order_created_at) >= TIMESTAMP '2025-01-01 00:00:00'
          AND timezone('Europe/Prague', o.order_created_at) < TIMESTAMP '2026-01-01 00:00:00'
        GROUP BY 1
        ORDER BY 1
        """
    )
    return {month: float(quantity) for month, quantity in rows}


def month_dict(values: dict[str, float]) -> dict[str, int]:
    return {month: int(round(values.get(month, 0))) for month in MONTHS}


def build_report() -> dict:
    variants = fetch_variant_rows()
    all_units_by_month = fetch_all_units_by_month()

    months_payload = []
    variant_units_total = int(round(sum(sku.total for sku in variants.values())))
    all_units_total = int(round(sum(all_units_by_month.values())))

    for month in MONTHS:
        variant_units = int(round(sum(sku.months.get(month, 0) for sku in variants.values())))
        all_units = int(round(all_units_by_month.get(month, 0)))
        active_variant_skus = sum(1 for sku in variants.values() if sku.months.get(month, 0) > 0)
        share_pct = round((variant_units / all_units) * 100, 2) if all_units else 0.0
        months_payload.append(
            {
                "month": month,
                "label": MONTH_LABELS[month],
                "variantUnits": variant_units,
                "allUnits": all_units,
                "sharePct": share_pct,
                "activeVariantSkus": active_variant_skus,
            }
        )

    skus_payload = []
    base_groups: dict[str, list[VariantSku]] = defaultdict(list)
    for sku in variants.values():
        base_groups[sku.base_sku].append(sku)
        skus_payload.append(
            {
                "sku": sku.sku,
                "title": sku.title,
                "baseSku": sku.base_sku,
                "months": month_dict(sku.months),
                "total": int(round(sku.total)),
            }
        )
    skus_payload.sort(key=lambda row: (-row["total"], row["sku"]))

    base_products_payload = []
    for base_sku, base_skus in base_groups.items():
        base_total = int(round(sum(item.total for item in base_skus)))
        base_products_payload.append(
            {
                "baseSku": base_sku,
                "variantSkus": [item.sku for item in sorted(base_skus, key=lambda item: item.sku)],
                "variantSkuCount": len(base_skus),
                "total": base_total,
                "months": month_dict(
                    {
                        month: sum(item.months.get(month, 0) for item in base_skus)
                        for month in MONTHS
                    }
                ),
            }
        )
    base_products_payload.sort(key=lambda row: (-row["total"], row["baseSku"]))

    summary = {
        "variantUnits": variant_units_total,
        "allUnits": all_units_total,
        "sharePct": round((variant_units_total / all_units_total) * 100, 2) if all_units_total else 0.0,
        "skuCount": len(skus_payload),
        "baseCount": len(base_products_payload),
        "definitionShort": "Varianty /dd mapovane i pres product_variants.variant_code, ale bez suffixu /01.",
    }

    return {
        "generatedAt": datetime.now().astimezone().isoformat(),
        "sourceWindow": {
            "from": "2025-01-01T00:00:00+01:00",
            "to": "2025-12-31T23:59:59+01:00",
            "days": 365,
        },
        "source": {
            "database": "eshop_analytics",
            "tables": ["orders", "order_items", "product_variants", "products"],
            "logic": "Varianta je bud prime product_code ve tvaru /dd, nebo variant_code z product_variants pro polozky, kde se suffix v objednavce neuklada primo do product_code. Z reportu jsou zamerne vyrazeny vsechny varianty koncici na /01.",
        },
        "summary": summary,
        "months": months_payload,
        "topSkus": skus_payload[:12],
        "baseProducts": base_products_payload,
        "skus": skus_payload,
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, header: list[str], rows: Iterable[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def export_support_files(report: dict) -> None:
    write_csv(
        EXPORTS_DIR / "varianty_2025_mesice_summary.csv",
        ["month", "label", "variant_units", "all_units", "share_pct", "active_variant_skus"],
        [
            [
                row["month"],
                row["label"],
                row["variantUnits"],
                row["allUnits"],
                row["sharePct"],
                row["activeVariantSkus"],
            ]
            for row in report["months"]
        ],
    )
    write_csv(
        EXPORTS_DIR / "varianty_2025_po_sku_mesice.csv",
        ["sku", "title", *MONTHS, "total_2025"],
        [
            [row["sku"], row["title"], *[row["months"][month] for month in MONTHS], row["total"]]
            for row in report["skus"]
        ],
    )
    write_csv(
        EXPORTS_DIR / "varianty_2025_po_zakladnim_produktu.csv",
        ["base_sku", "variant_sku_count", "variant_skus", *MONTHS, "total_2025"],
        [
            [
                row["baseSku"],
                row["variantSkuCount"],
                ",".join(row["variantSkus"]),
                *[row["months"][month] for month in MONTHS],
                row["total"],
            ]
            for row in report["baseProducts"]
        ],
    )
    markdown = [
        "# Varianty produktu za 2025",
        "",
        "Definice varianty v tomto reportu: bud skutecne prodane SKU koncici na `/dd`, nebo katalogova varianta mapovana pres `product_variants.variant_code`. Vsechny varianty koncici na `/01` jsou zamerne vyrazeny.",
        "",
        f"- Celkem prodano variantnich kusu: **{report['summary']['variantUnits']:,}**".replace(",", " "),
        f"- Celkem prodano vsech kusu: **{report['summary']['allUnits']:,}**".replace(",", " "),
        f"- Podil variant na vsech kusech: **{str(report['summary']['sharePct']).replace('.', ',')} %**",
        f"- Pocet aktivnich variantnich SKU v roce 2025: **{report['summary']['skuCount']}**",
        f"- Pocet zakladnich produktu s variantami: **{report['summary']['baseCount']}**",
        "",
        "## Mesice",
        "",
        "| mesic | variantni kusy | vsechny kusy | podil | aktivni variantni SKU |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in report["months"]:
        markdown.append(
            f"| {row['label']} | {row['variantUnits']} | {row['allUnits']} | {str(row['sharePct']).replace('.', ',')} % | {row['activeVariantSkus']} |"
        )
    markdown.extend(
        [
            "",
            "## Top variantni SKU za 2025",
            "",
            "| SKU | nazev | kusy |",
            "| --- | --- | ---: |",
        ]
    )
    for row in report["topSkus"]:
        markdown.append(f"| `{row['sku']}` | {row['title']} | {row['total']} |")
    markdown.extend(
        [
            "",
            "## Exporty",
            "",
            "- `exports/variant-report-2025/varianty_2025_mesice_summary.csv`",
            "- `exports/variant-report-2025/varianty_2025_po_sku_mesice.csv`",
            "- `exports/variant-report-2025/varianty_2025_po_zakladnim_produktu.csv`",
        ]
    )
    (EXPORTS_DIR / "varianty_2025_report.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")


def main() -> None:
    report = build_report()
    write_json(REPORT_JSON, report)
    export_support_files(report)


if __name__ == "__main__":
    main()
