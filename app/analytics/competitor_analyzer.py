from __future__ import annotations

from statistics import mean, median

from app.models import CompetitorProduct


def _average(values: list[float | int]) -> float | None:
    return round(float(mean(values)), 2) if values else None


def _median(values: list[float | int]) -> float | None:
    return round(float(median(values)), 2) if values else None


def analyze_competitor_products(
    products: list[CompetitorProduct],
) -> dict:
    prices = [product.price for product in products if product.price is not None]
    ratings = [
        product.average_rating
        for product in products
        if product.average_rating is not None
    ]
    reviews = [
        product.reviews_count
        for product in products
        if product.reviews_count is not None
    ]

    priced = [product for product in products if product.price is not None]
    reviewed = [
        product for product in products if product.reviews_count is not None
    ]
    rated = [
        product for product in products if product.average_rating is not None
    ]

    return {
        "total_products": len(products),
        "average_price": _average(prices),
        "median_price": _median(prices),
        "min_price": min(prices) if prices else None,
        "max_price": max(prices) if prices else None,
        "average_rating": _average(ratings),
        "median_rating": _median(ratings),
        "average_reviews": _average(reviews),
        "median_reviews": _median(reviews),
        "max_reviews": max(reviews) if reviews else None,
        "cheapest_products": [
            product.to_dict()
            for product in sorted(priced, key=lambda item: item.price)[:10]
        ],
        "most_expensive_products": [
            product.to_dict()
            for product in sorted(
                priced, key=lambda item: item.price, reverse=True
            )[:10]
        ],
        "most_reviewed_products": [
            product.to_dict()
            for product in sorted(
                reviewed, key=lambda item: item.reviews_count, reverse=True
            )[:10]
        ],
        "best_rated_products": [
            product.to_dict()
            for product in sorted(
                rated, key=lambda item: item.average_rating, reverse=True
            )[:10]
        ],
    }
