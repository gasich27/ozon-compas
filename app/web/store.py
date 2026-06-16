from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

from app.database import Database
from app.security import SecretBox


def create_user(database: Database, email: str, password: str) -> int:
    normalized = email.strip().lower()
    if "@" not in normalized:
        raise ValueError("Введите корректный email.")
    if len(password) < 8:
        raise ValueError("Пароль должен содержать минимум 8 символов.")
    try:
        with database.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                (
                    normalized,
                    generate_password_hash(password),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return int(cursor.lastrowid)
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise ValueError("Пользователь с таким email уже зарегистрирован.") from exc
        raise


def authenticate_user(database: Database, email: str, password: str) -> dict | None:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE",
            (email.strip(),),
        ).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password):
        return None
    return dict(row)


def get_user(database: Database, user_id: int) -> dict | None:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT id, email, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def save_api_credentials(
    database: Database,
    secret_box: SecretBox,
    user_id: int,
    client_id: str,
    api_key: str,
) -> None:
    if not client_id.strip() or not api_key.strip():
        raise ValueError("Client ID и API Key обязательны.")
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO user_api_credentials (
                user_id, ozon_client_id, ozon_api_key, updated_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                ozon_client_id=excluded.ozon_client_id,
                ozon_api_key=excluded.ozon_api_key,
                updated_at=excluded.updated_at
            """,
            (
                user_id,
                secret_box.encrypt(client_id.strip()),
                secret_box.encrypt(api_key.strip()),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def get_api_credentials(
    database: Database, secret_box: SecretBox, user_id: int
) -> tuple[str, str] | None:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT ozon_client_id, ozon_api_key FROM user_api_credentials "
            "WHERE user_id = ?",
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
    source_url: str | None = None,
    original_filename: str | None = None,
    products_count: int | None = None,
    saved: bool = False,
) -> int:
    with database.connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO competitor_datasets (
                user_id, name, source, source_url, file_path,
                original_filename, products_count, saved, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                name,
                source,
                source_url,
                str(file_path),
                original_filename,
                products_count,
                int(saved),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return int(cursor.lastrowid)


def list_datasets(database: Database, user_id: int) -> list[dict]:
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM competitor_datasets WHERE user_id = ? "
            "ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_dataset(database: Database, user_id: int, dataset_id: int) -> dict | None:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM competitor_datasets WHERE id = ? AND user_id = ?",
            (dataset_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def update_dataset_analysis(
    database: Database,
    user_id: int,
    dataset_id: int,
    analysis_run_id: int,
    products_count: int,
) -> None:
    with database.connect() as connection:
        connection.execute(
            "UPDATE competitor_datasets SET analysis_run_id = ?, products_count = ? "
            "WHERE id = ? AND user_id = ?",
            (analysis_run_id, products_count, dataset_id, user_id),
        )


def update_dataset_after_edit(
    database: Database,
    user_id: int,
    dataset_id: int,
    products_count: int,
) -> None:
    with database.connect() as connection:
        connection.execute(
            "UPDATE competitor_datasets SET products_count = ?, analysis_run_id = NULL "
            "WHERE id = ? AND user_id = ?",
            (products_count, dataset_id, user_id),
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
                user_id, url, status, message, created_at, updated_at
            ) VALUES (?, ?, 'queued', ?, ?, ?)
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
    dataset_id: int | None = None,
    error: str | None = None,
) -> None:
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE parser_jobs SET
                status = ?, message = ?, dataset_id = COALESCE(?, dataset_id),
                error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                message,
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
            (
                user_id,
                report_type,
                now.isoformat(),
                threshold.isoformat(),
            ),
        )
        if cursor.rowcount:
            return 0
        row = connection.execute(
            "SELECT last_created_at FROM report_rate_limits "
            "WHERE user_id = ? AND report_type = ?",
            (user_id, report_type),
        ).fetchone()
    if row is None:
        return cooldown_seconds
    last_created = datetime.fromisoformat(row["last_created_at"])
    remaining = cooldown_seconds - int((now - last_created).total_seconds())
    return max(1, remaining)
