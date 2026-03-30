"""
Currency conversion utilities with real-time exchange rates.
"""
import logging
import os
from typing import Dict, Optional
from datetime import datetime, timedelta, timezone
import requests

logger = logging.getLogger(__name__)

# Default exchange rates (fallback if API unavailable)
DEFAULT_RATES: Dict[str, float] = {
    "USD": 1.0,
    "EUR": 0.92,
    "GBP": 0.79,
    "CAD": 1.36,
    "AUD": 1.53,
    "JPY": 149.50,
    "CHF": 0.88,
    "CNY": 7.24,
    "INR": 83.12,
    "MXN": 17.15,
    "BRL": 4.97,
    "SGD": 1.34,
}

# Cache for exchange rates
_rates_cache: Dict[str, Dict] = {}


def get_exchange_rate(
    from_currency: str,
    to_currency: str,
    force_refresh: bool = False
) -> Optional[float]:
    """
    Get exchange rate between two currencies.
    
    Args:
        from_currency: Source currency code (e.g., "USD")
        to_currency: Target currency code (e.g., "EUR")
        force_refresh: Force refresh from API
        
    Returns:
        Exchange rate or None if unavailable
    """
    global _rates_cache
    
    if from_currency == to_currency:
        return 1.0
    
    cache_key = f"{from_currency}_{to_currency}"
    
    # Check cache
    if not force_refresh and cache_key in _rates_cache:
        cached = _rates_cache[cache_key]
        # Cache valid for 1 hour
        if (datetime.now(timezone.utc) - cached["timestamp"]).total_seconds() < 3600:
            return cached["rate"]
    
    # Try to fetch from API
    rate = _fetch_exchange_rate(from_currency, to_currency)
    
    if rate is not None:
        _rates_cache[cache_key] = {
            "rate": rate,
            "timestamp": datetime.now(timezone.utc)
        }
        return rate
    
    # Fallback to default rates
    return _get_fallback_rate(from_currency, to_currency)


def _fetch_exchange_rate(from_currency: str, to_currency: str) -> Optional[float]:
    """
    Fetch exchange rate from external API.
    
    Supports:
    - ExchangeRate-API (free tier available)
    - Open Exchange Rates
    - Fixer.io
    """
    # Try ExchangeRate-API (free tier)
    api_key = os.getenv("EXCHANGERATE_API_KEY")
    
    if api_key:
        try:
            url = f"https://v6.exchangerate-api.com/v6/{api_key}/latest/{from_currency}"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                rates = data.get("conversion_rates", {})
                return rates.get(to_currency)
        except Exception as e:
            logger.warning(f"Failed to fetch exchange rate: {e}")
    
    return None


def _get_fallback_rate(from_currency: str, to_currency: str) -> Optional[float]:
    """Get rate from default rates with USD as intermediate."""
    from_rate = DEFAULT_RATES.get(from_currency)
    to_rate = DEFAULT_RATES.get(to_currency)
    
    if from_rate and to_rate:
        return to_rate / from_rate
    
    return None


def convert_amount(
    amount: float,
    from_currency: str,
    to_currency: str,
    force_refresh: bool = False
) -> Optional[float]:
    """
    Convert amount from one currency to another.
    
    Args:
        amount: Amount to convert
        from_currency: Source currency code
        to_currency: Target currency code
        force_refresh: Force refresh exchange rates
        
    Returns:
        Converted amount or None if conversion not possible
    """
    if amount == 0:
        return 0.0
    
    rate = get_exchange_rate(from_currency, to_currency, force_refresh)
    
    if rate is None:
        logger.warning(f"Could not get exchange rate for {from_currency} to {to_currency}")
        return None
    
    return round(amount * rate, 2)


def get_all_rates(from_currency: str = "USD") -> Dict[str, float]:
    """
    Get all exchange rates for a base currency.
    
    Args:
        from_currency: Base currency code
        
    Returns:
        Dictionary of currency codes to rates
    """
    rates = {}
    
    for to_currency in DEFAULT_RATES.keys():
        rate = get_exchange_rate(from_currency, to_currency)
        if rate:
            rates[to_currency] = rate
    
    return rates


def is_supported_currency(currency: str) -> bool:
    """Check if a currency is supported."""
    return currency in DEFAULT_RATES


class CurrencyConverter:
    """Currency converter class for more complex operations."""
    
    def __init__(self, base_currency: str = "USD"):
        self.base_currency = base_currency
        self._rates: Dict[str, float] = {}
    
    def update_rates(self, force: bool = False) -> bool:
        """Update exchange rates."""
        for currency in DEFAULT_RATES.keys():
            if currency != self.base_currency:
                rate = get_exchange_rate(self.base_currency, currency, force)
                if rate:
                    self._rates[currency] = rate
        return len(self._rates) > 0
    
    def convert(self, amount: float, to_currency: str) -> Optional[float]:
        """Convert amount to target currency."""
        if to_currency == self.base_currency:
            return amount
        
        rate = self._rates.get(to_currency)
        if rate is None:
            rate = get_exchange_rate(self.base_currency, to_currency)
        
        if rate:
            return round(amount * rate, 2)
        return None
    
    def get_rate(self, to_currency: str) -> Optional[float]:
        """Get exchange rate to target currency."""
        if to_currency == self.base_currency:
            return 1.0
        return self._rates.get(to_currency) or get_exchange_rate(self.base_currency, to_currency)
