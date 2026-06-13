from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def sqlite_path_from_url(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("Поддерживается только DATABASE_URL в формате sqlite:///path/to/database.db")
    return Path(database_url[len(prefix) :])


@dataclass(frozen=True)
class Settings:
    database_url: str
    reports_dir: Path
    log_level: str
    ozon_client_id: str
    ozon_api_key: str
    ozon_api_base_url: str
    ozon_product_list_path: str
    ozon_product_info_path: str
    ozon_product_stock_path: str
    ozon_product_price_path: str
    external_parser_path: Path | None
    external_parser_output_dir: Path | None
    external_parser_timeout: int

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        parser_path = os.getenv("EXTERNAL_PARSER_PATH", "").strip()
        output_dir = os.getenv("EXTERNAL_PARSER_OUTPUT_DIR", "").strip()
        return cls(
            database_url=os.getenv(
                "DATABASE_URL", "sqlite:///data/ozon_seller_radar.db"
            ),
            reports_dir=Path(os.getenv("REPORTS_DIR", "reports")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            ozon_client_id=os.getenv("OZON_CLIENT_ID", "").strip(),
            ozon_api_key=os.getenv("OZON_API_KEY", "").strip(),
            ozon_api_base_url=os.getenv(
                "OZON_API_BASE_URL", "https://api-seller.ozon.ru"
            ).rstrip("/"),
            ozon_product_list_path=os.getenv(
                "OZON_PRODUCT_LIST_PATH", "/v2/product/list"
            ),
            ozon_product_info_path=os.getenv(
                "OZON_PRODUCT_INFO_PATH", "/v2/product/info/list"
            ),
            ozon_product_stock_path=os.getenv(
                "OZON_PRODUCT_STOCK_PATH", "/v1/product/info/stocks"
            ),
            ozon_product_price_path=os.getenv(
                "OZON_PRODUCT_PRICE_PATH", "/v1/product/info/prices"
            ),
            external_parser_path=Path(parser_path) if parser_path else None,
            external_parser_output_dir=Path(output_dir) if output_dir else None,
            external_parser_timeout=int(os.getenv("EXTERNAL_PARSER_TIMEOUT", "900")),
        )
