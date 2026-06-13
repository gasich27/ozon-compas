#!/usr/bin/env python3
"""
OZON Seller Parser — точка входа.
==================================

Использование:
    python run.py collect       — Stage 1: сбор ссылок на товары
    python run.py scrape        — Stage 2: парсинг деталей товаров
    python run.py all           — Запуск обоих этапов последовательно
    python run.py --help        — Справка
"""

import sys
import logging
from datetime import datetime

from src.config import ParserConfig


def setup_logging(log_file: str) -> None:
    """Настройка логирования в файл и консоль."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def print_help() -> None:
    """Вывести справку."""
    print("""
OZON Seller Parser v1.0.0
=========================

Использование:
    python run.py collect    Этап 1: сбор ссылок на товары продавца
    python run.py scrape     Этап 2: парсинг деталей каждого товара
    python run.py all        Запуск обоих этапов последовательно
    python run.py --help     Показать эту справку

Настройка:
    1. Скопируйте config.example.json -> config.json
    2. Укажите seller_url — ссылку на страницу продавца
    3. Запустите нужный этап
""")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h", "help"):
        print_help()
        return

    command = sys.argv[1].lower()
    valid_commands = ("collect", "scrape", "all")

    if command not in valid_commands:
        print(f"Неизвестная команда: {command}")
        print(f"Доступные: {', '.join(valid_commands)}")
        sys.exit(1)

    # Загрузка конфигурации
    config = ParserConfig.load()
    config.validate()

    # Настройка логов
    setup_logging(config.log_file)
    logger = logging.getLogger(__name__)

    start_time = datetime.now()
    logger.info(f"Запуск: {command} | {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        if command in ("collect", "all"):
            from src.collector import run_collector
            run_collector(config)

        if command in ("scrape", "all"):
            from src.scraper import run_scraper
            run_scraper(config)

    except KeyboardInterrupt:
        logger.warning("Прервано пользователем (Ctrl+C)")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        sys.exit(1)

    elapsed = datetime.now() - start_time
    logger.info(f"Завершено за {elapsed.total_seconds():.0f} сек.")


if __name__ == "__main__":
    main()
