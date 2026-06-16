# Ozon Seller Radar

Ozon Seller Radar is a local CLI and web app for Ozon sellers. It helps with three workflows:

1. Seller catalog sync through Ozon Seller API.
2. Market parsing through the existing external Ozon parser.
3. Comparison of a seller product against the market.

The project now includes a simple web interface with a custom visual layer, user accounts, saved datasets, reports, and CSV download/edit support.

## What It Does

- Stores seller data in SQLite.
- Keeps each user's API credentials, products, uploaded CSVs, parser results, and reports isolated.
- Runs the external parser as a subprocess without changing its internals.
- Reads parser CSV output and sends it into analytics and comparison.
- Generates TXT, JSON, and XLSX reports.

## Web Interface

The web interface is the easiest way to use the project.

Start it with:

```bash
python -m pip install -r requirements.txt
python web.py
```

Then open:

```text
http://127.0.0.1:8000
```

Main pages:

- `Главная` - overview and entry points.
- `Мои товары` - Seller API credentials, catalog sync, seller analytics, seller reports.
- `Парсинг маркета` - запуск внешнего парсера или загрузка готового CSV.
- `Сравнение` - compare a seller product with market data.

Users can register with email and password. After login they can:

- save `OZON_CLIENT_ID` and `OZON_API_KEY`;
- sync seller products;
- launch market parsing;
- upload ready CSV files;
- download parsed datasets;
- delete rows from a dataset and save the edited CSV;
- create and download reports.

The interface has a simple custom design with glass-like cards, a moving background video, and compact navigation.

## Seller API Mode

Seller API mode syncs products into SQLite and builds seller reports.

Commands:

```bash
python main.py seller check-api
python main.py seller sync
python main.py seller list
python main.py seller show --seller-product-id 123456
python main.py seller analyze
```

Seller API credentials are stored per user in the web app and encrypted before being written to SQLite.

## Market Parsing Mode

The external parser already exists in `ozon-seller-parser/`. Ozon Seller Radar does not rewrite it. It launches it as a subprocess, waits for the CSV, reads the result, and stores the parsed data.

Web flow:

1. Open `Парсинг маркета`.
2. Paste an Ozon URL.
3. Start parsing.
4. Wait for the progress screen.
5. Open the resulting dataset, download it, analyze it, or save it for later.

CLI flow:

```bash
python main.py competitors parse --url "https://www.ozon.ru/search/?text=рюкзак+мужской" --yes
```

You can also analyze an already prepared CSV:

```bash
python main.py competitors analyze-csv --input data/parser_output/products.csv
```

## Comparison Mode

Compare a seller product with market data:

```bash
python main.py compare product --seller-product-id 123456 --competitors-csv data/parser_output/products.csv
```

Or launch the parser first:

```bash
python main.py compare product --seller-product-id 123456 --competitors-url "https://www.ozon.ru/search/?text=рюкзак+мужской" --yes
```

If the seller product is not in SQLite yet, sync seller data first.

## External Parser Notes

The external parser lives in `ozon-seller-parser/`.

- Entry point: `run.py`.
- Actual workflow: `python run.py all`.
- The parser reads its URL from `config.json` through `seller_url`.
- The parser can open Chrome.
- Headless mode is not used.
- The output CSV is written to the parser output directory and then read by this project.
- CSV columns:
  - `Название`
  - `Ссылка на товар`
  - `Артикул`
  - `Цена`
  - `Количество отзывов`
  - `Средний отзыв`

## Reports

Parser analytics create:

```text
reports/competitors_external_parser_{timestamp}/
├── competitors_summary.txt
├── competitor_products.json
└── competitor_products.xlsx
```

Comparison creates:

```text
reports/compare_external_parser_{timestamp}/
├── comparison_summary.txt
├── comparison_result.json
└── comparison_result.xlsx
```

Seller reports create:

```text
reports/user_<id>/seller_api_{timestamp}/
├── seller_summary.txt
├── seller_products.json
└── seller_products.xlsx
```

## Configuration

Copy `.env.example` to `.env` for CLI use.

Important variables:

```dotenv
DATABASE_URL=sqlite:///data/ozon_seller_radar.db
REPORTS_DIR=reports
LOG_LEVEL=INFO
OZON_CLIENT_ID=
OZON_API_KEY=
EXTERNAL_PARSER_PATH=ozon-seller-parser
EXTERNAL_PARSER_OUTPUT_DIR=data/parser_output
EXTERNAL_PARSER_TIMEOUT=900
```

The web app keeps user secrets encrypted in SQLite with a local key in `data/.secret.key`.

## Development

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run tests:

```bash
pytest
```

## Notes

- The project keeps the external parser unchanged.
- Runtime data such as SQLite, parser output, user uploads, and reports are ignored by Git.
- The UI is intentionally simple and compact, with glass-style panels and a custom animated background.
