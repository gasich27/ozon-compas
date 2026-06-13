from __future__ import annotations

from pathlib import Path

from app.analytics.comparison_analyzer import (
    compare_seller_product_with_competitors,
)
from app.database import Database
from app.reports.generator import create_comparison_report
from app.sources.competitor_parser.csv_reader import CompetitorCsvReader


def compare_with_csv(
    *,
    seller_product_id: str,
    csv_path: Path,
    database: Database,
    reports_dir: Path,
    encoding: str = "utf-8",
    limit: int | None = None,
) -> tuple[dict, Path, int]:
    seller_product = database.get_seller_product(seller_product_id)
    if seller_product is None:
        raise LookupError(
            "Товар селлера не найден. Сначала выполните seller sync."
        )
    competitors = CompetitorCsvReader(encoding=encoding).load(
        csv_path, limit=limit
    )
    comparison = compare_seller_product_with_competitors(
        seller_product, competitors
    )
    run_id = database.create_analysis_run(
        mode="compare",
        source="external_parser",
        marketplace="ozon",
        total_products=len(competitors),
        status="success",
        result=comparison,
    )
    database.save_competitor_products(competitors, run_id)
    report_dir = create_comparison_report(
        reports_dir, seller_product, competitors, comparison
    )
    return comparison, report_dir, run_id
