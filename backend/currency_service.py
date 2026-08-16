
from __future__ import annotations

import time

import requests


BASE_URL = "https://open.er-api.com/v6/latest/{base}"
REQUEST_TIMEOUT_SECONDS = 8


class CurrencyServiceError(Exception):
    """Raised when live rates can't be fetched (network/API failure)."""


class CurrencyService:
    def __init__(self):
        pass  

    # Public API
    
    def get_rates(self, base_currency: str = "USD") -> dict:
        """Return {currency_code: rate} for the given base currency, fetched live."""
        base_currency = base_currency.upper()
        try:
            return self._fetch_from_api(base_currency)
        except (requests.RequestException, ValueError) as exc:
            raise CurrencyServiceError(
                f"Could not fetch live exchange rates for {base_currency}: {exc}"
            ) from exc

    def get_rate(self, from_currency: str, to_currency: str) -> float:
        """Return the live rate to convert 1 unit of from_currency into to_currency."""
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()
        if from_currency == to_currency:
            return 1.0

        rates = self.get_rates(from_currency)
        if to_currency not in rates:
            raise CurrencyServiceError(f"Unknown currency code: {to_currency}")
        return rates[to_currency]

    def convert(self, amount: float, from_currency: str, to_currency: str) -> float:
        """Convert `amount` from one currency to another using the live rate."""
        rate = self.get_rate(from_currency, to_currency)
        return amount * rate

    def list_supported_currencies(self, base_currency: str = "USD") -> list[str]:
        rates = self.get_rates(base_currency)
        return sorted(set(rates.keys()) | {base_currency.upper()})

    # Internal helpers
    
    def _fetch_from_api(self, base_currency: str) -> dict:
        url = BASE_URL.format(base=base_currency)
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()

        if data.get("result") != "success":
            raise ValueError(f"API returned non-success result: {data.get('result')}")

        return data["rates"]


if __name__ == "__main__":
    
    svc = CurrencyService()
    start = time.time()
    rates = svc.get_rates("USD")
    print(f"Fetched {len(rates)} live rates in {time.time() - start:.2f}s")
    print("1 USD in EUR:", svc.convert(1, "USD", "EUR"))
    print("50 USD in KES:", svc.convert(50, "USD", "KES"))
