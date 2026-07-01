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
            self._migrate_seller_products(connection)
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_api_credentials (
                    user_id INTEGER PRIMARY KEY,
                    ozon_client_id TEXT NOT NULL,
                    ozon_api_key TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS seller_products (
                    user_id INTEGER NOT NULL DEFAULT 0,
                    id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    price REAL,
                    stock INTEGER,
                    sku TEXT,
                    product_url TEXT,
                    rating REAL,
                    reviews_count INTEGER,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, id)
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
                    user_id INTEGER NOT NULL DEFAULT 0,
                    mode TEXT NOT NULL,
                    source TEXT NOT NULL,
                    marketplace TEXT NOT NULL,
                    total_products INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS competitor_datasets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_url TEXT,
                    file_path TEXT NOT NULL,
                    original_filename TEXT,
                    products_count INTEGER,
                    analysis_run_id INTEGER,
                    saved INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS parser_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT,
                    processed_links INTEGER,
                    total_links INTEGER,
                    dataset_id INTEGER,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS report_rate_limits (
                    user_id INTEGER NOT NULL,
                    report_type TEXT NOT NULL,
                    last_created_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, report_type),
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                """
            )
            self._ensure_column(connection, "analysis_runs", "user_id", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "parser_jobs", "processed_links", "INTEGER")
            self._ensure_column(connection, "parser_jobs", "total_links", "INTEGER")

    @staticmethod
    def _migrate_seller_products(connection: sqlite3.Connection) -> None:
        existing = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='seller_products'"
        ).fetchone()
        if existing is None:
            return
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(seller_products)")
        }
        if "user_id" in columns:
            return
        connection.executescript(
            """
            ALTER TABLE seller_products RENAME TO seller_products_legacy;
            CREATE TABLE seller_products (
                user_id INTEGER NOT NULL DEFAULT 0,
                id TEXT NOT NULL,
                name TEXT NOT NULL,
                price REAL,
                stock INTEGER,
                sku TEXT,
                product_url TEXT,
                rating REAL,
                reviews_count INTEGER,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(user_id, id)
            );
            INSERT INTO seller_products (
                user_id, id, name, price, stock, sku, product_url,
                rating, reviews_count, updated_at
            )
            SELECT
                0, id, name, price, stock, sku, product_url,
                rating, reviews_count, updated_at
            FROM seller_products_legacy;
            DROP TABLE seller_products_legacy;
            """
        )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        columns = {
            row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create_analysis_run(
        self,
        *,
        mode: str,
        source: str,
        marketplace: str,
        total_products: int,
        status: str,
        result: dict | None = None,
        user_id: int = 0,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO analysis_runs (
                    user_id, mode, source, marketplace, total_products, status,
                    result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
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

    def get_seller_product(
        self, product_id: str, user_id: int = 0
    ) -> SellerProduct | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM seller_products WHERE user_id = ? AND id = ?",
                (user_id, str(product_id)),
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

    def upsert_seller_product(
        self, product: SellerProduct, user_id: int = 0
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO seller_products (
                    user_id, id, name, price, stock, sku, product_url, rating,
                    reviews_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, id) DO UPDATE SET
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
                    user_id,
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
