from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass
class CompetitorProduct:
    name: str
    product_url: str
    sku: str
    price: float | None
    reviews_count: int | None
    average_rating: float | None
    position: int
    collected_at: datetime

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["collected_at"] = self.collected_at.isoformat()
        return data


@dataclass
class SellerProduct:
    id: str
    name: str
    price: float | None
    stock: int | None
    sku: str | None = None
    product_url: str | None = None
    rating: float | None = None
    reviews_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
