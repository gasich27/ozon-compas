from __future__ import annotations

from app.analytics.competitor_analyzer import analyze_competitor_products
from app.models import CompetitorProduct, SellerProduct


def compare_seller_product_with_competitors(
    seller_product: SellerProduct,
    competitors: list[CompetitorProduct],
) -> dict:
    market = analyze_competitor_products(competitors)
    seller_price = seller_product.price
    median_price = market["median_price"]

    price_gap_percent = None
    price_position = "unknown"
    if seller_price is not None and median_price not in (None, 0):
        price_gap_percent = round(
            ((seller_price - median_price) / median_price) * 100, 2
        )
        if price_gap_percent < -5:
            price_position = "cheaper_than_market"
        elif price_gap_percent > 5:
            price_position = "more_expensive_than_market"
        else:
            price_position = "near_market"

    priced_competitors = [
        product for product in competitors if product.price is not None
    ]
    seller_rank = None
    if seller_price is not None and priced_competitors:
        seller_rank = (
            sum(product.price < seller_price for product in priced_competitors) + 1
        )

    recommendations: list[str] = []
    if len(competitors) < 3:
        recommendations.append(
            "Данных конкурентов недостаточно для уверенного вывода."
        )
    if price_position == "more_expensive_than_market":
        recommendations.append(
            "Товар дороже медианы конкурентов. Рассмотрите снижение цены "
            "или усиление карточки."
        )
    elif price_position == "cheaper_than_market":
        recommendations.append(
            "Товар дешевле медианы конкурентов. Проверьте маржинальность, "
            "возможно есть потенциал для повышения цены."
        )
    if seller_product.stock is not None and seller_product.stock < 10:
        recommendations.append("Остатки низкие. Есть риск потерять продажи.")
    if len(competitors) >= 20:
        recommendations.append(
            "Конкуренция высокая, потребуется сильная карточка и аккуратная цена."
        )
    if not recommendations:
        recommendations.append(
            "Цена близка к рынку. Следите за остатками, рейтингом и динамикой цен."
        )

    return {
        "seller_product": seller_product.to_dict(),
        "seller_price": seller_price,
        "market_median_price": median_price,
        "market_average_price": market["average_price"],
        "price_gap_percent": price_gap_percent,
        "seller_stock": seller_product.stock,
        "market_average_rating": market["average_rating"],
        "market_median_reviews": market["median_reviews"],
        "seller_position_by_price": price_position,
        "seller_price_rank": seller_rank,
        "competitors_count": len(competitors),
        "recommendations": recommendations,
    }
