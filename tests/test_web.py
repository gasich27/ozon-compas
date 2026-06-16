from pathlib import Path
from io import BytesIO

import pytest

flask = pytest.importorskip("flask")

from app.config import Settings
from app.database import Database
from app.models import SellerProduct
from app.web import create_app
from app.web import ACTIVE_JOB_EVENTS, ACTIVE_JOB_EVENTS_LOCK
from app.web.store import create_parser_job
import threading


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'web.db'}",
        reports_dir=tmp_path / "reports",
        log_level="INFO",
        ozon_client_id="",
        ozon_api_key="",
        ozon_api_base_url="https://api-seller.ozon.ru",
        ozon_product_list_path="/v2/product/list",
        ozon_product_info_path="/v2/product/info/list",
        ozon_product_stock_path="/v1/product/info/stocks",
        ozon_product_price_path="/v1/product/info/prices",
        external_parser_path=tmp_path / "parser",
        external_parser_output_dir=tmp_path / "output",
        external_parser_timeout=30,
    )


def register(client, email: str = "seller@example.com"):
    return client.post(
        "/register",
        data={"email": email, "password": "strong-password"},
        follow_redirects=True,
    )


def test_dashboard_is_public(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(make_settings(tmp_path))
    app.config["TESTING"] = True
    response = app.test_client().get("/")
    assert response.status_code == 200
    assert "Ранний доступ".encode("utf-8") in response.data


def test_actions_require_login(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(make_settings(tmp_path))
    app.config["TESTING"] = True
    response = app.test_client().post(
        "/competitors/parse",
        data={"url": "https://www.ozon.ru/search/?text=test"},
    )
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_parser_job_can_be_cancelled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    settings = make_settings(tmp_path)
    app = create_app(settings)
    app.config["TESTING"] = True
    client = app.test_client()
    register(client)
    database = Database(tmp_path / "web.db")
    with database.connect() as connection:
        user_id = connection.execute(
            "SELECT id FROM users WHERE email = ?", ("seller@example.com",)
        ).fetchone()[0]
    job_id = create_parser_job(
        database, user_id, "https://www.ozon.ru/search/?text=test"
    )
    event = threading.Event()
    with ACTIVE_JOB_EVENTS_LOCK:
        ACTIVE_JOB_EVENTS[job_id] = event

    response = client.post(f"/competitors/jobs/{job_id}/cancel")

    assert response.status_code == 200
    assert event.is_set()
    assert response.get_json()["status"] == "cancelling"
    with ACTIVE_JOB_EVENTS_LOCK:
        ACTIVE_JOB_EVENTS.pop(job_id, None)


def test_registration_opens_dashboard(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(make_settings(tmp_path))
    app.config["TESTING"] = True
    response = register(app.test_client())
    assert response.status_code == 200
    assert "Ozon Radar".encode() in response.data


def test_seller_products_are_user_scoped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    settings = make_settings(tmp_path)
    app = create_app(settings)
    app.config["TESTING"] = True
    client = app.test_client()
    register(client)

    database = Database(tmp_path / "web.db")
    with database.connect() as connection:
        user_id = connection.execute(
            "SELECT id FROM users WHERE email = ?", ("seller@example.com",)
        ).fetchone()[0]
    database.upsert_seller_product(
        SellerProduct(id="123", name="Тестовый товар", price=1000, stock=5),
        user_id=user_id,
    )
    database.upsert_seller_product(
        SellerProduct(id="456", name="Чужой товар", price=2000, stock=3),
        user_id=user_id + 1,
    )

    response = client.get("/seller")
    assert response.status_code == 200
    assert "Тестовый товар".encode("utf-8") in response.data
    assert "Чужой товар".encode("utf-8") not in response.data


def test_user_can_save_api_credentials(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    settings = make_settings(tmp_path)
    app = create_app(settings)
    app.config["TESTING"] = True
    client = app.test_client()
    register(client)

    response = client.post(
        "/seller/credentials",
        data={"client_id": "client-1", "api_key": "secret-key"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "ключи сохранены".encode("utf-8") in response.data

    with Database(tmp_path / "web.db").connect() as connection:
        row = connection.execute(
            "SELECT ozon_api_key FROM user_api_credentials"
        ).fetchone()
    assert row["ozon_api_key"] != "secret-key"


def test_report_creation_is_rate_limited(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    settings = make_settings(tmp_path)
    app = create_app(settings)
    app.config["TESTING"] = True
    client = app.test_client()
    register(client)

    first = client.post("/seller/analyze", follow_redirects=True)
    second = client.post("/seller/analyze", follow_redirects=True)

    assert first.status_code == 200
    assert second.status_code == 200
    assert "Повторите через".encode("utf-8") in second.data


def test_seller_report_can_be_downloaded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    settings = make_settings(tmp_path)
    app = create_app(settings)
    app.config["TESTING"] = True
    client = app.test_client()
    register(client)

    client.post("/seller/analyze", follow_redirects=True)
    response = client.get("/seller/report/txt")

    assert response.status_code == 200
    assert response.headers["Content-Disposition"].startswith("attachment")
    assert "Аналитика товаров селлера Ozon".encode("utf-8") in response.data


def test_uploaded_dataset_is_saved_and_downloadable(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(make_settings(tmp_path))
    app.config["TESTING"] = True
    client = app.test_client()
    register(client)
    csv_bytes = (
        "Название;Ссылка на товар;Артикул;Цена;"
        "Количество отзывов;Средний отзыв\n"
        "Товар;https://www.ozon.ru/product/1;1;1000;10;4.8\n"
    ).encode("utf-8")

    response = client.post(
        "/competitors/upload",
        data={"csv_file": (BytesIO(csv_bytes), "товары_маркета.csv")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    assert "/competitors/datasets/" in response.headers["Location"]

    detail = client.get(response.headers["Location"])
    assert detail.status_code == 200
    assert "Товар".encode("utf-8") in detail.data

    dataset_id = int(response.headers["Location"].rstrip("/").split("/")[-1])
    download = client.get(f"/competitors/datasets/{dataset_id}/download")
    assert download.status_code == 200
    assert "attachment" in download.headers["Content-Disposition"]
    assert download.data.startswith(b"\xef\xbb\xbf")
    assert "Товар".encode("utf-8") in download.data
    assert b'\"=\"\"4.8\"\"\"' in download.data
    assert b"1000" in download.data


def test_dataset_rows_can_be_deleted_and_saved(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(make_settings(tmp_path))
    app.config["TESTING"] = True
    client = app.test_client()
    register(client)
    csv_bytes = (
        "Название;Ссылка на товар;Артикул;Цена;"
        "Количество отзывов;Средний отзыв\n"
        "Первый;https://www.ozon.ru/product/1;1;1000;10;4.8\n"
        "Второй;https://www.ozon.ru/product/2;2;2000;20;4.7\n"
    ).encode("utf-8")

    response = client.post(
        "/competitors/upload",
        data={"csv_file": (BytesIO(csv_bytes), "market.csv")},
        content_type="multipart/form-data",
    )
    dataset_id = int(response.headers["Location"].rstrip("/").split("/")[-1])

    delete = client.post(
        f"/competitors/datasets/{dataset_id}/rows/delete",
        data={"delete_positions": "1"},
        follow_redirects=True,
    )
    download = client.get(f"/competitors/datasets/{dataset_id}/download")

    assert delete.status_code == 200
    assert "Удалено строк: 1".encode("utf-8") in delete.data
    assert "Первый".encode("utf-8") not in download.data
    assert "Второй".encode("utf-8") in download.data


def test_user_cannot_open_another_users_dataset(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    app = create_app(make_settings(tmp_path))
    app.config["TESTING"] = True
    first = app.test_client()
    register(first, "first@example.com")
    csv_bytes = (
        "Название;Ссылка на товар;Артикул;Цена;"
        "Количество отзывов;Средний отзыв\n"
        "Скрытый;https://www.ozon.ru/product/1;1;1000;10;4.8\n"
    ).encode("utf-8")
    response = first.post(
        "/competitors/upload",
        data={"csv_file": (BytesIO(csv_bytes), "private.csv")},
        content_type="multipart/form-data",
    )
    dataset_id = int(response.headers["Location"].rstrip("/").split("/")[-1])

    second = app.test_client()
    register(second, "second@example.com")
    denied = second.get(f"/competitors/datasets/{dataset_id}")
    assert denied.status_code == 400
    assert "Набор данных не найден".encode("utf-8") in denied.data
