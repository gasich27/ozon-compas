from pathlib import Path

import pytest

from app.sources.competitor_parser.csv_reader import (
    CompetitorCsvError,
    CompetitorCsvReader,
    parse_price,
    parse_rating,
    parse_reviews_count,
)


def test_reads_russian_columns_and_parses_values(tmp_path: Path) -> None:
    csv_path = tmp_path / "products.csv"
    csv_path.write_text(
        "Название;Ссылка на товар;Артикул;Цена;Количество отзывов;Средний отзыв\n"
        "Товар;https://www.ozon.ru/product/test-123/;123;"
        "1\u00a0240 ₽;1 240 отзывов;Средний отзыв: 4,8\n",
        encoding="utf-8",
    )

    products = CompetitorCsvReader().load(csv_path)

    assert len(products) == 1
    assert products[0].price == 1240.0
    assert products[0].reviews_count == 1240
    assert products[0].average_rating == 4.8
    assert products[0].position == 1


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1 240 ₽", 1240.0), ("3\u00a0490,50 RUB", 3490.5), ("NaN", None)],
)
def test_parse_price(value, expected) -> None:
    assert parse_price(value) == expected


def test_parse_reviews_count() -> None:
    assert parse_reviews_count("1 240 отзывов") == 1240
    assert parse_reviews_count("") is None


def test_parse_rating() -> None:
    assert parse_rating("Средний отзыв: 4.8") == 4.8
    assert parse_rating("4,7") == 4.7


def test_limit(tmp_path: Path) -> None:
    csv_path = tmp_path / "products.csv"
    csv_path.write_text(
        "Название;Ссылка на товар;Артикул;Цена;Количество отзывов;Средний отзыв\n"
        "A;https://ozon.ru/a;1;100;1;4\n"
        "B;https://ozon.ru/b;2;200;2;5\n",
        encoding="utf-8",
    )
    assert len(CompetitorCsvReader().load(csv_path, limit=1)) == 1


def test_missing_required_column_has_clear_error(tmp_path: Path) -> None:
    csv_path = tmp_path / "products.csv"
    csv_path.write_text("Название;Цена\nA;100\n", encoding="utf-8")
    with pytest.raises(CompetitorCsvError, match="обязательные колонки"):
        CompetitorCsvReader().load(csv_path)
