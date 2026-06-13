"""
Тесты CSS-селекторов и логики извлечения данных.
=================================================
Проверяют, что парсер корректно извлекает данные из HTML-фикстур.
"""

import json
import sys
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

# Добавляем корень проекта в sys.path для импорта src
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.scraper import (
    extract_text,
    extract_description,
    extract_article,
    extract_attribute,
    parse_product,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> BeautifulSoup:
    """Загрузить HTML-фикстуру и вернуть BeautifulSoup."""
    filepath = FIXTURES_DIR / name
    with open(filepath, "r", encoding="utf-8") as f:
        return BeautifulSoup(f.read(), "html.parser")


# ────────────────────────────────────────────────────────────
# Тесты: извлечение текста по CSS-селекторам
# ────────────────────────────────────────────────────────────

class TestExtractText(unittest.TestCase):
    """Тесты функции extract_text."""

    def setUp(self):
        self.soup = load_fixture("product_page.html")

    def test_extract_heading_by_h1(self):
        """Извлечение заголовка через h1."""
        result = extract_text(self.soup, ["h1"])
        self.assertIn("Тестовый товар", result)

    def test_extract_heading_by_widget_selector(self):
        """Извлечение заголовка через data-widget селектор."""
        result = extract_text(
            self.soup,
            ['div[data-widget="webProductHeading"] h1'],
        )
        self.assertIn("Тестовый товар", result)

    def test_extract_text_fallback_to_default(self):
        """Возврат значения по умолчанию, если селектор не найден."""
        result = extract_text(self.soup, ["div.nonexistent-class"])
        self.assertEqual(result, "Нет данных")

    def test_extract_text_custom_default(self):
        """Использование пользовательского значения по умолчанию."""
        result = extract_text(self.soup, ["div.missing"], default="N/A")
        self.assertEqual(result, "N/A")

    def test_extract_text_first_match_wins(self):
        """Первый подходящий селектор из списка используется."""
        result = extract_text(
            self.soup,
            ["div.missing", "h1", "title"],
        )
        self.assertIn("Тестовый товар", result)


# ────────────────────────────────────────────────────────────
# Тесты: извлечение описания из JSON-LD
# ────────────────────────────────────────────────────────────

class TestExtractDescription(unittest.TestCase):
    """Тесты функции extract_description."""

    def test_extract_description_from_jsonld(self):
        """Описание извлекается из JSON-LD разметки."""
        soup = load_fixture("product_page.html")
        result = extract_description(soup)
        self.assertIn("Описание тестового товара", result)

    def test_extract_description_no_jsonld(self):
        """Возврат 'Нет описания' при отсутствии JSON-LD."""
        soup = load_fixture("product_no_jsonld.html")
        result = extract_description(soup)
        self.assertEqual(result, "Нет описания")

    def test_extract_description_empty_page(self):
        """Возврат 'Нет описания' для пустой страницы."""
        soup = load_fixture("empty_page.html")
        result = extract_description(soup)
        self.assertEqual(result, "Нет описания")


# ────────────────────────────────────────────────────────────
# Тесты: извлечение артикула из URL
# ────────────────────────────────────────────────────────────

class TestExtractArticle(unittest.TestCase):
    """Тесты функции extract_article."""

    def test_extract_article_normal_url(self):
        """Артикул извлекается из стандартного URL."""
        url = "https://www.ozon.ru/product/kniga-testovaya-12345/"
        self.assertEqual(extract_article(url), "12345")

    def test_extract_article_long_id(self):
        """Артикул извлекается при длинном числовом ID."""
        url = "https://www.ozon.ru/product/some-product-name-9876543210/"
        self.assertEqual(extract_article(url), "9876543210")

    def test_extract_article_no_match(self):
        """Возврат 'Нет артикула' при нестандартном URL."""
        url = "https://www.ozon.ru/category/books/"
        self.assertEqual(extract_article(url), "Нет артикула")

    def test_extract_article_no_trailing_slash(self):
        """Артикул извлекается из URL без завершающего слэша."""
        url = "https://www.ozon.ru/product/kniga-12345"
        self.assertEqual(extract_article(url), "12345")


# ────────────────────────────────────────────────────────────
# Тесты: извлечение атрибутов товара
# ────────────────────────────────────────────────────────────

class TestExtractAttribute(unittest.TestCase):
    """Тесты функции extract_attribute."""

    def setUp(self):
        self.soup = load_fixture("product_page.html")

    def test_extract_author(self):
        """Автор извлекается по паттерну person."""
        result = extract_attribute(self.soup, "person")
        self.assertEqual(result, "Иванов И.И.")

    def test_extract_series(self):
        """Серия извлекается по паттерну series."""
        result = extract_attribute(self.soup, "series")
        self.assertEqual(result, "Книжная серия")

    def test_extract_missing_attribute(self):
        """Возврат 'Нет данных' для несуществующего атрибута."""
        result = extract_attribute(self.soup, "publisher")
        self.assertEqual(result, "Нет данных")

    def test_extract_attribute_no_characteristics(self):
        """Возврат 'Нет данных', если блок характеристик пуст."""
        soup = load_fixture("product_no_jsonld.html")
        result = extract_attribute(soup, "person")
        self.assertEqual(result, "Нет данных")


# ────────────────────────────────────────────────────────────
# Тесты: полный парсинг страницы товара
# ────────────────────────────────────────────────────────────

class TestParseProduct(unittest.TestCase):
    """Тесты функции parse_product."""

    def test_parse_full_product(self):
        """Полный парсинг товара из фикстуры."""
        soup = load_fixture("product_page.html")
        link = "https://www.ozon.ru/product/kniga-testovaya-12345/"
        result = parse_product(soup, link)

        self.assertIn("Тестовый товар", result["Название"])
        self.assertEqual(result["Ссылка на товар"], link)
        self.assertEqual(result["Артикул"], "12345")
        self.assertEqual(result["Цена"], "Нет данных")
        self.assertEqual(result["Количество отзывов"], "Нет данных")
        self.assertEqual(result["Средний отзыв"], "Нет данных")

    def test_parse_product_without_jsonld(self):
        """Парсинг товара без JSON-LD разметки."""
        soup = load_fixture("product_no_jsonld.html")
        link = "https://www.ozon.ru/product/tovar-bez-jsonld-99999/"
        result = parse_product(soup, link)

        self.assertIn("Товар без JSON-LD", result["Название"])
        self.assertEqual(result["Артикул"], "99999")
        self.assertEqual(result["Цена"], "Нет данных")

    def test_parse_product_empty_page(self):
        """Парсинг пустой страницы — все поля с дефолтами."""
        soup = load_fixture("empty_page.html")
        link = "https://www.ozon.ru/product/empty-00000/"
        result = parse_product(soup, link)

        self.assertEqual(result["Название"], "Нет данных")
        self.assertEqual(result["Цена"], "Нет данных")


# ────────────────────────────────────────────────────────────
# Тесты: извлечение ссылок со страницы продавца
# ────────────────────────────────────────────────────────────

class TestSellerPageSelectors(unittest.TestCase):
    """Тесты CSS-селекторов для страницы продавца."""

    def setUp(self):
        self.soup = load_fixture("seller_page.html")

    def test_tile_root_count(self):
        """На странице 5 блоков tile-root."""
        tiles = self.soup.select("div.tile-root")
        self.assertEqual(len(tiles), 5)

    def test_product_links_extracted(self):
        """Извлечение только товарных ссылок (с /product/)."""
        links = set()
        for item in self.soup.select("div.tile-root a.tile-clickable-element[href]"):
            raw_url = "https://www.ozon.ru" + item["href"]
            clean_url = raw_url.split("?", 1)[0]
            if clean_url.startswith("https://www.ozon.ru/product/"):
                links.add(clean_url)

        self.assertEqual(len(links), 3)
        self.assertIn("https://www.ozon.ru/product/kniga-pervaya-12345/", links)
        self.assertIn("https://www.ozon.ru/product/kniga-vtoraya-67890/", links)
        self.assertIn("https://www.ozon.ru/product/kniga-tretya-11111/", links)

    def test_query_params_stripped(self):
        """Параметры запроса удаляются из URL."""
        links = set()
        for item in self.soup.select("div.tile-root a.tile-clickable-element[href]"):
            raw_url = "https://www.ozon.ru" + item["href"]
            clean_url = raw_url.split("?", 1)[0]
            if clean_url.startswith("https://www.ozon.ru/product/"):
                links.add(clean_url)

        for link in links:
            self.assertNotIn("?", link)

    def test_non_product_links_excluded(self):
        """Ссылки на категории не попадают в выборку."""
        links = set()
        for item in self.soup.select("div.tile-root a.tile-clickable-element[href]"):
            raw_url = "https://www.ozon.ru" + item["href"]
            clean_url = raw_url.split("?", 1)[0]
            if clean_url.startswith("https://www.ozon.ru/product/"):
                links.add(clean_url)

        for link in links:
            self.assertNotIn("/category/", link)


# ────────────────────────────────────────────────────────────
# Тесты: валидация конфигурации
# ────────────────────────────────────────────────────────────

class TestConfigValidation(unittest.TestCase):
    """Тесты валидации конфигурации."""

    def test_valid_config_loads(self):
        """Корректная конфигурация загружается без ошибок."""
        from src.config import ParserConfig
        config = ParserConfig(
            seller_url="https://www.ozon.ru/seller/test-123/books/",
            scroll_pause=5,
            page_pause=7,
            max_retries=50,
            implicit_wait=15,
            scroll_timeout=1200,
        )
        # validate() не должен вызвать sys.exit
        config.validate()

    def test_invalid_seller_url_rejected(self):
        """Пустой seller_url вызывает ошибку."""
        from src.config import ParserConfig
        config = ParserConfig(seller_url="")
        with self.assertRaises(SystemExit):
            config.validate()

    def test_placeholder_seller_url_rejected(self):
        """Placeholder seller_url вызывает ошибку."""
        from src.config import ParserConfig
        config = ParserConfig(
            seller_url="https://www.ozon.ru/seller/YOUR-SELLER-SLUG/CATEGORY/",
        )
        with self.assertRaises(SystemExit):
            config.validate()

    def test_zero_scroll_pause_rejected(self):
        """Нулевое значение scroll_pause вызывает ошибку."""
        from src.config import ParserConfig
        config = ParserConfig(
            seller_url="https://www.ozon.ru/seller/test-123/books/",
            scroll_pause=0,
        )
        with self.assertRaises(SystemExit):
            config.validate()

    def test_negative_page_pause_rejected(self):
        """Отрицательное значение page_pause вызывает ошибку."""
        from src.config import ParserConfig
        config = ParserConfig(
            seller_url="https://www.ozon.ru/seller/test-123/books/",
            page_pause=-1,
        )
        with self.assertRaises(SystemExit):
            config.validate()

    def test_unknown_keys_rejected(self):
        """Неизвестные ключи в JSON отклоняются при загрузке."""
        import json
        import tempfile
        from src.config import ParserConfig

        bad_config = {
            "seller_url": "https://www.ozon.ru/seller/test-123/books/",
            "unknown_field": "value",
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(bad_config, f)
            tmp_path = Path(f.name)

        try:
            with self.assertRaises(SystemExit):
                ParserConfig.load(tmp_path)
        finally:
            tmp_path.unlink()

    def test_wrong_type_rejected(self):
        """Неверный тип значения отклоняется при загрузке."""
        import json
        import tempfile
        from src.config import ParserConfig

        bad_config = {
            "seller_url": "https://www.ozon.ru/seller/test-123/books/",
            "scroll_pause": "not_a_number",
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(bad_config, f)
            tmp_path = Path(f.name)

        try:
            with self.assertRaises(SystemExit):
                ParserConfig.load(tmp_path)
        finally:
            tmp_path.unlink()


if __name__ == "__main__":
    unittest.main()
