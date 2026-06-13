from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.models import CompetitorProduct, SellerProduct


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        # Works on restricted/networked Windows workspaces where SQLite cannot
        # atomically manage DELETE/WAL sidecar files.
        connection.execute("PRAGMA journal_mode=MEMORY")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS seller_products (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    price REAL,
                    stock INTEGER,
                    sku TEXT,
                    product_url TEXT,
                    rating REAL,
                    reviews_count INTEGER,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS competitor_products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_run_id INTEGER,
                    name TEXT NOT NULL,
                    product_url TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    price REAL,
                    reviews_count INTEGER,
                    average_rating REAL,
                    position INTEGER NOT NULL,
                    collected_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS analysis_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mode TEXT NOT NULL,
                    source TEXT NOT NULL,
                    marketplace TEXT NOT NULL,
                    total_products INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

    def create_analysis_run(
        self,
        *,
        mode: str,
        source: str,
        marketplace: str,
        total_products: int,
        status: str,
        result: dict | None = None,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO analysis_runs (
                    mode, source, marketplace, total_products, status,
                    result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mode,
                    source,
                    marketplace,
                    total_products,
                    status,
                    json.dumps(result, ensure_ascii=False, default=str)
                    if result is not None
                    else None,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def save_competitor_products(
        self, products: Iterable[CompetitorProduct], analysis_run_id: int
    ) -> None:
        rows = [
            (
                analysis_run_id,
                product.name,
                product.product_url,
                product.sku,
                product.price,
                product.reviews_count,
                product.average_rating,
                product.position,
                product.collected_at.isoformat(),
            )
            for product in products
        ]
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO competitor_products (
                    analysis_run_id, name, product_url, sku, price,
                    reviews_count, average_rating, position, collected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def get_seller_product(self, product_id: str) -> SellerProduct | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM seller_products WHERE id = ?", (str(product_id),)
            ).fetchone()
        if row is None:
            return None
        return SellerProduct(
            id=row["id"],
            name=row["name"],
            price=row["price"],
            stock=row["stock"],
            sku=row["sku"],
            product_url=row["product_url"],
            rating=row["rating"],
            reviews_count=row["reviews_count"],
        )

    def upsert_seller_product(self, product: SellerProduct) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO seller_products (
                    id, name, price, stock, sku, product_url, rating,
                    reviews_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    price=excluded.price,
                    stock=excluded.stock,
                    sku=excluded.sku,
                    product_url=excluded.product_url,
                    rating=excluded.rating,
                    reviews_count=excluded.reviews_count,
                    updated_at=excluded.updated_at
                """,
                (
                    product.id,
                    product.name,
                    product.price,
                    product.stock,
                    product.sku,
                    product.product_url,
                    product.rating,
                    product.reviews_count,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
