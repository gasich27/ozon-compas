from __future__ import annotations

import csv
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from app.models import CompetitorProduct


REQUIRED_COLUMNS = {
    "Название",
    "Ссылка на товар",
    "Артикул",
    "Цена",
    "Количество отзывов",
    "Средний отзыв",
}
EMPTY_VALUES = {"", "-", "nan", "none", "null", "нет данных"}


class CompetitorCsvError(ValueError):
    pass


def _normalized(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\xa0", " ").strip()


def _is_empty(value: object) -> bool:
    text = _normalized(value).lower()
    return text in EMPTY_VALUES


def parse_price(value: object) -> float | None:
    if _is_empty(value):
        return None
    text = _normalized(value).replace(",", ".")
    match = re.search(r"-?\d[\d\s]*(?:\.\d+)?", text)
    if not match:
        return None
    number = match.group(0).replace(" ", "")
    try:
        result = float(number)
    except ValueError:
        return None
    return None if math.isnan(result) else result


def parse_reviews_count(value: object) -> int | None:
    if _is_empty(value):
        return None
    match = re.search(r"\d[\d\s]*", _normalized(value))
    if not match:
        return None
    try:
        return int(match.group(0).replace(" ", ""))
    except ValueError:
        return None


def parse_rating(value: object) -> float | None:
    if _is_empty(value):
        return None
    text = _normalized(value).replace(",", ".")
    numbers = re.findall(r"\d+(?:\.\d+)?", text)
    if not numbers:
        return None
    try:
        result = float(numbers[-1])
    except ValueError:
        return None
    return None if math.isnan(result) else result


class CompetitorCsvReader:
    def __init__(self, encoding: str = "utf-8"):
        self.encoding = encoding

    def load(
        self, path: str | Path, limit: int | None = None
    ) -> list[CompetitorProduct]:
        csv_path = Path(path)
        if not csv_path.exists():
            raise CompetitorCsvError(f"CSV-файл не найден: {csv_path}")
        if limit is not None and limit < 1:
            raise CompetitorCsvError("limit должен быть положительным целым числом.")

        encoding = "utf-8-sig" if self.encoding.lower() == "utf-8" else self.encoding
        try:
            with csv_path.open("r", encoding=encoding, newline="") as handle:
                sample = handle.read(4096)
                handle.seek(0)
                delimiter = self._detect_delimiter(sample)
                reader = csv.DictReader(handle, delimiter=delimiter)
                columns = {column.strip() for column in (reader.fieldnames or [])}
                missing = sorted(REQUIRED_COLUMNS - columns)
                if missing:
                    raise CompetitorCsvError(
                        "В CSV отсутствуют обязательные колонки: "
                        + ", ".join(missing)
                    )

                collected_at = datetime.now(timezone.utc)
                products: list[CompetitorProduct] = []
                for position, raw_row in enumerate(reader, 1):
                    row = {
                        (key.strip() if key else key): value
                        for key, value in raw_row.items()
                    }
                    products.append(
                        CompetitorProduct(
                            name=_normalized(row.get("Название")),
                            product_url=_normalized(row.get("Ссылка на товар")),
                            sku=_normalized(row.get("Артикул")),
                            price=parse_price(row.get("Цена")),
                            reviews_count=parse_reviews_count(
                                row.get("Количество отзывов")
                            ),
                            average_rating=parse_rating(row.get("Средний отзыв")),
                            position=position,
                            collected_at=collected_at,
                        )
                    )
                    if limit is not None and len(products) >= limit:
                        break
                return products
        except UnicodeError as exc:
            raise CompetitorCsvError(
                f"Не удалось прочитать CSV в кодировке {self.encoding}: {exc}"
            ) from exc

    @staticmethod
    def _detect_delimiter(sample: str) -> str:
        try:
            return csv.Sniffer().sniff(sample, delimiters=";,\t").delimiter
        except csv.Error:
            return ";"
