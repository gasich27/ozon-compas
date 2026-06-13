from __future__ import annotations

import argparse
from pathlib import Path

from app.cli.common import (
    confirm_parser_start,
    parser_paths,
    query_name_from_url,
    validate_ozon_url,
)
from app.config import Settings, sqlite_path_from_url
from app.database import Database
from app.services.comparison_service import compare_with_csv
from app.sources.competitor_parser.external_parser_runner import (
    ExternalParserRunner,
)


COMPARE_WARNING = [
    "Будет запущен внешний парсер конкурентов.",
    "Может открыться окно браузера.",
    "Не закрывайте его до завершения.",
    "После парсинга CSV будет автоматически использован для сравнения.",
]


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "compare", help="Сравнение товара селлера с конкурентами"
    )
    commands = parser.add_subparsers(dest="compare_command", required=True)
    product = commands.add_parser("product", help="Сравнить один товар")
    product.add_argument("--seller-product-id", required=True)
    source = product.add_mutually_exclusive_group(required=True)
    source.add_argument("--competitors-url")
    source.add_argument("--competitors-csv")
    product.add_argument("--limit", type=int)
    product.add_argument("--timeout", type=int)
    product.add_argument("--yes", action="store_true")
    product.add_argument("--parser-dir")
    product.add_argument("--output-dir")
    product.add_argument("--encoding", default="utf-8")
    product.set_defaults(handler=handle_product)


def handle_product(args: argparse.Namespace, settings: Settings) -> int:
    database = Database(sqlite_path_from_url(settings.database_url))
    seller_product = database.get_seller_product(args.seller_product_id)
    if seller_product is None:
        raise LookupError(
            "Товар селлера не найден. Сначала выполните seller sync."
        )

    if args.competitors_csv:
        csv_path = Path(args.competitors_csv)
    else:
        url = validate_ozon_url(args.competitors_url)
        parser_dir, output_dir = parser_paths(
            settings, args.parser_dir, args.output_dir
        )
        if not confirm_parser_start(COMPARE_WARNING, args.yes):
            print("Запуск отменён.")
            return 0
        timeout = args.timeout or settings.external_parser_timeout
        csv_path = ExternalParserRunner(
            str(parser_dir), str(output_dir), timeout
        ).run(
            url=url,
            query_name=query_name_from_url(url),
            limit=args.limit,
        )

    comparison, report_dir, run_id = compare_with_csv(
        seller_product_id=args.seller_product_id,
        csv_path=csv_path,
        database=database,
        reports_dir=settings.reports_dir,
        encoding=args.encoding,
        limit=args.limit,
    )
    print(f"Товар: {seller_product.name}")
    print(f"Конкурентов: {comparison['competitors_count']}")
    print(f"Медианная цена рынка: {comparison['market_median_price']}")
    print(f"Разница с рынком, %: {comparison['price_gap_percent']}")
    print("Рекомендации:")
    for recommendation in comparison["recommendations"]:
        print(f"- {recommendation}")
    print(f"Analysis run ID: {run_id}")
    print(f"Отчёт: {report_dir}")
    return 0
