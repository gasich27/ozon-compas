# OZON Seller Parser

![Python](https://img.shields.io/badge/Python-3.8+-blue?logo=python&logoColor=white)
![Selenium](https://img.shields.io/badge/Selenium-4.x-green?logo=selenium&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-yellow)

Парсер товаров продавца на маркетплейсе OZON. Двухэтапный пайплайн: сбор ссылок + парсинг деталей. Модульная архитектура, конфигурация через JSON, логирование.

## Возможности

- Автоматический скроллинг с обходом антибот-защиты (`undetected-chromedriver`)
- Инкрементальный сбор (не дублирует уже собранные ссылки)
- Извлечение: название, артикул, автор, серия, год, описание, изображение
- Конфигурация через `config.json` (без хардкода URL в коде)
- Логирование в файл и консоль
- Экспорт в CSV

## Структура

```
ozon-seller-parser/
├── run.py                  # Точка входа (CLI)
├── config.example.json     # Шаблон конфигурации
├── requirements.txt        # Зависимости
├── src/
│   ├── __init__.py
│   ├── config.py           # Конфигурация (dataclass)
│   ├── browser.py          # Инициализация WebDriver
│   ├── collector.py        # Stage 1: сбор ссылок
│   └── scraper.py          # Stage 2: парсинг деталей
├── CHANGELOG.md
├── LICENSE
└── README.md
```

## Установка

```bash
git clone https://github.com/al-nemirov/ozon-seller-parser.git
cd ozon-seller-parser
pip install -r requirements.txt
```

### Зависимости

| Пакет | Назначение |
|-------|-----------|
| `selenium` | Управление браузером |
| `undetected-chromedriver` | Обход антибот-защиты OZON |
| `beautifulsoup4` | Парсинг HTML |
| `pandas` | Работа с данными |

## Быстрый старт

### 1. Конфигурация

```bash
cp config.example.json config.json
```

Отредактируйте `config.json` — укажите URL продавца:

```json
{
    "seller_url": "https://www.ozon.ru/seller/your-shop-123456/books-16500/",
    "scroll_pause": 5,
    "page_pause": 7,
    "max_retries": 50
}
```

### 2. Сбор ссылок (Stage 1)

```bash
python run.py collect
```

Скрипт откроет браузер, проскроллит страницу и соберёт ссылки в `product_links.txt`.

### 3. Парсинг деталей (Stage 2)

```bash
python run.py scrape
```

Откроет каждую ссылку и соберёт данные в `product_details.csv`.

### 4. Всё сразу

```bash
python run.py all
```

## Конфигурация

| Параметр | По умолчанию | Описание |
|----------|:------------:|----------|
| `seller_url` | — | URL страницы продавца (обязательно) |
| `chrome_path` | `""` | Путь к Chrome (пусто = системный) |
| `links_file` | `product_links.txt` | Файл для ссылок |
| `output_file` | `product_details.csv` | Файл с результатами |
| `scroll_pause` | `5` | Пауза между скроллами (сек) |
| `page_pause` | `7` | Пауза между страницами (сек) |
| `max_retries` | `50` | Попыток без новых товаров |
| `implicit_wait` | `15` | Таймаут ожидания элементов |
| `scroll_timeout` | `1200` | Макс. время скроллинга (сек) |

## Результат

CSV-файл (`product_details.csv`) с разделителем `;`:

| Поле | Описание |
|------|----------|
| Название | Название товара |
| Ссылка на товар | URL страницы |
| Изображение | URL главного фото |
| Артикул | ID товара на OZON |
| Автор | Автор (для книг) |
| Серия | Серия (для книг) |
| Год выпуска | Год издания |
| Описание | Полное описание товара |

## Важно

- Используйте на свой риск — парсинг может нарушать ToS OZON
- При большом количестве товаров процесс занимает часы
- Рекомендуется VPN для стабильной работы

## Как это работает

**Stage 1: collect** → скроллинг страницы продавца, сбор ссылок → `product_links.txt`

**Stage 2: scrape** → парсинг каждого товара (Selenium + BS4): название, артикул, описание → `product_details.csv`

## Участие в разработке

1. Форк репозитория
2. Создайте ветку (`git checkout -b feature/my-feature`)
3. Коммит (`git commit -m "feat: описание"`)
4. Пуш (`git push origin feature/my-feature`)
5. Откройте Pull Request

## Лицензия

[MIT](LICENSE)
