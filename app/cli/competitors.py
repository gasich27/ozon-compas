from __future__ import annotations

import argparse
from pathlib import Path

from app.cli.common import (
    default_external_parser_dir,
    confirm_parser_start,
    parser_paths,
    query_name_from_url,
    validate_ozon_url,
)
from app.config import Settings, sqlite_path_from_url
from app.database import Database
from app.services.competitor_service import analyze_competitor_csv
from app.sources.competitor_parser.external_parser_runner import ExternalParserRunner


PARSER_WARNING = [
    "Сейчас будет запущен внешний парсер Ozon.",
    "Во время работы может открыться окно браузера.",
    "Не закрывайте его до завершения парсинга.",
    "Парсинг может занять от нескольких минут до 10–15 минут в зависимости "
    "от количества товаров и скорости загрузки.",
    "После завершения CSV будет автоматически передан в аналитику.",
]


def register(subparsers) -> None:
    parser = subparsers.add_parser(
        "competitors", help="Парсинг и аналитика товаров конкурентов"
    )
    commands = parser.add_subparsers(dest="competitors_command", required=True)

    parse = commands.add_parser(
        "parse", help="Запустить внешний парсер и проанализировать CSV"
    )
    parse.add_argument("--url", help="URL страницы Ozon")
    parse.add_argument("--limit", type=int, help="Ограничить число строк CSV")
    parse.add_argument("--timeout", type=int, help="Таймаут парсера в секундах")
    parse.add_argument("--yes", action="store_true", help="Не спрашивать подтверждение")
    parse.add_argument("--parser-dir", help="Директория внешнего парсера")
    parse.add_argument("--output-dir", help="Директория выходных CSV")
    parse.add_argument("--encoding", default="utf-8", help="Кодировка CSV")
    parse.set_defaults(handler=handle_parse)

    analyze = commands.add_parser(
        "analyze-csv", help="Проанализировать уже готовый CSV"
    )
    analyze.add_argument("--input", required=True, help="Путь к CSV")
    analyze.add_argument("--limit", type=int, help="Ограничить число строк CSV")
    analyze.add_argument("--encoding", default="utf-8", help="Кодировка CSV")
    analyze.set_defaults(handler=handle_analyze_csv)


def handle_parse(args: argparse.Namespace, settings: Settings) -> int:
    if args.url:
        url_value = args.url
    else:
        try:
            url_value = input("Введите URL Ozon: ").strip()
        except EOFError as exc:
            raise ValueError(
                "URL не был передан, а интерактивный ввод недоступен. "
                "Запустите команду с --url."
            ) from exc
    url = validate_ozon_url(url_value)
    parser_dir, output_dir = parser_paths(settings, args.parser_dir, args.output_dir)
    if not args.parser_dir and not settings.external_parser_path:
        print(f"Путь к внешнему парсеру не задан, используем {default_external_parser_dir()}")
    if not confirm_parser_start(PARSER_WARNING, args.yes):
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
    return _analyze_and_print(
        csv_path, args.encoding, args.limit, settings, "external_parser"
    )


def handle_analyze_csv(args: argparse.Namespace, settings: Settings) -> int:
    return _analyze_and_print(
        Path(args.input), args.encoding, args.limit, settings, "external_csv"
    )


def _analyze_and_print(
    csv_path: Path,
    encoding: str,
    limit: int | None,
    settings: Settings,
    source: str,
) -> int:
    database = Database(sqlite_path_from_url(settings.database_url))
    products, analysis, report_dir, run_id = analyze_competitor_csv(
        csv_path=csv_path,
        database=database,
        reports_dir=settings.reports_dir,
        encoding=encoding,
        limit=limit,
        source=source,
    )
    print(f"CSV: {csv_path}")
    print(f"Обработано товаров: {len(products)}")
    print(f"Средняя цена: {analysis['average_price']}")
    print(f"Медианная цена: {analysis['median_price']}")
    print(f"Средний рейтинг: {analysis['average_rating']}")
    print(f"Analysis run ID: {run_id}")
    print(f"Отчёт: {report_dir}")
    return 0
