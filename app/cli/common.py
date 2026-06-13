from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.config import Settings
from app.sources.competitor_parser.exceptions import ExternalParserConfigError


def default_external_parser_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "ozon-seller-parser"


def default_external_parser_output_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "parser_output"


def validate_ozon_url(value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not (
        host == "ozon.ru" or host.endswith(".ozon.ru")
    ):
        raise ValueError("Укажите корректный URL на домене ozon.ru.")
    return value


def query_name_from_url(value: str) -> str | None:
    query = parse_qs(urlparse(value).query)
    for key in ("text", "query"):
        if query.get(key):
            return query[key][0]
    return None


def parser_paths(
    settings: Settings,
    parser_dir: str | None,
    output_dir: str | None,
) -> tuple[Path, Path]:
    resolved_parser = (
        Path(parser_dir)
        if parser_dir
        else settings.external_parser_path
        if settings.external_parser_path
        else default_external_parser_dir()
    )
    resolved_output = (
        Path(output_dir)
        if output_dir
        else settings.external_parser_output_dir
        if settings.external_parser_output_dir
        else default_external_parser_output_dir()
    )
    return resolved_parser, resolved_output


def confirm_parser_start(lines: list[str], assume_yes: bool) -> bool:
    for line in lines:
        print(line)
    if assume_yes:
        return True
    answer = input("Продолжить запуск парсера? [y/N] ").strip().lower()
    return answer in {"y", "yes", "д", "да"}
