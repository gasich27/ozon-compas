from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

from app.sources.competitor_parser.exceptions import (
    ExternalParserCancelledError,
    ExternalParserConfigError,
    ExternalParserOutputNotFoundError,
    ExternalParserRunError,
    ExternalParserTimeoutError,
)


logger = logging.getLogger(__name__)


class ExternalParserRunner:
    """Adapter for the existing ozon-seller-parser CLI."""

    def __init__(self, parser_dir: str, output_dir: str, timeout_seconds: int = 900):
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
        cancel_event: Event | None = None,
        progress_callback: Callable[[int | None, int | None], None] | None = None,
    ) -> Path:
        del limit
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
            completed = self._run_process(
                integration_log=integration_log,
                cancel_event=cancel_event,
                progress_callback=progress_callback,
            )
            if completed.returncode != 0:
                detail = self._extract_failure_detail(
                    completed.stdout or "", completed.stderr or ""
                )
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

    def _run_process(
        self,
        integration_log: Path,
        cancel_event: Event | None,
        progress_callback: Callable[[int | None, int | None], None] | None,
    ) -> subprocess.CompletedProcess:
        process = subprocess.Popen(
            [sys.executable, str(self.entrypoint), "all"],
            cwd=self.parser_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        stdout_chunks: list[str] = []
        started = time.monotonic()
        while True:
            if cancel_event is not None and cancel_event.is_set():
                self._terminate_process(process)
                stdout, _ = process.communicate(timeout=5)
                if stdout:
                    stdout_chunks.append(stdout)
                self._write_log(integration_log, "".join(stdout_chunks), "")
                raise ExternalParserCancelledError("Парсинг отменён пользователем.")
            if time.monotonic() - started > self.timeout_seconds:
                process.kill()
                stdout, _ = process.communicate()
                if stdout:
                    stdout_chunks.append(stdout)
                self._write_log(integration_log, "".join(stdout_chunks), "")
                raise ExternalParserTimeoutError(
                    "Парсинг занял слишком много времени. Увеличьте timeout или проверьте внешний парсер."
                )
            if process.stdout is None:
                break
            line = process.stdout.readline()
            if line:
                stdout_chunks.append(line)
                if progress_callback is not None:
                    processed, total = self._parse_progress(line)
                    if processed is not None or total is not None:
                        progress_callback(processed, total)
                continue
            if process.poll() is not None:
                break
            time.sleep(0.1)
        stdout, _ = process.communicate()
        if stdout:
            stdout_chunks.append(stdout)
        stdout_text = "".join(stdout_chunks)
        self._write_log(integration_log, stdout_text, "")
        return subprocess.CompletedProcess(process.args, process.returncode, stdout_text, "")

    @staticmethod
    def _terminate_process(process: subprocess.Popen) -> None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        else:
            process.terminate()

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
                f"Не найден обязательный config.json: {self.config_path}."
            )
        if self.timeout_seconds < 1:
            raise ExternalParserConfigError("timeout_seconds должен быть больше нуля.")

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9а-яА-Я_-]+", "_", value.strip())
        return slug.strip("_")[:80] or "products"

    @staticmethod
    def _write_log(path: Path, stdout: str, stderr: str) -> None:
        path.write_text(f"STDOUT\n{stdout}\n\nSTDERR\n{stderr}\n", encoding="utf-8")
        logger.info("External parser subprocess log: %s", path)

    @staticmethod
    def _last_output_line(output: str) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        return lines[-1] if lines else ""

    @staticmethod
    def _parse_progress(line: str) -> tuple[int | None, int | None]:
        text = line.lower()
        match = re.search(r"(\d+)\s*/\s*(\d+)", text)
        if match:
            return int(match.group(1)), int(match.group(2))
        match = re.search(r"собрано\s+(\d+)", text)
        if match:
            return int(match.group(1)), None
        return None, None

    @staticmethod
    def _extract_failure_detail(stdout: str, stderr: str) -> str:
        combined = "\n".join(part for part in (stdout, stderr) if part)
        if "ChromeDriver only supports Chrome version" in combined:
            return (
                "Несовместимые версии Chrome и ChromeDriver. "
                "Нужно обновить браузер или драйвер внешнего парсера."
            )
        if "Current browser version is" in combined:
            return (
                "Версия установленного Chrome не совпадает с ChromeDriver. "
                "Обновите Chrome или внешний драйвер."
            )
        if "session not created: cannot connect to chrome" in combined:
            return (
                "Внешний парсер не смог подключиться к Chrome. "
                "Проверьте установленный браузер и ChromeDriver."
            )
        if "WinError 6" in combined or "OSError: [WinError 6]" in combined:
            return (
                "Внешний парсер завершился с ошибкой управления Chrome. "
                "Скорее всего, у браузера и драйвера разные версии."
            )
        return ExternalParserRunner._last_output_line(stderr or stdout)
