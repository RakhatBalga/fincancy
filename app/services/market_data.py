"""Small async Yahoo Finance client for stock prices and USD/KZT."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


class MarketDataError(RuntimeError):
    """Raised when Yahoo Finance has no usable quote."""


@dataclass(frozen=True)
class MarketQuote:
    symbol: str
    price: float
    currency: str
    name: str


@dataclass(frozen=True)
class InstitutionTarget:
    firm: str
    target_price: float
    rating: str


@dataclass(frozen=True)
class AnalystForecast:
    symbol: str
    target_low: float
    target_mean: float
    target_high: float
    analyst_count: int
    recommendation: str | None
    institution_targets: tuple[InstitutionTarget, ...]


class YahooFinanceService:
    """Fetch Yahoo chart metadata and cache it briefly in process."""

    def __init__(self, cache_seconds: int = 300) -> None:
        self._cache_seconds = cache_seconds
        self._cache: dict[str, tuple[float, MarketQuote]] = {}
        self._forecast_cache: dict[str, tuple[float, AnalystForecast]] = {}

    async def quote(self, symbol: str) -> MarketQuote:
        normalized = symbol.strip().upper()
        cached = self._cache.get(normalized)
        now = time.monotonic()
        if cached is not None and now - cached[0] < self._cache_seconds:
            return cached[1]

        result = await asyncio.to_thread(self._fetch, normalized)
        self._cache[normalized] = (now, result)
        return result

    async def usd_kzt(self) -> float:
        return (await self.quote("USDKZT=X")).price

    async def forecasts(self, symbols: list[str]) -> dict[str, AnalystForecast]:
        """Return available analyst targets without failing the whole portfolio."""
        normalized = list(dict.fromkeys(symbol.strip().upper() for symbol in symbols))
        now = time.monotonic()
        result = {
            symbol: cached[1]
            for symbol in normalized
            if (cached := self._forecast_cache.get(symbol)) is not None
            and now - cached[0] < self._cache_seconds
        }
        missing = [symbol for symbol in normalized if symbol not in result]
        if missing:
            fetched = await asyncio.to_thread(self._fetch_forecasts, missing)
            for symbol, forecast in fetched.items():
                self._forecast_cache[symbol] = (now, forecast)
            result.update(fetched)
        return result

    @staticmethod
    def _fetch(symbol: str) -> MarketQuote:
        encoded = quote(symbol, safe="")
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
            "?interval=1d&range=1d"
        )
        request = Request(url, headers={"User-Agent": "FincancyBot/1.0"})
        try:
            with urlopen(request, timeout=8) as response:  # noqa: S310 - fixed host
                payload = json.load(response)
            result = payload["chart"]["result"][0]
            meta = result["meta"]
            price = float(meta["regularMarketPrice"])
            if price <= 0:
                raise ValueError("non-positive price")
            return MarketQuote(
                symbol=str(meta.get("symbol") or symbol).upper(),
                price=price,
                currency=str(meta.get("currency") or "USD").upper(),
                name=str(meta.get("shortName") or meta.get("longName") or symbol),
            )
        except (
            HTTPError,
            URLError,
            TimeoutError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ) as exc:
            raise MarketDataError(f"quote unavailable for {symbol}") from exc

    @classmethod
    def _fetch_forecasts(cls, symbols: list[str]) -> dict[str, AnalystForecast]:
        jar = CookieJar()
        opener = build_opener(HTTPCookieProcessor(jar))
        headers = {"User-Agent": "Mozilla/5.0 FincancyBot/1.0"}
        try:
            try:
                with opener.open(
                    Request("https://fc.yahoo.com", headers=headers), timeout=8
                ) as response:
                    response.read(1)
            except HTTPError as exc:
                if exc.code != 404:
                    raise
            crumb_request = Request(
                "https://query2.finance.yahoo.com/v1/test/getcrumb",
                headers=headers,
            )
            with opener.open(crumb_request, timeout=8) as response:
                crumb = response.read().decode().strip()
            if not crumb:
                raise ValueError("empty Yahoo crumb")
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            raise MarketDataError("analyst forecasts unavailable") from exc

        forecasts: dict[str, AnalystForecast] = {}
        for symbol in symbols:
            try:
                encoded = quote(symbol, safe="")
                query = urlencode(
                    {
                        "modules": (
                            "financialData,recommendationTrend,"
                            "upgradeDowngradeHistory"
                        ),
                        "crumb": crumb,
                    }
                )
                request = Request(
                    "https://query2.finance.yahoo.com/v10/finance/"
                    f"quoteSummary/{encoded}?{query}",
                    headers=headers,
                )
                with opener.open(request, timeout=8) as response:
                    payload = json.load(response)
                forecast = cls._parse_forecast(symbol, payload)
                if forecast is not None:
                    forecasts[symbol] = forecast
            except (
                HTTPError,
                URLError,
                TimeoutError,
                KeyError,
                IndexError,
                TypeError,
                ValueError,
            ):
                continue
        return forecasts

    @staticmethod
    def _parse_forecast(
        symbol: str, payload: dict[str, object]
    ) -> AnalystForecast | None:
        result = payload["quoteSummary"]["result"][0]  # type: ignore[index]
        financial = result.get("financialData") or {}

        def raw(name: str) -> float:
            value = financial.get(name)
            if isinstance(value, dict):
                value = value.get("raw")
            return float(value)

        low = raw("targetLowPrice")
        mean = raw("targetMeanPrice")
        high = raw("targetHighPrice")
        if low <= 0 or mean <= 0 or high <= 0:
            return None

        analyst_value = financial.get("numberOfAnalystOpinions", 0)
        if isinstance(analyst_value, dict):
            analyst_value = analyst_value.get("raw", 0)

        latest_by_firm: dict[str, InstitutionTarget] = {}
        history = (result.get("upgradeDowngradeHistory") or {}).get("history") or []
        for item in history:
            firm = str(item.get("firm") or "").strip()
            target = float(item.get("currentPriceTarget") or 0)
            if not firm or target <= 0 or firm in latest_by_firm:
                continue
            latest_by_firm[firm] = InstitutionTarget(
                firm=firm,
                target_price=target,
                rating=str(item.get("toGrade") or "").strip(),
            )
            if len(latest_by_firm) == 3:
                break

        recommendation = financial.get("recommendationKey")
        return AnalystForecast(
            symbol=symbol,
            target_low=low,
            target_mean=mean,
            target_high=high,
            analyst_count=int(analyst_value or 0),
            recommendation=str(recommendation) if recommendation else None,
            institution_targets=tuple(latest_by_firm.values()),
        )
