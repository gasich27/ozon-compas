from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.security import SecretBox
from app.config import Settings, sqlite_path_from_url
from app.models import CompetitorProduct, SellerProduct


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
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
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(seller_products)")}
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
            SELECT 0, id, name, price, stock, sku, product_url,
                rating, reviews_count, updated_at
            FROM seller_products_legacy;
            DROP TABLE seller_products_legacy;
            """
        )

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create_analysis_run(self, *, mode: str, source: str, marketplace: str, total_products: int, status: str, result: dict | None = None, user_id: int = 0) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO analysis_runs (
                    user_id, mode, source, marketplace, total_products, status,
                    result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id, mode, source, marketplace, total_products, status,
                    json.dumps(result, ensure_ascii=False, default=str) if result is not None else None,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def save_competitor_products(self, products, analysis_run_id: int) -> None:
        rows = [
            (analysis_run_id, p.name, p.product_url, p.sku, p.price, p.reviews_count, p.average_rating, p.position, p.collected_at.isoformat())
            for p in products
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

    def get_seller_product(self, product_id: str, user_id: int = 0) -> SellerProduct | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM seller_products WHERE user_id = ? AND id = ?",
                (user_id, str(product_id)),
            ).fetchone()
        if row is None:
            return None
        return SellerProduct(
            id=row["id"], name=row["name"], price=row["price"], stock=row["stock"], sku=row["sku"], product_url=row["product_url"], rating=row["rating"], reviews_count=row["reviews_count"]
        )

    def upsert_seller_product(self, product: SellerProduct, user_id: int = 0) -> None:
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
                (user_id, product.id, product.name, product.price, product.stock, product.sku, product.product_url, product.rating, product.reviews_count, datetime.now(timezone.utc).isoformat()),
            )

    def delete_seller_product(self, product_id: str, user_id: int = 0) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM seller_products WHERE user_id = ? AND id = ?", (user_id, str(product_id)))

    def list_seller_products(self, user_id: int = 0):
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM seller_products WHERE user_id = ? ORDER BY updated_at DESC", (user_id,)).fetchall()
        return [self._row_to_seller_product(row) for row in rows]

    @staticmethod
    def _row_to_seller_product(row) -> SellerProduct:
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


def create_user(database: Database, email: str, password: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with database.connect() as connection:
        cursor = connection.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email.strip(), password, now),
        )
        return int(cursor.lastrowid)


def get_user(database: Database, user_id: int | None) -> dict | None:
    if user_id is None:
        return None
    with database.connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def authenticate_user(database: Database, email: str, password: str) -> dict | None:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE email = ?",
            (email.strip(),),
        ).fetchone()
    if row is None or row["password_hash"] != password:
        return None
    return dict(row)


def save_api_credentials(
    database: Database, secret_box: SecretBox, user_id: int, client_id: str, api_key: str
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    client_id_encrypted = secret_box.encrypt(client_id.strip())
    api_key_encrypted = secret_box.encrypt(api_key.strip())
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO user_api_credentials (
                user_id, ozon_client_id, ozon_api_key, updated_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                ozon_client_id = excluded.ozon_client_id,
                ozon_api_key = excluded.ozon_api_key,
                updated_at = excluded.updated_at
            """,
            (user_id, client_id_encrypted, api_key_encrypted, now),
        )


def get_api_credentials(
    database: Database, secret_box: SecretBox, user_id: int
) -> tuple[str, str] | None:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM user_api_credentials WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    return (
        secret_box.decrypt(row["ozon_client_id"]),
        secret_box.decrypt(row["ozon_api_key"]),
    )


def create_dataset(
    database: Database,
    *,
    user_id: int,
    name: str,
    source: str,
    file_path: Path,
    original_filename: str | None = None,
    source_url: str | None = None,
    products_count: int | None = None,
    analysis_run_id: int | None = None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with database.connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO competitor_datasets (
                user_id, name, source, source_url, file_path, original_filename,
                products_count, analysis_run_id, saved, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                user_id,
                name,
                source,
                source_url,
                str(file_path),
                original_filename,
                products_count,
                analysis_run_id,
                now,
            ),
        )
        return int(cursor.lastrowid)


def get_dataset(database: Database, user_id: int, dataset_id: int) -> dict | None:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM competitor_datasets WHERE id = ? AND user_id = ?",
            (dataset_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def list_datasets(database: Database, user_id: int) -> list[dict]:
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM competitor_datasets WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def update_dataset_analysis(
    database: Database, dataset_id: int, analysis_run_id: int
) -> None:
    with database.connect() as connection:
        connection.execute(
            "UPDATE competitor_datasets SET analysis_run_id = ? WHERE id = ?",
            (analysis_run_id, dataset_id),
        )


def update_dataset_after_edit(
    database: Database, dataset_id: int, file_path: Path, products_count: int
) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE competitor_datasets
            SET file_path = ?, products_count = ?
            WHERE id = ?
            """,
            (str(file_path), products_count, dataset_id),
        )


def set_dataset_saved(
    database: Database, user_id: int, dataset_id: int, saved: bool
) -> None:
    with database.connect() as connection:
        connection.execute(
            "UPDATE competitor_datasets SET saved = ? WHERE id = ? AND user_id = ?",
            (int(saved), dataset_id, user_id),
        )


def create_parser_job(database: Database, user_id: int, url: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with database.connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO parser_jobs (
                user_id, url, status, message, processed_links, total_links,
                created_at, updated_at
            ) VALUES (?, ?, 'queued', ?, NULL, NULL, ?, ?)
            """,
            (user_id, url, "Ожидает запуска", now, now),
        )
        return int(cursor.lastrowid)


def update_parser_job(
    database: Database,
    job_id: int,
    *,
    status: str,
    message: str,
    processed_links: int | None = None,
    total_links: int | None = None,
    dataset_id: int | None = None,
    error: str | None = None,
) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE parser_jobs SET
                status = ?, message = ?,
                processed_links = COALESCE(?, processed_links),
                total_links = COALESCE(?, total_links),
                dataset_id = COALESCE(?, dataset_id),
                error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                message,
                processed_links,
                total_links,
                dataset_id,
                error,
                datetime.now(timezone.utc).isoformat(),
                job_id,
            ),
        )


def get_parser_job(database: Database, user_id: int, job_id: int) -> dict | None:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM parser_jobs WHERE id = ? AND user_id = ?",
            (job_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def claim_report_creation(
    database: Database,
    user_id: int,
    report_type: str,
    cooldown_seconds: int = 60,
) -> int:
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(seconds=cooldown_seconds)
    with database.connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO report_rate_limits (
                user_id, report_type, last_created_at
            ) VALUES (?, ?, ?)
            ON CONFLICT(user_id, report_type) DO UPDATE SET
                last_created_at = excluded.last_created_at
            WHERE report_rate_limits.last_created_at <= ?
            """,
            (user_id, report_type, now.isoformat(), threshold.isoformat()),
        )
        if cursor.rowcount:
            return 0
        row = connection.execute(
            "SELECT last_created_at FROM report_rate_limits WHERE user_id = ? AND report_type = ?",
            (user_id, report_type),
        ).fetchone()
    if row is None:
        return cooldown_seconds
    last_created = datetime.fromisoformat(row["last_created_at"])
    remaining = cooldown_seconds - int((now - last_created).total_seconds())
    return max(1, remaining)
