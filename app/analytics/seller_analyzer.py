from __future__ import annotations

from statistics import mean, median

from app.models import SellerProduct


def analyze_seller_products(products: list[SellerProduct]) -> dict:
    prices = [product.price for product in products if product.price is not None]
    stocks = [product.stock for product in products if product.stock is not None]
    ratings = [product.rating for product in products if product.rating is not None]
    reviews = [
        product.reviews_count for product in products if product.reviews_count is not None
    ]

    in_stock = [product for product in products if (product.stock or 0) > 0]
    out_of_stock = [product for product in products if (product.stock or 0) <= 0]

    return {
        "total_products": len(products),
        "average_price": round(float(mean(prices)), 2) if prices else None,
        "median_price": round(float(median(prices)), 2) if prices else None,
        "min_price": min(prices) if prices else None,
        "max_price": max(prices) if prices else None,
        "average_stock": round(float(mean(stocks)), 2) if stocks else None,
        "total_stock": sum(stocks) if stocks else None,
        "average_rating": round(float(mean(ratings)), 2) if ratings else None,
        "median_rating": round(float(median(ratings)), 2) if ratings else None,
        "average_reviews": round(float(mean(reviews)), 2) if reviews else None,
        "products_in_stock": len(in_stock),
        "products_out_of_stock": len(out_of_stock),
        "top_priced_products": [
            product.to_dict()
            for product in sorted(
                [p for p in products if p.price is not None],
                key=lambda item: item.price,
                reverse=True,
            )[:10]
        ],
    }
