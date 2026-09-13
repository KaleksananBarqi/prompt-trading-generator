"""Binance public REST client (read-only market data only).

Endpoints (no API key, no signed/private routes, spec §4.1):
  * ``GET /api/v3/klines``        — HTF daily / LTF hourly OHLCV
  * ``GET /api/v3/ticker/price``  — current price
  * ``GET /api/v3/exchangeInfo``  — symbol validation

Includes retry-with-backoff (spec §9.4) and base-URL failover on connection
errors / HTTP 451 / HTTP 403.
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Sequence

import requests

from . import config as cfg
from .errors import NetworkError, SymbolNotFoundError
from .models import Candle

#: HTTP statuses that mean "this host is blocked for us" -> try the next host.
_HOST_BLOCK_STATUSES: frozenset[int] = frozenset({403, 451})

#: HTTP statuses that mean the request itself is invalid -> no retry.
_FATAL_CLIENT_STATUSES: frozenset[int] = frozenset({400, 404})

#: HTTP statuses worth retrying on the same host.
_RETRY_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


def _ms_to_utc(ms: int | float | str) -> datetime:
    """Convert a Binance millisecond timestamp to an aware UTC datetime."""

    return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc)


class DataFetcher:
    """Fetches and normalizes Binance market data for one symbol."""

    def __init__(
        self,
        config: cfg.Config,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[], float] = random.random,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._session = session or requests.Session()
        self._sleep = sleep
        self._rand = rand
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._active_base_url: str | None = None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _jitter(self) -> float:
        """Small +/-250ms jitter; affects network timing only, not output."""

        return (self._rand() - 0.5) * 0.5

    def _backoff(self, attempt: int) -> float:
        return self._config.retry_backoff_base * (
            self._config.retry_backoff_factor ** attempt
        ) + self._jitter()

    def _request_json(self, path: str, params: dict[str, Any]) -> Any:
        """GET ``path`` with retry/backoff and base-URL failover.

        Raises :class:`SymbolNotFoundError` for invalid-symbol responses and
        :class:`NetworkError` once every host/attempt pair is exhausted.
        """

        hosts: Sequence[str] = self._config.base_urls
        last_reason = "unknown error"
        attempts_total = 0

        for host in hosts:
            url = f"{host}{path}"
            for attempt in range(self._config.retry_max):
                attempts_total += 1
                try:
                    response = self._session.get(
                        url,
                        params=params,
                        timeout=self._config.request_timeout,
                        headers={"User-Agent": "smc-prompt/0.1"},
                    )
                except (requests.ConnectionError, requests.Timeout) as exc:
                    last_reason = f"{type(exc).__name__}: {exc}"
                    if attempt < self._config.retry_max - 1:
                        self._sleep(self._backoff(attempt))
                        continue
                    break

                status = response.status_code

                if status in _HOST_BLOCK_STATUSES:
                    # Geo-block / forbidden for this host: stop retrying it and
                    # fail over to the next approved base URL.
                    last_reason = f"HTTP {status} from {host}"
                    break

                if status in _FATAL_CLIENT_STATUSES:
                    # 400 commonly means "symbol does not exist" for klines.
                    raise SymbolNotFoundError(
                        f"Symbol '{self._config.symbol}' is not listed on "
                        f"Binance Spot. Check the spelling (e.g. BTCUSDT)."
                    )

                if status in _RETRY_STATUSES:
                    last_reason = f"HTTP {status} from {host}"
                    if attempt < self._config.retry_max - 1:
                        self._sleep(self._backoff(attempt))
                        continue
                    break

                if status >= 400:
                    last_reason = f"HTTP {status} from {host}"
                    break

                try:
                    payload = response.json()
                except ValueError as exc:
                    last_reason = f"invalid JSON from {host}: {exc}"
                    if attempt < self._config.retry_max - 1:
                        self._sleep(self._backoff(attempt))
                        continue
                    break

                self._active_base_url = host
                return payload

        raise NetworkError(
            f"Binance API unreachable after {attempts_total} attempts "
            f"({last_reason}). No prompt generated."
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def active_base_url(self) -> str | None:
        """Host that served the last successful request."""

        return self._active_base_url

    def validate_symbol(self) -> dict[str, Any]:
        """Validate the symbol against ``exchangeInfo`` (spec §9.3)."""

        payload = self._request_json(
            cfg.EXCHANGE_INFO_PATH, {"symbol": self._config.symbol}
        )
        symbols = payload.get("symbols") if isinstance(payload, dict) else None
        if not symbols:
            raise SymbolNotFoundError(
                f"Symbol '{self._config.symbol}' is not listed on Binance "
                f"Spot. Check the spelling (e.g. BTCUSDT)."
            )
        entry = symbols[0]
        if entry.get("status") not in (None, "TRADING"):
            # A listed but non-trading symbol is still surfaced to the user;
            # the zero-volume heuristic in the analyzer reports it as warning.
            pass
        return entry

    def fetch_klines(
        self, interval: str, limit: int, *, symbol: str | None = None
    ) -> list[Candle]:
        """Fetch ``limit`` klines for ``interval`` and normalize to Candle."""

        active_symbol = symbol or self._config.symbol
        raw = self._request_json(
            cfg.KLINES_PATH,
            {"symbol": active_symbol, "interval": interval, "limit": limit},
        )
        if not isinstance(raw, list):
            raise NetworkError(
                f"Unexpected klines payload for {active_symbol} "
                f"{interval}. No prompt generated."
            )

        now = self._now()
        candles: list[Candle] = []
        for row in raw:
            close_time = _ms_to_utc(row[6])
            is_closed = now >= close_time + timedelta(seconds=1)
            candles.append(
                Candle(
                    open_time=_ms_to_utc(row[0]),
                    open=Decimal(str(row[1])),
                    high=Decimal(str(row[2])),
                    low=Decimal(str(row[3])),
                    close=Decimal(str(row[4])),
                    volume=Decimal(str(row[5])),
                    close_time=close_time,
                    is_closed=is_closed,
                )
            )
        return candles

    def fetch_current_price(self) -> Decimal:
        """Fetch the current price via ticker/price, falling back to kline close.

        Uses the last *closed* 1h candle close as fallback; the half-open
        candle is never used for anything else (spec §4.3).
        """

        try:
            payload = self._request_json(
                cfg.TICKER_PRICE_PATH, {"symbol": self._config.symbol}
            )
            price = payload.get("price") if isinstance(payload, dict) else None
            if price is None:
                raise NetworkError("ticker/price returned no price field.")
            return Decimal(str(price))
        except (NetworkError, SymbolNotFoundError):
            candles = self.fetch_klines(
                self._config.ltf_interval, cfg.MIN_CANDLES
            )
            closed = [c for c in candles if c.is_closed]
            if not closed:
                raise NetworkError(
                    "Current price unavailable: ticker endpoint failed and no "
                    "closed candle exists to derive a fallback price."
                )
            return closed[-1].close
