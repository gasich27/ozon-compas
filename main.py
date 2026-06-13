from __future__ import annotations

import argparse
import logging
import sqlite3
import sys

from app.cli import compare, competitors, seller
from app.config import Settings
from app.sources.competitor_parser.csv_reader import CompetitorCsvError
from app.sources.competitor_parser.exceptions import ExternalParserError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ozon Seller Radar: товары селлера и аналитика конкурентов"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    seller.register(subparsers)
    competitors.register(subparsers)
    compare.register(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    try:
        return int(args.handler(args, settings))
    except (
        ExternalParserError,
        CompetitorCsvError,
        LookupError,
        ValueError,
        sqlite3.Error,
        OSError,
    ) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Операция прервана пользователем.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
