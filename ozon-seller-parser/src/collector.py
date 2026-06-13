"""
Stage 1 — Сбор ссылок на товары.
=================================
Скроллит страницу продавца на OZON и собирает все ссылки на товары.
"""

import logging
import os
import time
from collections import Counter
from pathlib import Path
from typing import Set

from bs4 import BeautifulSoup
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .config import ParserConfig
from .browser import create_driver, fetch_page, FetchError

logger = logging.getLogger(__name__)


def load_existing_links(filepath: str) -> Set[str]:
    """Загрузить уже собранные ссылки для инкрементального сбора."""
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()


def scroll_and_collect(driver, config: ParserConfig) -> Set[str]:
    """
    Скроллить страницу и собирать ссылки на товары.

    Args:
        driver: экземпляр WebDriver.
        config: настройки парсера.

    Returns:
        Множество URL товаров.
    """
    seen_links: Set[str] = set()
    previous_height = 0
    retries_left = config.max_retries
    start_time = time.time()
    scroll_num = 0

    while time.time() - start_time < config.scroll_timeout:
        scroll_num += 1
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(config.scroll_pause)

        new_height = driver.execute_script("return document.body.scrollHeight")

        if new_height == previous_height:
            retries_left -= 1
            if retries_left <= 0:
                logger.info("Новые товары не загружаются — завершаем скроллинг")
                break
        else:
            retries_left = config.max_retries
            previous_height = new_height

        # Сбор ссылок из DOM
        # ВНИМАНИЕ: CSS-селекторы зависят от вёрстки OZON.
        # При изменении структуры страницы нужно обновить селекторы ниже.
        # Актуальные классы: div.tile-root, a.tile-clickable-element
        try:
            soup = BeautifulSoup(driver.page_source, "html.parser")
            for item in soup.select("div.tile-root a.tile-clickable-element[href]"):
                raw_url = "https://www.ozon.ru" + item["href"]
                clean_url = raw_url.split("?", 1)[0]
                if clean_url.startswith("https://www.ozon.ru/product/"):
                    seen_links.add(clean_url)
        except Exception as e:
            logger.warning(f"Ошибка при сборе ссылок: {e}")

        if scroll_num % 5 == 0:
            logger.info(f"Скролл #{scroll_num} | Найдено: {len(seen_links)} | Попыток: {retries_left}")

    elapsed = int(time.time() - start_time)
    logger.info(f"Скроллинг завершён за {elapsed} сек. Собрано: {len(seen_links)} ссылок")

    return seen_links


def save_links(links: Set[str], existing: Set[str], filepath: str) -> int:
    """
    Сохранить новые ссылки в файл (инкрементально).

    Returns:
        Количество добавленных ссылок.
    """
    added = 0
    with open(filepath, "a", encoding="utf-8") as f:
        for link in sorted(links):
            if link not in existing:
                f.write(link + "\n")
                existing.add(link)
                added += 1

    return added


def run_collector(config: ParserConfig) -> None:
    """
    Запуск Stage 1: сбор ссылок на товары.

    Args:
        config: настройки парсера.
    """
    logger.info("=" * 60)
    logger.info("  Stage 1: Сбор ссылок на товары")
    logger.info("=" * 60)

    existing_links = load_existing_links(config.links_file)
    logger.info(f"Уже собрано ссылок: {len(existing_links)}")

    # Счётчики ошибок для итогового отчёта
    failure_reasons: Counter = Counter()

    driver = create_driver(config.chrome_path or None)

    try:
        logger.info(f"Открытие: {config.seller_url}")
        fetch_page(driver, config.seller_url)

        # Ждём загрузки первых товаров
        try:
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.tile-root"))
            )
        except TimeoutException:
            failure_reasons["selector_not_found"] += 1
            logger.error(
                "Таймаут: элемент div.tile-root не найден на странице продавца. "
                "Возможно, изменилась вёрстка OZON или страница не загрузилась."
            )
            raise

        logger.info("Страница загружена, начинаю скроллинг...")

        # Сбор ссылок
        all_links = scroll_and_collect(driver, config)
        new_links = all_links - existing_links

        # Сохранение
        added = save_links(new_links, existing_links, config.links_file)
        total = len(existing_links)

        # Итоговый отчёт
        logger.info("=" * 60)
        logger.info(f"Добавлено новых: {added}")
        logger.info(f"Всего в файле: {total}")
        if failure_reasons:
            logger.info("Ошибки при сборе:")
            for reason, count in failure_reasons.most_common():
                logger.info(f"  {reason}: {count}")
        logger.info("=" * 60)

    except FetchError as e:
        failure_reasons[e.reason] += 1
        logger.error(
            f"Не удалось загрузить страницу продавца: {config.seller_url} — "
            f"причина: {e.reason}, попыток: {e.attempts}"
        )
        raise

    except TimeoutException as e:
        failure_reasons["timeout"] += 1
        logger.error(f"Таймаут при загрузке страницы продавца: {e}")
        raise

    except WebDriverException as e:
        failure_reasons["webdriver_error"] += 1
        logger.error(f"WebDriver ошибка: {e}")
        raise

    except Exception as e:
        failure_reasons["unexpected_error"] += 1
        logger.error(f"Непредвиденная ошибка: {type(e).__name__}: {e}")
        raise

    finally:
        try:
            driver.quit()
            logger.info("Браузер закрыт")
        except Exception:
            pass
