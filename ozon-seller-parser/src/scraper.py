"""
Stage 2 — Парсинг деталей товаров.
====================================
Открывает каждую ссылку из product_links.txt и извлекает данные товара.
"""

import csv
import json
import logging
import re
import time
from collections import Counter
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from selenium.common.exceptions import TimeoutException, WebDriverException

from .config import ParserConfig
from .browser import create_driver, fetch_page, FetchError

logger = logging.getLogger(__name__)

# Колонки CSV
FIELDNAMES = [
    "Название",
    "Ссылка на товар",
    "Артикул",
    "Цена",
    "Количество отзывов",
    "Средний отзыв",
]


def extract_text(soup: BeautifulSoup, selectors: list, default: str = "Нет данных") -> str:
    """Извлечь текст по списку CSS-селекторов (первый найденный)."""
    for selector in selectors:
        element = soup.select_one(selector)
        if element:
            return element.text.strip()
    return default


def extract_description(soup: BeautifulSoup) -> str:
    """Извлечь полное описание из JSON-LD разметки."""
    try:
        script_tag = soup.find("script", string=re.compile(r"@context"))
        if script_tag:
            json_data = json.loads(script_tag.string.strip())
            if "description" in json_data:
                return json_data["description"].strip()
    except Exception as e:
        logger.debug(f"Не удалось извлечь описание из JSON-LD: {e}")
    return "Нет описания"


def extract_article(link: str) -> str:
    """Извлечь артикул (ID товара) из URL."""
    match = re.search(r"/product/.+-(\d+)/?", link)
    return match.group(1) if match else "Нет артикула"


def extract_attribute(soup: BeautifulSoup, href_pattern: str) -> str:
    """Извлечь атрибут товара по паттерну ссылки (автор, серия и т.д.)."""
    try:
        el = soup.select_one(f'div[data-widget="webShortCharacteristics"] a[href*="/{href_pattern}/"]')
        return el.text.strip() if el else "Нет данных"
    except Exception:
        return "Нет данных"


def extract_price(soup: BeautifulSoup) -> str:
    """Извлечь цену товара из JSON-LD."""
    product = {}
    for item in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw_json = item.string or item.get_text(strip=True)
        if not raw_json:
            continue
        try:
            json_data = json.loads(raw_json)
        except Exception:
            continue

        if isinstance(json_data, dict) and json_data.get("@type") == "Product":
            product = json_data
            break

        if isinstance(json_data, list):
            for entry in json_data:
                if isinstance(entry, dict) and entry.get("@type") == "Product":
                    product = entry
                    break

    offers = product.get("offers") if product else None
    if isinstance(offers, list):
        offers = offers[0] if offers else None

    if isinstance(offers, dict):
        price = offers.get("price") or offers.get("lowPrice")
        currency = offers.get("priceCurrency")
        if price not in (None, ""):
            return f"{price} {currency}".strip() if currency else str(price)

    price = product.get("price") if product else None
    currency = product.get("priceCurrency") if product else None
    if price not in (None, ""):
        return f"{price} {currency}".strip() if currency else str(price)

    return "Нет данных"


def extract_reviews_count(soup: BeautifulSoup) -> str:
    """Извлечь количество отзывов товара из JSON-LD."""
    product = {}
    for item in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw_json = item.string or item.get_text(strip=True)
        if not raw_json:
            continue
        try:
            json_data = json.loads(raw_json)
        except Exception:
            continue

        if isinstance(json_data, dict) and json_data.get("@type") == "Product":
            product = json_data
            break

        if isinstance(json_data, list):
            for entry in json_data:
                if isinstance(entry, dict) and entry.get("@type") == "Product":
                    product = entry
                    break

    aggregate = product.get("aggregateRating") if product else None
    if isinstance(aggregate, dict):
        count = aggregate.get("reviewCount") or aggregate.get("ratingCount")
        if count not in (None, ""):
            return str(count)
    return "Нет данных"


def extract_average_rating(soup: BeautifulSoup) -> str:
    """Извлечь средний рейтинг товара из JSON-LD."""
    product = {}
    for item in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw_json = item.string or item.get_text(strip=True)
        if not raw_json:
            continue
        try:
            json_data = json.loads(raw_json)
        except Exception:
            continue

        if isinstance(json_data, dict) and json_data.get("@type") == "Product":
            product = json_data
            break

        if isinstance(json_data, list):
            for entry in json_data:
                if isinstance(entry, dict) and entry.get("@type") == "Product":
                    product = entry
                    break

    aggregate = product.get("aggregateRating") if product else None
    if isinstance(aggregate, dict):
        rating = aggregate.get("ratingValue")
        if rating not in (None, ""):
            return str(rating)
    return "Нет данных"


def parse_product(soup: BeautifulSoup, link: str) -> dict:
    """
    Извлечь все данные товара со страницы.

    ВНИМАНИЕ: CSS-селекторы и data-widget атрибуты зависят от вёрстки OZON.
    При изменении структуры страницы товара необходимо обновить:
    - Селектор заголовка: div[data-widget="webProductHeading"] h1
    - Селектор галереи:   div[data-widget="webGallery"] img
    - Селектор атрибутов: div[data-widget="webShortCharacteristics"]
    - JSON-LD разметку:   script с @context

    Args:
        soup: распаршенный HTML.
        link: URL товара.

    Returns:
        Словарь с данными товара.
    """
    name = extract_text(soup, ["h1", 'div[data-widget="webProductHeading"] h1'])

    return {
        "Название": name,
        "Ссылка на товар": link,
        "Артикул": extract_article(link),
        "Цена": extract_price(soup),
        "Количество отзывов": extract_reviews_count(soup),
        "Средний отзыв": extract_average_rating(soup),
    }


def run_scraper(config: ParserConfig) -> None:
    """
    Запуск Stage 2: парсинг деталей товаров.

    Args:
        config: настройки парсера.
    """
    logger.info("=" * 60)
    logger.info("  Stage 2: Парсинг деталей товаров")
    logger.info("=" * 60)

    links_path = Path(config.links_file)
    if not links_path.exists():
        logger.error(f"Файл не найден: {config.links_file}")
        logger.error("Сначала запустите Stage 1: python run.py collect")
        return

    with open(links_path, "r", encoding="utf-8") as f:
        links = [line.strip() for line in f if line.strip()]

    if not links:
        logger.warning("Файл ссылок пуст")
        return

    logger.info(f"Ссылок для обработки: {len(links)}")

    driver = create_driver(config.chrome_path or None)

    success = 0
    errors = 0
    # Счётчики причин ошибок для итогового отчёта
    failure_reasons: Counter = Counter()

    try:
        with open(config.output_file, mode="w", encoding="utf-8", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=FIELDNAMES, delimiter=";")
            writer.writeheader()

            for i, link in enumerate(links, 1):
                try:
                    page_source = fetch_page(driver, link, pause=config.page_pause)

                    soup = BeautifulSoup(page_source, "html.parser")

                    # Проверяем, что страница не пустая
                    if not soup.find("body") or len(soup.get_text(strip=True)) < 50:
                        errors += 1
                        reason = "empty_response"
                        failure_reasons[reason] += 1
                        logger.warning(
                            f"[{i}/{len(links)}] Пустая страница: {link} "
                            f"(причина: {reason})"
                        )
                        continue

                    row = parse_product(soup, link)

                    # Проверяем, удалось ли извлечь ключевые поля
                    missing_fields = [
                        k for k in ("Название", "Артикул")
                        if row.get(k) in ("Нет данных", "Нет артикула", "")
                    ]
                    if missing_fields:
                        logger.warning(
                            f"[{i}/{len(links)}] Неполные данные для {link}: "
                            f"отсутствуют {', '.join(missing_fields)}"
                        )
                        failure_reasons["missing_fields"] += 1

                    writer.writerow(row)
                    success += 1

                    if i % 10 == 0 or i == len(links):
                        logger.info(f"[{i}/{len(links)}] Обработано: {success} | Ошибок: {errors}")

                except FetchError as e:
                    errors += 1
                    failure_reasons[e.reason] += 1
                    logger.warning(
                        f"[{i}/{len(links)}] Ошибка загрузки: {link} — "
                        f"причина: {e.reason}, попыток: {e.attempts} | {e.original}"
                    )

                except TimeoutException as e:
                    errors += 1
                    failure_reasons["timeout"] += 1
                    logger.warning(
                        f"[{i}/{len(links)}] Таймаут: {link} — {e}"
                    )

                except WebDriverException as e:
                    errors += 1
                    failure_reasons["webdriver_error"] += 1
                    logger.warning(
                        f"[{i}/{len(links)}] WebDriver ошибка: {link} — {e}"
                    )

                except Exception as e:
                    errors += 1
                    failure_reasons["unexpected_error"] += 1
                    logger.warning(
                        f"[{i}/{len(links)}] Непредвиденная ошибка: {link} — "
                        f"{type(e).__name__}: {e}"
                    )

    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        raise
    finally:
        try:
            driver.quit()
            logger.info("Браузер закрыт")
        except Exception:
            pass

    # Итоговый отчёт
    logger.info("=" * 60)
    logger.info(f"Готово! Успешно: {success} | Ошибок: {errors}")
    if failure_reasons:
        logger.info("Причины ошибок:")
        for reason, count in failure_reasons.most_common():
            logger.info(f"  {reason}: {count}")
    logger.info(f"Результат: {config.output_file}")
    logger.info("=" * 60)
