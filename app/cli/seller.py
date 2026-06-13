from __future__ import annotations

import argparse
from pathlib import Path

from app.config import Settings, sqlite_path_from_url
from app.database import Database
from app.services.seller_service import (
    analyze_seller_products_in_db,
    build_seller_client_from_settings,
    sync_seller_products,
)
from app.sources.seller_api.exceptions import (
    OzonSellerApiAuthError,
    OzonSellerApiError,
    OzonSellerApiResponseError,
)


def register(subparsers) -> None:
    parser = subparsers.add_parser("seller", help="Seller API mode")
    commands = parser.add_subparsers(dest="seller_command", required=True)

    check_api = commands.add_parser("check-api", help="Проверить ключи Seller API")
    check_api.set_defaults(handler=handle_check_api)

    sync = commands.add_parser("sync", help="Синхронизировать товары селлера")
    sync.add_argument("--limit", type=int, help="Ограничить число товаров")
    sync.set_defaults(handler=handle_sync)

    list_cmd = commands.add_parser("list", help="Показать товары из SQLite")
    list_cmd.add_argument("--limit", type=int, help="Ограничить число строк")
    list_cmd.set_defaults(handler=handle_list)

    show = commands.add_parser("show", help="Показать один товар")
    show.add_argument("--seller-product-id", required=True)
    show.set_defaults(handler=handle_show)

    analyze = commands.add_parser("analyze", help="Анализ товаров селлера")
    analyze.set_defaults(handler=handle_analyze)


def handle_check_api(args: argparse.Namespace, settings: Settings) -> int:
    client = build_seller_client_from_settings(settings)
    ok, message = client.check_credentials()
    print(message)
    return 0 if ok else 1


def handle_sync(args: argparse.Namespace, settings: Settings) -> int:
    database = Database(sqlite_path_from_url(settings.database_url))
    client = build_seller_client_from_settings(settings)
    products = sync_seller_products(database=database, client=client, limit=args.limit)
    database.create_analysis_run(
        mode="seller",
        source="ozon_api",
        marketplace="ozon",
        total_products=len(products),
        status="success",
    )
    print(f"Синхронизировано товаров: {len(products)}")
    return 0


def handle_list(args: argparse.Namespace, settings: Settings) -> int:
    database = Database(sqlite_path_from_url(settings.database_url))
    rows = _load_rows(database, limit=args.limit)
    if not rows:
        print("Товары селлера не найдены. Сначала выполните seller sync.")
        return 0
    _print_table(rows)
    return 0


def handle_show(args: argparse.Namespace, settings: Settings) -> int:
    database = Database(sqlite_path_from_url(settings.database_url))
    row = database.get_seller_product(args.seller_product_id)
    if row is None:
        print("Товар селлера не найден. Сначала выполните seller sync.")
        return 1
    for key, value in row.to_dict().items():
        print(f"{key}: {value}")
    return 0


def handle_analyze(args: argparse.Namespace, settings: Settings) -> int:
    database = Database(sqlite_path_from_url(settings.database_url))
    products, analysis, report_dir = analyze_seller_products_in_db(
        database=database, reports_dir=settings.reports_dir
    )
    print(f"Товаров в базе: {len(products)}")
    print(f"Средняя цена: {analysis['average_price']}")
    print(f"Медианная цена: {analysis['median_price']}")
    print(f"Средний остаток: {analysis['average_stock']}")
    print(f"Отчёт: {report_dir}")
    return 0


def _load_rows(database: Database, limit: int | None = None) -> list[dict]:
    query = "SELECT * FROM seller_products ORDER BY name"
    params: tuple = ()
    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)
    with database.connect() as connection:
        return [dict(row) for row in connection.execute(query, params).fetchall()]


def _print_table(rows: list[dict]) -> None:
    headers = ["id", "name", "price", "stock", "rating", "reviews_count"]
    widths = {header: max(len(header), *(len(str(row.get(header, ""))) for row in rows)) for header in headers}
    print(" | ".join(header.ljust(widths[header]) for header in headers))
    print("-+-".join("-" * widths[header] for header in headers))
    for row in rows:
        print(" | ".join(str(row.get(header, "")).ljust(widths[header]) for header in headers))
