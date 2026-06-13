from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.models import SellerProduct
from app.sources.seller_api.exceptions import (
    OzonSellerApiAuthError,
    OzonSellerApiError,
    OzonSellerApiResponseError,
)


@dataclass(frozen=True)
class SellerApiCredentials:
    client_id: str
    api_key: str


class OzonSellerApiClient:
    def __init__(
        self,
        *,
        client_id: str,
        api_key: str,
        base_url: str = "https://api-seller.ozon.ru",
        product_list_path: str = "/v2/product/list",
        product_info_path: str = "/v2/product/info/list",
        product_stock_path: str = "/v1/product/info/stocks",
        product_price_path: str = "/v1/product/info/prices",
        timeout_seconds: int = 30,
    ):
        self.credentials = SellerApiCredentials(client_id=client_id, api_key=api_key)
        self.base_url = base_url.rstrip("/")
        self.product_list_path = product_list_path
        self.product_info_path = product_info_path
        self.product_stock_path = product_stock_path
        self.product_price_path = product_price_path
        self.timeout_seconds = timeout_seconds

    def check_credentials(self) -> tuple[bool, str]:
        try:
            self.list_products(limit=1)
            return True, "Seller API credentials are valid."
        except OzonSellerApiAuthError as exc:
            return False, str(exc)
        except OzonSellerApiError as exc:
            return False, str(exc)

    def list_products(self, limit: int | None = None) -> list[SellerProduct]:
        items = self._fetch_paginated_products(limit=limit)
        if not items:
            return []
        product_ids = [self._extract_product_id(item) for item in items]
        info_by_id = self._merge_by_product_id(
            self._request_json(
                self.product_info_path,
                {"product_id": [pid for pid in product_ids if pid]},
            )
        )
        stock_by_id = self._merge_by_product_id(
            self._request_json(
                self.product_stock_path,
                {"product_id": [pid for pid in product_ids if pid]},
            )
        )
        price_by_id = self._merge_by_product_id(
            self._request_json(
                self.product_price_path,
                {"product_id": [pid for pid in product_ids if pid]},
            )
        )

        products: list[SellerProduct] = []
        for item in items:
            product_id = self._extract_product_id(item)
            info = info_by_id.get(product_id, {})
            stock = self._extract_stock(stock_by_id.get(product_id, {}))
            price = self._extract_price(price_by_id.get(product_id, {}), info)
            products.append(
                SellerProduct(
                    id=str(product_id or self._extract_text(item, "offer_id") or ""),
                    name=self._extract_text(info, "name")
                    or self._extract_text(item, "name")
                    or self._extract_text(item, "product_name")
                    or "Без названия",
                    price=price,
                    stock=stock,
                    sku=self._extract_text(info, "sku")
                    or self._extract_text(item, "sku"),
                    product_url=self._build_product_url(product_id),
                    rating=self._extract_float(info, "rating"),
                    reviews_count=self._extract_int(info, "reviews_count")
                    or self._extract_int(info, "review_count"),
                )
            )
        return products

    def _fetch_paginated_products(self, limit: int | None = None) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        last_id = ""
        page_size = min(max(limit or 1000, 1), 1000)
        while True:
            payload = {
                "filter": {"visibility": "ALL"},
                "last_id": last_id,
                "limit": page_size,
            }
            response = self._request_json(self.product_list_path, payload)
            result = response.get("result") or response
            items = result.get("items") or result.get("products") or []
            if not isinstance(items, list):
                raise OzonSellerApiResponseError(
                    "Seller API returned an unexpected product list payload."
                )
            collected.extend([item for item in items if isinstance(item, dict)])
            if limit is not None and len(collected) >= limit:
                return collected[:limit]
            next_last_id = (
                result.get("last_id")
                or result.get("lastId")
                or response.get("last_id")
                or response.get("lastId")
            )
            if not next_last_id or next_last_id == last_id or not items:
                return collected
            last_id = str(next_last_id)

    def _request_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.credentials.client_id or not self.credentials.api_key:
            raise OzonSellerApiAuthError(
                "OZON_CLIENT_ID и OZON_API_KEY должны быть заданы."
            )
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Client-Id": self.credentials.client_id,
                "Api-Key": self.credentials.api_key,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise OzonSellerApiAuthError(
                    f"Seller API authentication failed with HTTP {exc.code}."
                ) from exc
            raise OzonSellerApiError(
                f"Seller API request failed with HTTP {exc.code}: {exc.reason}"
            ) from exc
        except URLError as exc:
            raise OzonSellerApiError(f"Seller API connection error: {exc.reason}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OzonSellerApiResponseError(
                "Seller API returned invalid JSON."
            ) from exc
        if not isinstance(data, dict):
            raise OzonSellerApiResponseError(
                "Seller API returned an unexpected JSON payload."
            )
        return data

    @staticmethod
    def _extract_product_id(item: dict[str, Any]) -> str:
        for key in ("product_id", "id", "offer_id", "sku"):
            value = item.get(key)
            if value not in (None, ""):
                return str(value)
        return ""

    @staticmethod
    def _merge_by_product_id(response: dict[str, Any]) -> dict[str, dict[str, Any]]:
        result = response.get("result") or response
        items = result.get("items") or result.get("products") or []
        merged: dict[str, dict[str, Any]] = {}
        if not isinstance(items, list):
            return merged
        for item in items:
            if not isinstance(item, dict):
                continue
            key = OzonSellerApiClient._extract_product_id(item)
            if key:
                merged[key] = item
        return merged

    @staticmethod
    def _extract_text(item: dict[str, Any], key: str) -> str | None:
        value = item.get(key)
        if value in (None, ""):
            return None
        return str(value)

    @staticmethod
    def _extract_int(item: dict[str, Any], key: str) -> int | None:
        value = item.get(key)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_float(item: dict[str, Any], key: str) -> float | None:
        value = item.get(key)
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_stock(item: dict[str, Any]) -> int | None:
        for key in ("stocks", "stock", "available_stock", "free_stock"):
            value = item.get(key)
            if isinstance(value, dict):
                nested = value.get("present") or value.get("free") or value.get("value")
                if nested not in (None, ""):
                    try:
                        return int(nested)
                    except (TypeError, ValueError):
                        pass
            elif value not in (None, ""):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _extract_price(item: dict[str, Any], fallback: dict[str, Any]) -> float | None:
        candidate_sources = [
            item,
            fallback,
        ]
        for source in candidate_sources:
            for key in ("price", "price_with_discount", "price_index", "old_price"):
                value = source.get(key)
                if value in (None, ""):
                    continue
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
            price_info = source.get("price")
            if isinstance(price_info, dict):
                for key in ("price", "value", "current"):
                    nested = price_info.get(key)
                    if nested not in (None, ""):
                        try:
                            return float(nested)
                        except (TypeError, ValueError):
                            continue
        return None

    @staticmethod
    def _build_product_url(product_id: str | None) -> str | None:
        if not product_id:
            return None
        return f"https://www.ozon.ru/product/{product_id}/"
