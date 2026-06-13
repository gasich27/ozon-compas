"""
Конфигурация парсера.
=====================
Все настройки вынесены в один файл для удобства.
Скопируйте config.example.json -> config.json и заполните свои данные.
"""

import json
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT_DIR / "config.json"
DEFAULT_CONFIG_FILE = ROOT_DIR / "config.example.json"

# Допустимые ключи конфигурации (совпадают с полями dataclass)
KNOWN_CONFIG_KEYS = {
    "seller_url", "chrome_path", "links_file", "output_file", "log_file",
    "scroll_pause", "page_pause", "max_retries", "implicit_wait", "scroll_timeout",
}

# Правила валидации: (тип, мин_значение_или_None)
_FIELD_RULES = {
    "seller_url":     (str, None),
    "chrome_path":    (str, None),
    "links_file":     (str, None),
    "output_file":    (str, None),
    "log_file":       (str, None),
    "scroll_pause":   (int, 1),
    "page_pause":     (int, 1),
    "max_retries":    (int, 1),
    "implicit_wait":  (int, 1),
    "scroll_timeout": (int, 1),
}


@dataclass
class ParserConfig:
    """Настройки парсера."""

    # URL страницы продавца на OZON
    seller_url: str = ""

    # Путь к браузеру (пустая строка = системный Chrome)
    chrome_path: str = ""

    # Файл со ссылками на товары
    links_file: str = "product_links.txt"

    # Файл с результатами парсинга
    output_file: str = "product_details.csv"

    # Лог-файл
    log_file: str = "parser.log"

    # Пауза между скроллами (секунды)
    scroll_pause: int = 5

    # Пауза между загрузкой страниц товаров (секунды)
    page_pause: int = 7

    # Максимум попыток без новых товаров перед остановкой
    max_retries: int = 50

    # Таймаут ожидания элементов (секунды)
    implicit_wait: int = 15

    # Таймаут скроллинга (секунды)
    scroll_timeout: int = 1200

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "ParserConfig":
        """Загрузить конфигурацию из JSON-файла."""
        config_path = path or CONFIG_FILE

        if not config_path.exists():
            print(f"Конфигурация не найдена: {config_path}")
            print(f"Скопируйте config.example.json -> config.json и заполните данные.")
            sys.exit(1)

        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)

        # Проверяем наличие неизвестных ключей
        unknown_keys = set(data.keys()) - KNOWN_CONFIG_KEYS
        if unknown_keys:
            print(f"Ошибка: неизвестные ключи в config.json: {', '.join(sorted(unknown_keys))}")
            print(f"Допустимые ключи: {', '.join(sorted(KNOWN_CONFIG_KEYS))}")
            sys.exit(1)

        # Проверяем типы и значения каждого поля
        errors = []
        for key, value in data.items():
            if key not in _FIELD_RULES:
                continue

            expected_type, min_value = _FIELD_RULES[key]

            if not isinstance(value, expected_type):
                errors.append(
                    f"  {key}: ожидается {expected_type.__name__}, "
                    f"получено {type(value).__name__} ({value!r})"
                )
                continue

            if min_value is not None and isinstance(value, (int, float)) and value < min_value:
                errors.append(
                    f"  {key}: значение {value} меньше минимального ({min_value})"
                )

        if errors:
            print("Ошибки валидации config.json:")
            for err in errors:
                print(err)
            sys.exit(1)

        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def validate(self) -> None:
        """Проверить обязательные поля и диапазоны значений."""
        errors = []

        # seller_url: обязательное поле
        if not self.seller_url or "YOUR-SELLER" in self.seller_url:
            errors.append(
                "seller_url: укажите URL страницы продавца. "
                "Пример: https://www.ozon.ru/seller/my-shop-123456/books-16500/"
            )

        # Строковые поля: не пустые
        for field_name in ("links_file", "output_file", "log_file"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{field_name}: не может быть пустым")

        # Числовые поля: положительные
        numeric_fields = {
            "scroll_pause":  "пауза между скроллами",
            "page_pause":    "пауза между страницами",
            "max_retries":   "максимум попыток",
            "implicit_wait": "таймаут ожидания",
            "scroll_timeout": "таймаут скроллинга",
        }
        for field_name, description in numeric_fields.items():
            value = getattr(self, field_name)
            if not isinstance(value, int) or value < 1:
                errors.append(
                    f"{field_name} ({description}): "
                    f"должно быть целое число > 0, получено {value!r}"
                )

        if errors:
            print("Ошибки валидации конфигурации:")
            for err in errors:
                print(f"  {err}")
            sys.exit(1)
