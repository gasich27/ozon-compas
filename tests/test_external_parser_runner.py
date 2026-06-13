import json
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.sources.competitor_parser.exceptions import (
    ExternalParserConfigError,
    ExternalParserOutputNotFoundError,
    ExternalParserRunError,
    ExternalParserTimeoutError,
)
from app.sources.competitor_parser.external_parser_runner import (
    ExternalParserRunner,
)


def make_parser(tmp_path: Path) -> tuple[Path, Path]:
    parser_dir = tmp_path / "parser"
    output_dir = tmp_path / "output"
    parser_dir.mkdir()
    output_dir.mkdir()
    (parser_dir / "run.py").write_text("print('unused')\n", encoding="utf-8")
    (parser_dir / "config.json").write_text(
        json.dumps(
            {
                "seller_url": "https://www.ozon.ru/seller/example/",
                "links_file": "product_links.txt",
                "output_file": "product_details.csv",
                "log_file": "parser.log",
            }
        ),
        encoding="utf-8",
    )
    return parser_dir, output_dir


def test_error_if_parser_dir_does_not_exist(tmp_path: Path) -> None:
    runner = ExternalParserRunner(
        str(tmp_path / "missing"), str(tmp_path / "output")
    )
    with pytest.raises(ExternalParserConfigError):
        runner.run("https://www.ozon.ru/search/?text=test")


def test_error_if_success_process_does_not_create_csv(tmp_path: Path) -> None:
    parser_dir, output_dir = make_parser(tmp_path)
    runner = ExternalParserRunner(str(parser_dir), str(output_dir))
    with patch("subprocess.run", return_value=Mock(returncode=0, stdout="", stderr="")):
        with pytest.raises(ExternalParserOutputNotFoundError):
            runner.run("https://www.ozon.ru/search/?text=test")


def test_success_returns_fresh_csv(tmp_path: Path) -> None:
    parser_dir, output_dir = make_parser(tmp_path)
    runner = ExternalParserRunner(str(parser_dir), str(output_dir))

    def fake_run(*args, **kwargs):
        config = json.loads((parser_dir / "config.json").read_text(encoding="utf-8"))
        Path(config["output_file"]).write_text(
            "Название;Ссылка на товар;Артикул;Цена;"
            "Количество отзывов;Средний отзыв\n",
            encoding="utf-8",
        )
        return Mock(returncode=0, stdout="ok", stderr="")

    original = (parser_dir / "config.json").read_text(encoding="utf-8")
    with patch("subprocess.run", side_effect=fake_run):
        result = runner.run("https://www.ozon.ru/search/?text=test")

    assert result.exists()
    assert (parser_dir / "config.json").read_text(encoding="utf-8") == original


def test_timeout_is_wrapped(tmp_path: Path) -> None:
    parser_dir, output_dir = make_parser(tmp_path)
    runner = ExternalParserRunner(str(parser_dir), str(output_dir))
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="python run.py all", timeout=1),
    ):
        with pytest.raises(ExternalParserTimeoutError):
            runner.run("https://www.ozon.ru/search/?text=test")


def test_non_zero_exit_is_wrapped(tmp_path: Path) -> None:
    parser_dir, output_dir = make_parser(tmp_path)
    runner = ExternalParserRunner(str(parser_dir), str(output_dir))
    completed = Mock(returncode=1, stdout="", stderr="parser failed")
    with patch("subprocess.run", return_value=completed):
        with pytest.raises(ExternalParserRunError, match="кодом 1"):
            runner.run("https://www.ozon.ru/search/?text=test")
