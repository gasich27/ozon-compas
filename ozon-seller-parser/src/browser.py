"""
Управление браузером.
=====================
Инициализация undetected-chromedriver с обходом антибот-защиты.
Вспомогательные функции: таймауты, retry-загрузка страниц.
"""

import logging
import time
from typing import Optional

import undetected_chromedriver as uc
from selenium.common.exceptions import TimeoutException, WebDriverException

logger = logging.getLogger(__name__)

# Настройки таймаутов WebDriver (секунды)
PAGE_LOAD_TIMEOUT = 30
SCRIPT_TIMEOUT = 15
IMPLICIT_WAIT_TIMEOUT = 10

# Настройки retry-логики
MAX_RETRIES = 3
BACKOFF_BASE = 2  # секунды: 2, 4, 8

# HTTP-коды, при которых стоит повторить запрос
RETRYABLE_STATUS_PHRASES = ["429", "500", "502", "503", "504"]


def create_driver(chrome_path: Optional[str] = None) -> uc.Chrome:
    """
    Создать экземпляр браузера с обходом антибот-защиты.

    Args:
        chrome_path: путь к исполняемому файлу Chrome (None = системный).

    Returns:
        Настроенный экземпляр Chrome WebDriver.
    """
    options = uc.ChromeOptions()

    if chrome_path:
        options.binary_location = chrome_path

    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")

    logger.info("Запуск браузера...")
    driver = uc.Chrome(options=options)

    # Установка таймаутов WebDriver
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    driver.set_script_timeout(SCRIPT_TIMEOUT)
    driver.implicitly_wait(IMPLICIT_WAIT_TIMEOUT)

    logger.info(
        f"Таймауты: page_load={PAGE_LOAD_TIMEOUT}s, "
        f"script={SCRIPT_TIMEOUT}s, implicit_wait={IMPLICIT_WAIT_TIMEOUT}s"
    )

    return driver


def fetch_page(driver, url: str, pause: float = 0) -> str:
    """
    Загрузить страницу с retry-логикой и экспоненциальным backoff.

    При ошибках (timeout, connection error, HTTP 429/5xx) делает до
    MAX_RETRIES повторных попыток с задержкой 2, 4, 8 секунд.

    Args:
        driver: экземпляр WebDriver.
        url: URL для загрузки.
        pause: пауза после успешной загрузки (секунды).

    Returns:
        page_source: HTML-код страницы.

    Raises:
        FetchError: если все попытки исчерпаны.
    """
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            driver.get(url)

            if pause > 0:
                time.sleep(pause)

            # Проверяем заголовок страницы на признаки HTTP-ошибок
            title = driver.title or ""
            for phrase in RETRYABLE_STATUS_PHRASES:
                if phrase in title:
                    raise WebDriverException(f"Страница вернула HTTP {phrase}: {title}")

            return driver.page_source

        except TimeoutException as e:
            last_error = e
            reason = "timeout"
        except WebDriverException as e:
            last_error = e
            error_msg = str(e).lower()
            if any(kw in error_msg for kw in ("timeout", "timed out", "net::err_", "429", "500", "502", "503", "504")):
                reason = "retriable_error"
            else:
                raise FetchError(url, attempt, "webdriver_error", e)
        except Exception as e:
            raise FetchError(url, attempt, "unexpected_error", e)

        if attempt < MAX_RETRIES:
            backoff = BACKOFF_BASE ** attempt
            logger.warning(
                f"[retry {attempt}/{MAX_RETRIES}] {reason}: {url} — "
                f"повтор через {backoff}s"
            )
            time.sleep(backoff)

    raise FetchError(url, MAX_RETRIES, reason, last_error)


class FetchError(Exception):
    """Ошибка загрузки страницы после всех попыток."""

    def __init__(self, url: str, attempts: int, reason: str, original: Optional[Exception] = None):
        self.url = url
        self.attempts = attempts
        self.reason = reason
        self.original = original
        super().__init__(
            f"Не удалось загрузить {url} после {attempts} попыток "
            f"(причина: {reason}): {original}"
        )
