from pathlib import Path

from app.database import Database
from app.models import SellerProduct
from app.services.comparison_service import compare_with_csv


def test_compare_with_csv_returns_gap_and_recommendations(tmp_path: Path) -> None:
    database = Database(tmp_path / "radar.db")
    database.upsert_seller_product(
        SellerProduct(
            id="123456",
            name="Товар селлера",
            price=1500.0,
            stock=5,
        )
    )
    csv_path = tmp_path / "competitors.csv"
    csv_path.write_text(
        "Название;Ссылка на товар;Артикул;Цена;Количество отзывов;Средний отзыв\n"
        "A;https://www.ozon.ru/product/a-1/;1;1000;10;4.5\n"
        "B;https://www.ozon.ru/product/b-2/;2;1200;20;4.7\n"
        "C;https://www.ozon.ru/product/c-3/;3;1400;30;4.9\n",
        encoding="utf-8",
    )

    result, report_dir, _ = compare_with_csv(
        seller_product_id="123456",
        csv_path=csv_path,
        database=database,
        reports_dir=tmp_path / "reports",
    )

    assert result["price_gap_percent"] is not None
    assert result["recommendations"]
    assert report_dir.exists()
    assert (report_dir / "comparison_result.xlsx").exists()
