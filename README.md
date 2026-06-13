# Ozon Seller Radar

### CLI/backend-сервис для хранения товаров селлера Ozon, анализа конкурентов и сравнения товара селлера с рынком.

## Установка

```bash
python -m pip install -r requirements.txt
copy .env.example .env
```

По умолчанию SQLite создаётся в `data/ozon_seller_radar.db`, а отчёты — в
`reports/`.

## External Ozon parser integration

Внешний парсер уже существует отдельно в директории `ozon-seller-parser`.
Ozon Seller Radar не изменяет его внутреннюю логику: он запускает parser как
subprocess, ожидает CSV, читает результат и передаёт его в аналитику.

Парсер может открыть окно Chrome. Не закрывайте окно до завершения. Парсинг
может занимать несколько минут или дольше в зависимости от количества товаров
и скорости загрузки.

Настройте `.env`:

```dotenv
EXTERNAL_PARSER_PATH=ozon-seller-parser
EXTERNAL_PARSER_OUTPUT_DIR=data/parser_output
EXTERNAL_PARSER_TIMEOUT=900
```

Если внешний парсер требует `config.json`, ChromeDriver или ручную настройку,
настройте его отдельно по его README. Ozon Seller Radar не меняет внутренности
парсера.

### External parser integration notes

- Путь в текущем workspace: `ozon-seller-parser/`.
- Entrypoint: `run.py`.
- Фактические команды: `python run.py collect`, `python run.py scrape`,
  `python run.py all`.
- Интеграция использует `python run.py all`.
- URL не поддерживается аргументом CLI. Он передаётся через существующее поле
  `seller_url` в обязательном `config.json`.
- `limit` и headless-режим parser не поддерживает. `limit` применяется только
  при чтении готового CSV.
- `config.json` обязателен. Runner временно меняет только `seller_url`,
  `links_file`, `output_file` и `log_file`, затем восстанавливает файл.
- Имя CSV задаётся полем `output_file`; runner создаёт уникальное имя в
  `EXTERNAL_PARSER_OUTPUT_DIR`.
- CSV имеет разделитель `;` и колонки: `Название`, `Ссылка на товар`,
  `Артикул`, `Цена`, `Количество отзывов`, `Средний отзыв`.
- Используются Selenium и `undetected-chromedriver`; требуется Chrome. Окно
  браузера открывается, headless-опции нет.
- Верхнеуровневая ошибка и неверная команда завершаются exit code `1`, успех —
  `0`. Некоторые ранние выходы stage `scrape` могут вернуть `0` без CSV,
  поэтому runner отдельно проверяет свежий выходной файл.
- stdout/stderr subprocess сохраняются рядом с parser output.

## Команды

Seller API mode:

```bash
python main.py seller check-api
python main.py seller sync
python main.py seller list
python main.py seller show --seller-product-id 123456
python main.py seller analyze
```

For Seller API mode you need `OZON_CLIENT_ID` and `OZON_API_KEY` in `.env`.

Анализ уже готового CSV:

```bash
python main.py competitors analyze-csv --input data/parser_output/products.csv
```

Запуск внешнего парсера и анализ:

```bash
python main.py competitors parse --url "https://www.ozon.ru/search/?text=рюкзак+мужской" --yes
```

Без `--yes` CLI покажет предупреждение и запросит подтверждение.

Сравнение товара селлера с готовым CSV:

```bash
python main.py compare product --seller-product-id 123456 --competitors-csv data/parser_output/products.csv
```

Сравнение товара селлера с запуском парсера:

```bash
python main.py compare product --seller-product-id 123456 --competitors-url "https://www.ozon.ru/search/?text=рюкзак+мужской" --yes
```

Для сравнения товар должен уже находиться в таблице `seller_products`, которая
заполняется Seller API workflow. Если товара нет, CLI выводит:
`Товар селлера не найден. Сначала выполните seller sync.`

## Отчёты

Аналитика конкурентов создаёт:

```text
reports/competitors_external_parser_{timestamp}/
├── competitors_summary.txt
├── competitor_products.json
└── competitor_products.xlsx
```

Сравнение создаёт:

```text
reports/compare_external_parser_{timestamp}/
├── comparison_summary.txt
├── comparison_result.json
└── comparison_result.xlsx
```
