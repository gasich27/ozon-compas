from __future__ import annotations

from pathlib import Path

from app.analytics.seller_analyzer import analyze_seller_products
from app.database import Database
from app.models import SellerProduct
from app.reports.generator import create_seller_report
from app.sources.seller_api.client import OzonSellerApiClient


def build_seller_client_from_settings(settings) -> OzonSellerApiClient:
    return OzonSellerApiClient(
        client_id=settings.ozon_client_id,
        api_key=settings.ozon_api_key,
        base_url=settings.ozon_api_base_url,
        product_list_path=settings.ozon_product_list_path,
        product_info_path=settings.ozon_product_info_path,
        product_stock_path=settings.ozon_product_stock_path,
        product_price_path=settings.ozon_product_price_path,
    )


def sync_seller_products(
    *,
    database: Database,
    client: OzonSellerApiClient,
    limit: int | None = None,
    user_id: int = 0,
) -> list[SellerProduct]:
    products = client.list_products(limit=limit)
    for product in products:
        database.upsert_seller_product(product, user_id=user_id)
    return products


def analyze_seller_products_in_db(
    *,
    database: Database,
    reports_dir: Path,
    user_id: int = 0,
) -> tuple[list[SellerProduct], dict, Path]:
    products = _load_all_seller_products(database, user_id=user_id)
    analysis = analyze_seller_products(products)
    report_dir = create_seller_report(reports_dir, products, analysis)
    return products, analysis, report_dir


def _load_all_seller_products(
    database: Database, user_id: int = 0
) -> list[SellerProduct]:
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM seller_products WHERE user_id = ? ORDER BY name",
            (user_id,),
        ).fetchall()
    return [
        SellerProduct(
            id=row["id"],
            name=row["name"],
            price=row["price"],
            stock=row["stock"],
            sku=row["sku"],
            product_url=row["product_url"],
            rating=row["rating"],
            reviews_count=row["reviews_count"],
        )
        for row in rows
    ]
