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
REPORT_YEARS = [2025, 2026]
MONTH_NAMES = {
    1: "leden",
    2: "unor",
    3: "brezen",
    4: "duben",
    5: "kveten",
    6: "cerven",
    7: "cervenec",
    8: "srpen",
    9: "zari",
    10: "rijen",
    11: "listopad",
    12: "prosinec",
}
EXCLUDED_SUFFIXES = {"/01"}
REPORT_AS_OF = datetime.fromisoformat("2026-06-29T18:05:25+02:00")


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


def months_for_year(year: int) -> list[str]:
    if year > REPORT_AS_OF.year:
        return []
    last_month = REPORT_AS_OF.month if year == REPORT_AS_OF.year else 12
    return [f"{year}-{month:02d}" for month in range(1, last_month + 1)]


def month_labels_for_year(year: int) -> dict[str, str]:
    return {f"{year}-{month:02d}": MONTH_NAMES[month] for month in range(1, 13)}


ALL_MONTHS = [month for year in REPORT_YEARS for month in months_for_year(year)]
ALL_MONTH_LABELS = {
    month: label
    for year in REPORT_YEARS
    for month, label in month_labels_for_year(year).items()
}
WINDOW_START = f"{min(REPORT_YEARS)}-01-01 00:00:00"
WINDOW_END = "2026-07-01 00:00:00"


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


def fetch_variant_rows() -> dict[int, dict[str, VariantSku]]:
    rows = run_psql(
        f"""
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
          AND timezone('Europe/Prague', o.order_created_at) >= TIMESTAMP '{WINDOW_START}'
          AND timezone('Europe/Prague', o.order_created_at) < TIMESTAMP '{WINDOW_END}'
          AND COALESCE(NULLIF(pv.variant_code, ''), NULLIF(oi.product_code, '')) ~ '/[0-9]{{2}}$'
        GROUP BY 1, 2, 3, 4, 5
        ORDER BY 1, 5
        """
    )

    variants_by_year = {year: {} for year in REPORT_YEARS}
    for variant_code, raw_product_code, variant_title, product_title, month, quantity in rows:
        if is_excluded_variant(variant_code):
            continue
        year = int(month[:4])
        if year not in variants_by_year:
            continue
        base_sku = raw_product_code.split("/", 1)[0] if raw_product_code else variant_code.split("/", 1)[0]
        sku = variants_by_year[year].get(variant_code)
        if sku is None:
            sku = VariantSku(
                sku=variant_code,
                base_sku=base_sku,
                title=build_title(product_title, variant_title, variant_code),
                product_title=product_title or base_sku,
            )
            variants_by_year[year][variant_code] = sku
        sku.months[month] += float(quantity)
    return variants_by_year


def fetch_all_units_by_month() -> dict[int, dict[str, float]]:
    rows = run_psql(
        f"""
        SELECT
            to_char(timezone('Europe/Prague', o.order_created_at), 'YYYY-MM') AS month,
            SUM(COALESCE(oi.quantity, 0)) AS quantity
        FROM order_items oi
        JOIN orders o ON o.order_id = oi.order_id
        WHERE o.is_counted = TRUE
          AND timezone('Europe/Prague', o.order_created_at) >= TIMESTAMP '{WINDOW_START}'
          AND timezone('Europe/Prague', o.order_created_at) < TIMESTAMP '{WINDOW_END}'
        GROUP BY 1
        ORDER BY 1
        """
    )
    payload = {year: {} for year in REPORT_YEARS}
    for month, quantity in rows:
        year = int(month[:4])
        if year in payload:
            payload[year][month] = float(quantity)
    return payload


def month_dict(values: dict[str, float], year: int) -> dict[str, int]:
    return {month: int(round(values.get(month, 0))) for month in months_for_year(year)}


def build_year_report(year: int, variants: dict[str, VariantSku], all_units_by_month: dict[str, float]) -> dict:
    year_months = months_for_year(year)
    month_labels = month_labels_for_year(year)

    months_payload = []
    variant_units_total = int(round(sum(sku.total for sku in variants.values())))
    all_units_total = int(round(sum(all_units_by_month.values())))

    for month in year_months:
        variant_units = int(round(sum(sku.months.get(month, 0) for sku in variants.values())))
        all_units = int(round(all_units_by_month.get(month, 0)))
        active_variant_skus = sum(1 for sku in variants.values() if sku.months.get(month, 0) > 0)
        share_pct = round((variant_units / all_units) * 100, 2) if all_units else 0.0
        months_payload.append(
            {
                "month": month,
                "label": month_labels[month],
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
                "months": month_dict(sku.months, year),
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
                        for month in year_months
                    },
                    year,
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
        "year": year,
        "summary": summary,
        "months": months_payload,
        "topSkus": skus_payload[:12],
        "baseProducts": base_products_payload,
        "skus": skus_payload,
    }


def build_report() -> dict:
    variants_by_year = fetch_variant_rows()
    all_units_by_year = fetch_all_units_by_month()

    annual_payload = [
        build_year_report(year, variants_by_year[year], all_units_by_year[year])
        for year in REPORT_YEARS
    ]

    return {
        "generatedAt": REPORT_AS_OF.isoformat(),
        "availableYears": REPORT_YEARS,
        "defaultYear": max(year for year in REPORT_YEARS if months_for_year(year)),
        "monthLabels": ALL_MONTH_LABELS,
        "sourceWindow": {
            "from": f"{min(REPORT_YEARS)}-01-01T00:00:00+01:00",
            "to": REPORT_AS_OF.isoformat(),
            "years": REPORT_YEARS,
        },
        "source": {
            "database": "eshop_analytics",
            "tables": ["orders", "order_items", "product_variants", "products"],
            "logic": "Varianta je bud prime product_code ve tvaru /dd, nebo variant_code z product_variants pro polozky, kde se suffix v objednavce neuklada primo do product_code. Z reportu jsou zamerne vyrazeny vsechny varianty koncici na /01.",
        },
        "annual": annual_payload,
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


def export_year_files(year_report: dict) -> None:
    year = year_report["year"]
    year_months = months_for_year(year)

    write_csv(
        EXPORTS_DIR / f"varianty_{year}_mesice_summary.csv",
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
            for row in year_report["months"]
        ],
    )
    write_csv(
        EXPORTS_DIR / f"varianty_{year}_po_sku_mesice.csv",
        ["sku", "title", *year_months, f"total_{year}"],
        [
            [row["sku"], row["title"], *[row["months"][month] for month in year_months], row["total"]]
            for row in year_report["skus"]
        ],
    )
    write_csv(
        EXPORTS_DIR / f"varianty_{year}_po_zakladnim_produktu.csv",
        ["base_sku", "variant_sku_count", "variant_skus", *year_months, f"total_{year}"],
        [
            [
                row["baseSku"],
                row["variantSkuCount"],
                ",".join(row["variantSkus"]),
                *[row["months"][month] for month in year_months],
                row["total"],
            ]
            for row in year_report["baseProducts"]
        ],
    )


def export_markdown(report: dict) -> None:
    markdown = [
        "# Varianty produktu za 2025 a 2026",
        "",
        "Definice varianty v tomto reportu: bud skutecne prodane SKU koncici na `/dd`, nebo katalogova varianta mapovana pres `product_variants.variant_code`. Vsechny varianty koncici na `/01` jsou zamerne vyrazeny.",
        "",
    ]

    for year_report in report["annual"]:
        year = year_report["year"]
        summary = year_report["summary"]
        markdown.extend(
            [
                f"## Rok {year}",
                "",
                f"- Celkem prodano variantnich kusu: **{summary['variantUnits']:,}**".replace(",", " "),
                f"- Celkem prodano vsech kusu: **{summary['allUnits']:,}**".replace(",", " "),
                f"- Podil variant na vsech kusech: **{str(summary['sharePct']).replace('.', ',')} %**",
                f"- Pocet aktivnich variantnich SKU: **{summary['skuCount']}**",
                f"- Pocet zakladnich produktu s variantami: **{summary['baseCount']}**",
                "",
                "| mesic | variantni kusy | vsechny kusy | podil | aktivni variantni SKU |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in year_report["months"]:
            markdown.append(
                f"| {row['label']} | {row['variantUnits']} | {row['allUnits']} | {str(row['sharePct']).replace('.', ',')} % | {row['activeVariantSkus']} |"
            )
        markdown.extend(
            [
                "",
                f"### Top variantni SKU za {year}",
                "",
                "| SKU | nazev | kusy |",
                "| --- | --- | ---: |",
            ]
        )
        for row in year_report["topSkus"]:
            markdown.append(f"| `{row['sku']}` | {row['title']} | {row['total']} |")
        markdown.append("")

    markdown.extend(
        [
            "## Exporty",
            "",
            "- `exports/variant-report-2025/varianty_2025_mesice_summary.csv`",
            "- `exports/variant-report-2025/varianty_2025_po_sku_mesice.csv`",
            "- `exports/variant-report-2025/varianty_2025_po_zakladnim_produktu.csv`",
            "- `exports/variant-report-2025/varianty_2026_mesice_summary.csv`",
            "- `exports/variant-report-2025/varianty_2026_po_sku_mesice.csv`",
            "- `exports/variant-report-2025/varianty_2026_po_zakladnim_produktu.csv`",
        ]
    )
    (EXPORTS_DIR / "varianty_2025_2026_report.md").write_text(
        "\n".join(markdown) + "\n",
        encoding="utf-8",
    )


def export_support_files(report: dict) -> None:
    for year_report in report["annual"]:
        export_year_files(year_report)
    export_markdown(report)


def main() -> None:
    report = build_report()
    write_json(REPORT_JSON, report)
    export_support_files(report)


if __name__ == "__main__":
    main()
