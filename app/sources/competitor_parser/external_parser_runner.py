from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.sources.competitor_parser.exceptions import (
    ExternalParserConfigError,
    ExternalParserOutputNotFoundError,
    ExternalParserRunError,
    ExternalParserTimeoutError,
)


logger = logging.getLogger(__name__)


class ExternalParserRunner:
    """Adapter for the existing ozon-seller-parser CLI.

    The parser accepts only ``collect``, ``scrape`` and ``all``. URL and output
    paths are therefore passed through its existing config.json contract.
    """

    def __init__(
        self,
        parser_dir: str,
        output_dir: str,
        timeout_seconds: int = 900,
    ):
        self.parser_dir = Path(parser_dir).expanduser().resolve()
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.timeout_seconds = timeout_seconds
        self.entrypoint = self.parser_dir / "run.py"
        self.config_path = self.parser_dir / "config.json"

    def run(
        self,
        url: str,
        query_name: str | None = None,
        limit: int | None = None,
    ) -> Path:
        del limit  # The external parser has no CLI/config limit option.
        self._validate()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        original_config_text = self.config_path.read_text(encoding="utf-8")
        try:
            config = json.loads(original_config_text)
        except json.JSONDecodeError as exc:
            raise ExternalParserConfigError(
                f"Некорректный JSON в {self.config_path}: {exc}"
            ) from exc

        run_stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        slug = self._slug(query_name) if query_name else "products"
        expected_csv = self.output_dir / f"{slug}_{run_stamp}.csv"
        links_file = self.output_dir / f"product_links_{run_stamp}.txt"
        parser_log = self.output_dir / f"parser_{run_stamp}.log"
        integration_log = self.output_dir / f"subprocess_{run_stamp}.log"

        temporary_config = dict(config)
        temporary_config.update(
            {
                "seller_url": url,
                "links_file": str(links_file),
                "output_file": str(expected_csv),
                "log_file": str(parser_log),
            }
        )

        started_at = datetime.now(timezone.utc).timestamp()
        try:
            self.config_path.write_text(
                json.dumps(temporary_config, ensure_ascii=False, indent=4) + "\n",
                encoding="utf-8",
            )
            try:
                completed = subprocess.run(
                    [sys.executable, str(self.entrypoint), "all"],
                    cwd=self.parser_dir,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    encoding="utf-8",
                    errors="replace",
                )
            except subprocess.TimeoutExpired as exc:
                self._write_log(integration_log, exc.stdout or "", exc.stderr or "")
                raise ExternalParserTimeoutError(
                    "Парсинг занял слишком много времени. Увеличьте timeout "
                    "или проверьте внешний парсер."
                ) from exc

            self._write_log(integration_log, completed.stdout, completed.stderr)
            if completed.returncode != 0:
                detail = self._last_output_line(completed.stderr or completed.stdout)
                message = (
                    f"Внешний парсер завершился с кодом {completed.returncode}. "
                    f"Лог: {integration_log}"
                )
                if detail:
                    message += f". Последнее сообщение: {detail}"
                raise ExternalParserRunError(message)
        finally:
            self.config_path.write_text(original_config_text, encoding="utf-8")

        if expected_csv.exists() and expected_csv.stat().st_mtime >= started_at - 1:
            return expected_csv

        fresh_csv_files = [
            path
            for path in self.output_dir.glob("*.csv")
            if path.stat().st_mtime >= started_at - 1
        ]
        if fresh_csv_files:
            return max(fresh_csv_files, key=lambda path: path.stat().st_mtime)

        raise ExternalParserOutputNotFoundError(
            f"Внешний парсер завершился, но свежий CSV не найден в {self.output_dir}. "
            f"Проверьте лог: {integration_log}"
        )

    def _validate(self) -> None:
        if not self.parser_dir.is_dir():
            raise ExternalParserConfigError(
                f"Директория внешнего парсера не найдена: {self.parser_dir}"
            )
        if not self.entrypoint.is_file():
            raise ExternalParserConfigError(
                f"Entrypoint внешнего парсера не найден: {self.entrypoint}"
            )
        if not self.config_path.is_file():
            raise ExternalParserConfigError(
                f"Не найден обязательный config.json: {self.config_path}. "
                "Настройте внешний парсер по его README."
            )
        if self.timeout_seconds < 1:
            raise ExternalParserConfigError("timeout_seconds должен быть больше нуля.")

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9а-яА-Я_-]+", "_", value.strip())
        return slug.strip("_")[:80] or "products"

    @staticmethod
    def _write_log(path: Path, stdout: str, stderr: str) -> None:
        path.write_text(
            f"STDOUT\n{stdout}\n\nSTDERR\n{stderr}\n", encoding="utf-8"
        )
        logger.info("External parser subprocess log: %s", path)

    @staticmethod
    def _last_output_line(output: str) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        return lines[-1] if lines else ""
