class OzonSellerApiError(Exception):
    """Base error for Ozon Seller API integration."""


class OzonSellerApiAuthError(OzonSellerApiError):
    """Raised when API credentials are missing or rejected."""


class OzonSellerApiResponseError(OzonSellerApiError):
    """Raised when the API returns an unexpected payload."""
