from __future__ import annotations

import logging
import shutil
import sqlite3
import threading
import uuid
import csv
from functools import wraps
from io import BytesIO
from io import StringIO
from pathlib import Path

from flask import (
    Flask,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.exceptions import HTTPException, NotFound
from werkzeug.utils import secure_filename

from app.cli.common import parser_paths, query_name_from_url, validate_ozon_url
from app.config import Settings, sqlite_path_from_url
from app.database import Database
from app.security import SecretBox
from app.services.comparison_service import compare_with_csv
from app.services.competitor_service import analyze_competitor_csv
from app.services.seller_service import (
    analyze_seller_products_in_db,
    sync_seller_products,
)
from app.sources.competitor_parser.csv_reader import (
    CompetitorCsvError,
    CompetitorCsvReader,
)
from app.sources.competitor_parser.exceptions import ExternalParserError
from app.sources.competitor_parser.exceptions import ExternalParserCancelledError
from app.sources.competitor_parser.external_parser_runner import ExternalParserRunner
from app.sources.seller_api.client import OzonSellerApiClient
from app.sources.seller_api.exceptions import OzonSellerApiError
from app.web.store import (
    authenticate_user,
    claim_report_creation,
    create_dataset,
    create_parser_job,
    create_user,
    get_api_credentials,
    get_dataset,
    get_parser_job,
    get_user,
    list_datasets,
    save_api_credentials,
    set_dataset_saved,
    update_dataset_after_edit,
    update_dataset_analysis,
    update_parser_job,
)


ALLOWED_UPLOADS = {".csv"}
PARSER_LOCK = threading.Lock()
ACTIVE_JOB_EVENTS: dict[int, threading.Event] = {}
ACTIVE_JOB_EVENTS_LOCK = threading.Lock()


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or Settings.from_env()
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = _web_secret()
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
    app.extensions["radar_settings"] = settings
    app.extensions["secret_box"] = SecretBox()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    @app.before_request
    def load_user():
        user_id = session.get("user_id")
        g.user = get_user(_database(settings), user_id) if user_id else None

    @app.context_processor
    def inject_globals():
        return {"current_path": request.path, "current_user": g.user}

    @app.template_filter("short_text")
    def short_text(value: object, length: int = 20) -> str:
        text = "" if value is None else str(value)
        return text if len(text) <= length else text[:length].rstrip() + "..."

    @app.get("/register")
    def register():
        if g.user:
            return redirect(url_for("dashboard"))
        return render_template("register.html")

    @app.post("/register")
    def register_submit():
        user_id = create_user(
            _database(settings),
            request.form.get("email", ""),
            request.form.get("password", ""),
        )
        session.clear()
        session["user_id"] = user_id
        return redirect(url_for("dashboard"))

    @app.get("/login")
    def login():
        if g.user:
            return redirect(url_for("dashboard"))
        return render_template("login.html")

    @app.post("/login")
    def login_submit():
        user = authenticate_user(
            _database(settings),
            request.form.get("email", ""),
            request.form.get("password", ""),
        )
        if user is None:
            flash("Неверная почта или пароль.", "error")
            return redirect(url_for("login"))
        session.clear()
        session["user_id"] = user["id"]
        next_url = request.form.get("next", "")
        return redirect(next_url if next_url.startswith("/") else url_for("dashboard"))

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    def dashboard():
        database = _database(settings)
        return render_template(
            "dashboard.html",
            stats=_dashboard_stats(database, g.user["id"]) if g.user else _empty_stats(),
        )

    @app.get("/seller")
    def seller_products():
        database = _database(settings)
        credentials = (
            get_api_credentials(database, app.extensions["secret_box"], g.user["id"])
            if g.user
            else None
        )
        return render_template(
            "seller.html",
            products=_seller_rows(database, g.user["id"]) if g.user else [],
            api_configured=credentials is not None,
            client_id=credentials[0] if credentials else "",
            seller_report=_latest_seller_report(settings, g.user["id"])
            if g.user
            else None,
        )

    @app.post("/seller/credentials")
    @login_required
    def seller_credentials():
        save_api_credentials(
            _database(settings),
            app.extensions["secret_box"],
            g.user["id"],
            request.form.get("client_id", ""),
            request.form.get("api_key", ""),
        )
        flash("Seller API-ключи сохранены.", "success")
        return redirect(url_for("seller_products"))

    @app.post("/seller/check-api")
    @login_required
    def seller_check_api():
        client = _seller_client(settings, app, g.user["id"])
        ok, message = client.check_credentials()
        flash(message, "success" if ok else "error")
        return redirect(url_for("seller_products"))

    @app.post("/seller/sync")
    @login_required
    def seller_sync():
        database = _database(settings)
        products = sync_seller_products(
            database=database,
            client=_seller_client(settings, app, g.user["id"]),
            limit=_optional_int(request.form.get("limit")),
            user_id=g.user["id"],
        )
        database.create_analysis_run(
            mode="seller",
            source="ozon_api",
            marketplace="ozon",
            total_products=len(products),
            status="success",
            user_id=g.user["id"],
        )
        flash(f"Синхронизировано товаров: {len(products)}", "success")
        return redirect(url_for("seller_products"))

    @app.get("/seller/<product_id>")
    @login_required
    def seller_product(product_id: str):
        product = _database(settings).get_seller_product(
            product_id, user_id=g.user["id"]
        )
        if product is None:
            raise LookupError("Товар селлера не найден.")
        return render_template("seller_product.html", product=product)

    @app.post("/seller/analyze")
    @login_required
    def seller_analyze():
        remaining = claim_report_creation(
            _database(settings), g.user["id"], "seller_catalog"
        )
        if remaining:
            flash(
                f"Отчёт уже создавался недавно. Повторите через {remaining} сек.",
                "error",
            )
            return redirect(url_for("seller_products"))
        products, _, report_dir = analyze_seller_products_in_db(
            database=_database(settings),
            reports_dir=_user_reports_dir(settings, g.user["id"]),
            user_id=g.user["id"],
        )
        flash(f"Анализ готов: {len(products)} товаров. Отчёт: {report_dir}", "success")
        return redirect(url_for("seller_products"))

    @app.get("/seller/report/<format_name>")
    @login_required
    def seller_report_download(format_name: str):
        files = {
            "txt": "seller_summary.txt",
            "json": "seller_products.json",
            "xlsx": "seller_products.xlsx",
        }
        filename = files.get(format_name)
        if filename is None:
            raise LookupError("Формат отчёта не найден.")
        report = _latest_seller_report(settings, g.user["id"])
        if report is None:
            raise LookupError("Отчёт ещё не создан.")
        path = report["dir"] / filename
        if not path.exists():
            raise LookupError("Файл отчёта не найден.")
        return send_file(path.resolve(), as_attachment=True, download_name=filename)

    @app.get("/competitors")
    def competitors():
        return render_template(
            "competitors.html",
            datasets=list_datasets(_database(settings), g.user["id"]) if g.user else [],
        )

    @app.post("/competitors/parse")
    @login_required
    def competitors_parse():
        url = validate_ozon_url(request.form.get("url", "").strip())
        database = _database(settings)
        job_id = create_parser_job(database, g.user["id"], url)
        cancel_event = threading.Event()
        with ACTIVE_JOB_EVENTS_LOCK:
            ACTIVE_JOB_EVENTS[job_id] = cancel_event
        thread = threading.Thread(
            target=_run_parser_job,
            args=(
                settings,
                database.path,
                g.user["id"],
                job_id,
                url,
                _optional_int(request.form.get("timeout"))
                or settings.external_parser_timeout,
                cancel_event,
            ),
            daemon=True,
        )
        thread.start()
        return redirect(url_for("parser_job", job_id=job_id))

    @app.get("/competitors/jobs/<int:job_id>")
    @login_required
    def parser_job(job_id: int):
        job = _owned_job(settings, g.user["id"], job_id)
        return render_template("parser_job.html", job=job)

    @app.get("/api/competitors/jobs/<int:job_id>")
    @login_required
    def parser_job_status(job_id: int):
        job = _owned_job(settings, g.user["id"], job_id)
        return jsonify(
            {
                "id": job["id"],
                "status": job["status"],
                "message": job["message"],
                "error": job["error"],
                "processed_links": job.get("processed_links"),
                "total_links": job.get("total_links"),
                "result_url": url_for(
                    "dataset_detail", dataset_id=job["dataset_id"]
                )
                if job["dataset_id"]
                else None,
            }
        )

    @app.post("/competitors/jobs/<int:job_id>/cancel")
    @login_required
    def parser_job_cancel(job_id: int):
        job = _owned_job(settings, g.user["id"], job_id)
        if job["status"] in {"success", "error", "cancelled"}:
            return jsonify({"status": job["status"]})
        with ACTIVE_JOB_EVENTS_LOCK:
            cancel_event = ACTIVE_JOB_EVENTS.get(job_id)
        if cancel_event is not None:
            cancel_event.set()
        update_parser_job(
            _database(settings),
            job_id,
            status="cancelling",
            message="Отменяем парсинг",
        )
        return jsonify({"status": "cancelling"})

    @app.post("/competitors/upload")
    @login_required
    def competitors_upload():
        csv_path, original_name = _save_upload(
            request.files.get("csv_file"), g.user["id"]
        )
        products = CompetitorCsvReader().load(csv_path)
        dataset_id = create_dataset(
            _database(settings),
            user_id=g.user["id"],
            name=Path(original_name).stem,
            source="upload",
            file_path=csv_path,
            original_filename=original_name,
            products_count=len(products),
        )
        return redirect(url_for("dataset_detail", dataset_id=dataset_id))

    @app.get("/competitors/datasets/<int:dataset_id>")
    @login_required
    def dataset_detail(dataset_id: int):
        dataset = _owned_dataset(settings, g.user["id"], dataset_id)
        products = CompetitorCsvReader().load(dataset["file_path"], limit=100)
        analysis = _analysis_result(
            _database(settings), g.user["id"], dataset["analysis_run_id"]
        )
        return render_template(
            "dataset_detail.html",
            dataset=dataset,
            products=products,
            analysis=analysis,
        )

    @app.get("/competitors/datasets/<int:dataset_id>/download")
    @login_required
    def dataset_download(dataset_id: int):
        dataset = _owned_dataset(settings, g.user["id"], dataset_id)
        csv_path = Path(dataset["file_path"])
        download_name = dataset["original_filename"] or f"competitors_{dataset_id}.csv"
        return _csv_download_response(csv_path, download_name)

    @app.post("/competitors/datasets/<int:dataset_id>/rows/delete")
    @login_required
    def dataset_delete_rows(dataset_id: int):
        dataset = _owned_dataset(settings, g.user["id"], dataset_id)
        positions = {
            int(value)
            for value in request.form.getlist("delete_positions")
            if value.isdigit()
        }
        if not positions:
            flash("Выберите строки для удаления.", "error")
            return redirect(url_for("dataset_detail", dataset_id=dataset_id))

        remaining_count = _remove_csv_rows(Path(dataset["file_path"]), positions)
        update_dataset_after_edit(
            _database(settings), g.user["id"], dataset_id, remaining_count
        )
        flash(f"Удалено строк: {len(positions)}. CSV обновлён.", "success")
        return redirect(url_for("dataset_detail", dataset_id=dataset_id))

    @app.post("/competitors/datasets/<int:dataset_id>/save")
    @login_required
    def dataset_save(dataset_id: int):
        dataset = _owned_dataset(settings, g.user["id"], dataset_id)
        set_dataset_saved(
            _database(settings),
            g.user["id"],
            dataset_id,
            not bool(dataset["saved"]),
        )
        flash("Статус набора данных обновлён.", "success")
        return redirect(url_for("dataset_detail", dataset_id=dataset_id))

    @app.post("/competitors/datasets/<int:dataset_id>/analyze")
    @login_required
    def dataset_analyze(dataset_id: int):
        dataset = _owned_dataset(settings, g.user["id"], dataset_id)
        remaining = claim_report_creation(
            _database(settings), g.user["id"], f"market_dataset:{dataset_id}"
        )
        if remaining:
            flash(
                f"Отчёт уже создавался недавно. Повторите через {remaining} сек.",
                "error",
            )
            return redirect(url_for("dataset_detail", dataset_id=dataset_id))
        products, analysis, report_dir, run_id = analyze_competitor_csv(
            csv_path=Path(dataset["file_path"]),
            database=_database(settings),
            reports_dir=_user_reports_dir(settings, g.user["id"]),
            source=dataset["source"],
            user_id=g.user["id"],
        )
        update_dataset_analysis(
            _database(settings),
            g.user["id"],
            dataset_id,
            run_id,
            len(products),
        )
        return render_template(
            "competitor_result.html",
            products=products,
            analysis=analysis,
            report_dir=report_dir,
            run_id=run_id,
            dataset={**dataset, "analysis_run_id": run_id},
        )

    @app.get("/compare")
    def compare():
        database = _database(settings)
        return render_template(
            "compare.html",
            seller_products=_seller_rows(database, g.user["id"]) if g.user else [],
            datasets=list_datasets(database, g.user["id"]) if g.user else [],
        )

    @app.post("/compare")
    @login_required
    def compare_run():
        dataset = _owned_dataset(
            settings,
            g.user["id"],
            int(request.form.get("dataset_id", "0")),
        )
        remaining = claim_report_creation(
            _database(settings), g.user["id"], "comparison"
        )
        if remaining:
            flash(
                f"Отчёт уже создавался недавно. Повторите через {remaining} сек.",
                "error",
            )
            return redirect(url_for("compare"))
        comparison, report_dir, run_id = compare_with_csv(
            seller_product_id=request.form.get("seller_product_id", "").strip(),
            csv_path=Path(dataset["file_path"]),
            database=_database(settings),
            reports_dir=_user_reports_dir(settings, g.user["id"]),
            limit=_optional_int(request.form.get("limit")),
            user_id=g.user["id"],
        )
        return render_template(
            "comparison_result.html",
            comparison=comparison,
            report_dir=report_dir,
            run_id=run_id,
        )

    @app.errorhandler(Exception)
    def handle_error(exc: Exception):
        if isinstance(exc, HTTPException):
            if isinstance(exc, NotFound):
                return render_template("error.html", message="Страница не найдена."), 404
            return exc
        if isinstance(
            exc,
            (
                ExternalParserError,
                CompetitorCsvError,
                OzonSellerApiError,
                LookupError,
                ValueError,
                sqlite3.Error,
                OSError,
            ),
        ):
            return render_template("error.html", message=str(exc)), 400
        raise exc

    return app


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def _database(settings: Settings) -> Database:
    return Database(sqlite_path_from_url(settings.database_url))


def _web_secret() -> str:
    key_path = Path("data/.web_secret")
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if not key_path.exists():
        key_path.write_text(uuid.uuid4().hex + uuid.uuid4().hex, encoding="ascii")
    return key_path.read_text(encoding="ascii").strip()


def _seller_client(settings: Settings, app: Flask, user_id: int) -> OzonSellerApiClient:
    credentials = get_api_credentials(
        _database(settings), app.extensions["secret_box"], user_id
    )
    if credentials is None:
        raise ValueError("Сначала сохраните Client ID и API Key.")
    return OzonSellerApiClient(
        client_id=credentials[0],
        api_key=credentials[1],
        base_url=settings.ozon_api_base_url,
        product_list_path=settings.ozon_product_list_path,
        product_info_path=settings.ozon_product_info_path,
        product_stock_path=settings.ozon_product_stock_path,
        product_price_path=settings.ozon_product_price_path,
    )


def _seller_rows(database: Database, user_id: int) -> list[dict]:
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT * FROM seller_products WHERE user_id = ? ORDER BY name",
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _dashboard_stats(database: Database, user_id: int) -> dict:
    with database.connect() as connection:
        sellers = connection.execute(
            "SELECT COUNT(*) FROM seller_products WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        datasets = connection.execute(
            "SELECT COUNT(*) FROM competitor_datasets WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        runs = connection.execute(
            "SELECT COUNT(*) FROM analysis_runs WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
    return {
        "seller_products": sellers,
        "competitor_products": datasets,
        "analysis_runs": runs,
        "latest_run": None,
    }


def _empty_stats() -> dict:
    return {
        "seller_products": 0,
        "competitor_products": 0,
        "analysis_runs": 0,
        "latest_run": None,
    }


def _optional_int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    result = int(value)
    if result < 1:
        raise ValueError("Значение должно быть больше нуля.")
    return result


def _user_data_dir(user_id: int) -> Path:
    path = Path("data/users") / str(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _user_reports_dir(settings: Settings, user_id: int) -> Path:
    return settings.reports_dir / f"user_{user_id}"


def _save_upload(file_storage, user_id: int) -> tuple[Path, str]:
    if file_storage is None or not file_storage.filename:
        raise ValueError("Выберите CSV-файл.")
    original_name = file_storage.filename
    if Path(original_name).suffix.lower() not in ALLOWED_UPLOADS:
        raise ValueError("Поддерживаются только CSV-файлы.")
    upload_dir = _user_data_dir(user_id) / "datasets"
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = secure_filename(original_name) or "competitors.csv"
    destination = upload_dir / f"{uuid.uuid4().hex}_{safe_name}"
    file_storage.save(destination)
    return destination, original_name


def _owned_dataset(settings: Settings, user_id: int, dataset_id: int) -> dict:
    dataset = get_dataset(_database(settings), user_id, dataset_id)
    if dataset is None:
        raise LookupError("Набор данных не найден.")
    return dataset


def _owned_job(settings: Settings, user_id: int, job_id: int) -> dict:
    job = get_parser_job(_database(settings), user_id, job_id)
    if job is None:
        raise LookupError("Задача парсинга не найдена.")
    return job


def _analysis_result(
    database: Database, user_id: int, analysis_run_id: int | None
) -> dict | None:
    if not analysis_run_id:
        return None
    with database.connect() as connection:
        row = connection.execute(
            "SELECT result_json FROM analysis_runs WHERE id = ? AND user_id = ?",
            (analysis_run_id, user_id),
        ).fetchone()
    if row is None or not row["result_json"]:
        return None
    import json

    return json.loads(row["result_json"])


def _latest_seller_report(settings: Settings, user_id: int) -> dict | None:
    reports_root = _user_reports_dir(settings, user_id)
    if not reports_root.exists():
        return None
    report_dirs = [
        path
        for path in reports_root.glob("seller_api_*")
        if path.is_dir() and (path / "seller_summary.txt").exists()
    ]
    if not report_dirs:
        return None
    latest = max(report_dirs, key=lambda path: path.stat().st_mtime)
    created_at = latest.name.replace("seller_api_", "", 1)
    return {"dir": latest, "created_at": created_at}


def _csv_download_response(path: Path, download_name: str):
    content = _excel_safe_csv_text(_read_csv_text(path))
    buffer = BytesIO(content.encode("utf-8-sig"))
    return send_file(
        buffer,
        mimetype="text/csv; charset=utf-8",
        as_attachment=True,
        download_name=download_name,
        max_age=0,
    )


def _read_csv_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "windows-1251"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _remove_csv_rows(path: Path, positions: set[int]) -> int:
    content = _read_csv_text(path)
    sample = content[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";"

    source = StringIO(content)
    reader = csv.DictReader(source, delimiter=delimiter)
    if not reader.fieldnames:
        return 0

    rows = [
        row
        for position, row in enumerate(reader, 1)
        if position not in positions
    ]
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=reader.fieldnames,
        delimiter=delimiter,
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(output.getvalue(), encoding="utf-8-sig", newline="")
    return len(rows)


def _excel_safe_csv_text(content: str) -> str:
    sample = content[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";"

    source = StringIO(content)
    reader = csv.DictReader(source, delimiter=delimiter)
    if not reader.fieldnames:
        return content

    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=reader.fieldnames,
        delimiter=delimiter,
        lineterminator="\n",
    )
    writer.writeheader()
    for row in reader:
        if "Средний отзыв" in row and row["Средний отзыв"]:
            rating = row["Средний отзыв"].strip().replace(",", ".")
            if rating and not rating.startswith('="'):
                row["Средний отзыв"] = f'="{rating}"'
        writer.writerow(row)
    return output.getvalue()


def _run_parser_job(
    settings: Settings,
    database_path: Path,
    user_id: int,
    job_id: int,
    url: str,
    timeout: int,
    cancel_event: threading.Event,
) -> None:
    database = Database(database_path)
    progress_state = {"processed_links": None, "total_links": None}

    def _progress_callback(processed: int | None, total: int | None) -> None:
        if processed is not None:
            progress_state["processed_links"] = processed
        if total is not None:
            progress_state["total_links"] = total
        update_parser_job(
            database,
            job_id,
            status="running",
            message=(
                f"Парсинг маркета выполняется"
                + (
                    f" ({progress_state['processed_links']}/{progress_state['total_links']})"
                    if progress_state["processed_links"] is not None
                    else ""
                )
            ),
            processed_links=progress_state["processed_links"],
            total_links=progress_state["total_links"],
        )
    try:
        update_parser_job(
            database,
            job_id,
            status="running",
            message="Парсинг маркета выполняется",
        )
        parser_dir, _ = parser_paths(settings, None, None)
        output_dir = _user_data_dir(user_id) / "parser_output"
        with PARSER_LOCK:
            csv_path = ExternalParserRunner(
                str(parser_dir), str(output_dir), timeout
            ).run(
                url=url,
                query_name=query_name_from_url(url),
                cancel_event=cancel_event,
                progress_callback=_progress_callback,
            )
        products = CompetitorCsvReader().load(csv_path)
        stored_dir = _user_data_dir(user_id) / "datasets"
        stored_dir.mkdir(parents=True, exist_ok=True)
        stored_path = stored_dir / csv_path.name
        if csv_path.resolve() != stored_path.resolve():
            shutil.copy2(csv_path, stored_path)
        dataset_id = create_dataset(
            database,
            user_id=user_id,
            name=query_name_from_url(url) or csv_path.stem,
            source="external_parser",
            source_url=url,
            file_path=stored_path,
            original_filename=csv_path.name,
            products_count=len(products),
        )
        update_parser_job(
            database,
            job_id,
            status="success",
            message=f"Готово: собрано {len(products)} товаров",
            processed_links=len(products),
            total_links=len(products),
            dataset_id=dataset_id,
        )
    except ExternalParserCancelledError:
        update_parser_job(
            database,
            job_id,
            status="cancelled",
            message="Парсинг отменён",
        )
    except Exception as exc:
        logging.exception("Parser job %s failed", job_id)
        update_parser_job(
            database,
            job_id,
            status="error",
            message="Парсинг завершился с ошибкой",
            error=str(exc),
        )
    finally:
        with ACTIVE_JOB_EVENTS_LOCK:
            ACTIVE_JOB_EVENTS.pop(job_id, None)
