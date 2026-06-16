from __future__ import annotations

from pathlib import Path

from app.analytics.competitor_analyzer import analyze_competitor_products
from app.database import Database
from app.reports.generator import create_competitor_report
from app.sources.competitor_parser.csv_reader import CompetitorCsvReader


def analyze_competitor_csv(
    *,
    csv_path: Path,
    database: Database,
    reports_dir: Path,
    encoding: str = "utf-8",
    limit: int | None = None,
    source: str = "external_parser",
    user_id: int = 0,
) -> tuple[list, dict, Path, int]:
    products = CompetitorCsvReader(encoding=encoding).load(csv_path, limit=limit)
    analysis = analyze_competitor_products(products)
    run_id = database.create_analysis_run(
        mode="competitors",
        source=source,
        marketplace="ozon",
        total_products=len(products),
        status="success",
        result=analysis,
        user_id=user_id,
    )
    database.save_competitor_products(products, run_id)
    report_dir = create_competitor_report(reports_dir, products, analysis)
    return products, analysis, report_dir, run_id
