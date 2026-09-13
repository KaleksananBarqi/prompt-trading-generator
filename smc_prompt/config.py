"""Immutable defaults, configuration dataclass and byte-stable formatting rules.

Values come from ``docs/DESIGN_SPEC.md`` §11 (defaults) and §8.1 (formatting
primitives). This module is a leaf: it must not import any other smc_prompt
module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence

from .errors import ConfigError

# --------------------------------------------------------------------------
# Intervals / endpoint paths (no API key, read-only public market data only)
# --------------------------------------------------------------------------

HTF_INTERVAL: str = "1d"
LTF_INTERVAL: str = "1h"

KLINES_PATH: str = "/api/v3/klines"
TICKER_PRICE_PATH: str = "/api/v3/ticker/price"
EXCHANGE_INFO_PATH: str = "/api/v3/exchangeInfo"

# --------------------------------------------------------------------------
# Base URL fallback list (orchestrator decision, see brief §3 notes)
# --------------------------------------------------------------------------

#: Approved public hosts, tried in order. Fail over on connection errors,
#: HTTP 451 (geo-block) and HTTP 403. Overridable constant.
DEFAULT_BASE_URLS: tuple[str, ...] = (
    "https://api.binance.com",
    "https://data-api.binance.vision",
)

# --------------------------------------------------------------------------
# Numeric defaults
# --------------------------------------------------------------------------

DEFAULT_HTF_CANDLES: int = 60
DEFAULT_LTF_CANDLES: int = 100
DEFAULT_SWING_LOOKBACK: int = 5
DEFAULT_SWING_MERGE_ATR_MULT: Decimal = Decimal("0.5")
DEFAULT_ATR_PERIOD: int = 14
DEFAULT_STRUCTURE_MIN_SWINGS: int = 4
DEFAULT_STRUCTURE_LAST_SWINGS: int = 6
DEFAULT_CONTEXT_BUFFER: int = 50
FETCH_LIMIT_MAX: int = 1000
DEFAULT_REQUEST_TIMEOUT: float = 10.0
DEFAULT_RETRY_MAX: int = 3
DEFAULT_RETRY_BACKOFF_BASE: float = 1.0
DEFAULT_RETRY_BACKOFF_FACTOR: float = 2.0
DEFAULT_OUTPUT_DIR: str = "output"
DEFAULT_DELISTED_ZERO_VOLUME_STREAK: int = 3

MIN_CANDLES: int = 10
MIN_SWING_LOOKBACK: int = 3

#: Valid values for ``--distance-reference``.
DISTANCE_REFERENCE_NEAREST: str = "nearest"
DISTANCE_REFERENCE_MOST_RECENT: str = "most-recent"
DISTANCE_REFERENCES: tuple[str, ...] = (
    DISTANCE_REFERENCE_NEAREST,
    DISTANCE_REFERENCE_MOST_RECENT,
)

# --------------------------------------------------------------------------
# Formatting primitives (byte-stable, spec §8.1)
# --------------------------------------------------------------------------


def price_decimals(value: Decimal | float | int | str) -> int:
    """Decimals chosen by magnitude: >=1000 -> 2dp, >=1 -> 4dp, else 8dp."""

    magnitude = abs(Decimal(str(value)))
    if magnitude >= Decimal("1000"):
        return 2
    if magnitude >= Decimal("1"):
        return 4
    return 8


def fmt_price(value: Decimal | float | int | str) -> str:
    """Render a price using the magnitude-based decimal rule."""

    dec = Decimal(str(value))
    return f"{dec:.{price_decimals(dec)}f}"


def fmt_atr(value: Decimal | float | int | str) -> str:
    """Render ATR as a volatility scale figure (spec §12 oracle: ``145.00``).

    The frozen rendered example shows ``1850.00`` and ``145.00`` — 2 dp for
    unit-scale values — whereas magnitude-based ``fmt_price`` would render 145
    as ``145.0000``. Sub-unit values keep their magnitude-based precision so
    low-priced pairs do not collapse to ``0.00``.
    """

    dec = Decimal(str(value))
    dp = 2 if abs(dec) >= Decimal("1") else price_decimals(dec)
    return f"{dec:.{dp}f}"


def fmt_distance(current: Decimal, reference: Decimal) -> str:
    """Render signed distance as ``{sign}{pct:.2f}% ({sign}{abs})``.

    The absolute part uses the decimal precision implied by the *reference*
    price magnitude (spec §8.2 example: ``-0.52% (-330.00)`` from a 63450.00
    swing high, even though 330 itself is < 1000).
    """

    abs_val = Decimal(current) - Decimal(reference)
    pct = (abs_val / Decimal(reference)) * Decimal("100")
    sign = "+" if abs_val >= 0 else "-"
    dp = price_decimals(reference)
    return f"{sign}{abs(pct):.2f}% ({sign}{abs(abs_val):.{dp}f})"


def fmt_htf_date(moment: datetime) -> str:
    """HTF date format: ``%Y-%m-%d`` (UTC)."""

    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d")


def fmt_ltf_datetime(moment: datetime) -> str:
    """LTF datetime format: ``%Y-%m-%d %H:%M`` (UTC)."""

    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")


def fmt_generated_at(moment: datetime) -> str:
    """``GENERATED_AT_UTC`` format: ``%Y-%m-%dT%H:%M:%SZ``."""

    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_fallback_stamp(moment: datetime) -> str:
    """Fallback filename stamp: ``%Y%m%dT%H%M%SZ``."""

    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# --------------------------------------------------------------------------
# Configuration dataclass
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    """Fully validated, immutable run configuration."""

    symbol: str
    htf_candles: int = DEFAULT_HTF_CANDLES
    ltf_candles: int = DEFAULT_LTF_CANDLES
    swing_lookback: int = DEFAULT_SWING_LOOKBACK

    distance_reference: str = DISTANCE_REFERENCE_NEAREST
    include_atr: bool = True

    htf_interval: str = HTF_INTERVAL
    ltf_interval: str = LTF_INTERVAL
    swing_merge_atr_mult: Decimal = DEFAULT_SWING_MERGE_ATR_MULT
    atr_period: int = DEFAULT_ATR_PERIOD
    structure_min_swings: int = DEFAULT_STRUCTURE_MIN_SWINGS
    structure_last_swings: int = DEFAULT_STRUCTURE_LAST_SWINGS
    context_buffer: int = DEFAULT_CONTEXT_BUFFER
    fetch_limit_max: int = FETCH_LIMIT_MAX
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    retry_max: int = DEFAULT_RETRY_MAX
    retry_backoff_base: float = DEFAULT_RETRY_BACKOFF_BASE
    retry_backoff_factor: float = DEFAULT_RETRY_BACKOFF_FACTOR
    output_dir: str = DEFAULT_OUTPUT_DIR
    delisted_zero_volume_streak: int = DEFAULT_DELISTED_ZERO_VOLUME_STREAK

    base_urls: tuple[str, ...] = field(default=DEFAULT_BASE_URLS)

    @property
    def htf_fetch_limit(self) -> int:
        """Candles to request for HTF (table size + context buffer, capped)."""

        return min(self.htf_candles + self.context_buffer, self.fetch_limit_max)

    @property
    def ltf_fetch_limit(self) -> int:
        """Candles to request for LTF (table size + context buffer, capped)."""

        return min(self.ltf_candles + self.context_buffer, self.fetch_limit_max)


def build_config(
    symbol: str,
    *,
    htf_candles: int = DEFAULT_HTF_CANDLES,
    ltf_candles: int = DEFAULT_LTF_CANDLES,
    swing_lookback: int = DEFAULT_SWING_LOOKBACK,
    distance_reference: str = DISTANCE_REFERENCE_NEAREST,
    include_atr: bool = True,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    base_urls: Sequence[str] | None = None,
) -> Config:
    """Validate raw CLI arguments and build an immutable :class:`Config`.

    Raises :class:`~smc_prompt.errors.ConfigError` on any invalid input
    (spec §9.3, exit code 2).
    """

    normalized_symbol = (symbol or "").strip().upper()
    if not normalized_symbol:
        raise ConfigError("SYMBOL is required. Example: smc-prompt BTCUSDT.")

    if not isinstance(swing_lookback, int) or swing_lookback < MIN_SWING_LOOKBACK:
        raise ConfigError("--swing-lookback must be an odd integer >= 3.")
    if swing_lookback % 2 == 0:
        raise ConfigError("--swing-lookback must be an odd integer >= 3.")

    if not isinstance(htf_candles, int) or htf_candles < MIN_CANDLES:
        raise ConfigError("--htf-candles must be an integer >= 10.")
    if not isinstance(ltf_candles, int) or ltf_candles < MIN_CANDLES:
        raise ConfigError("--ltf-candles must be an integer >= 10.")

    if distance_reference not in DISTANCE_REFERENCES:
        raise ConfigError(
            "--distance-reference must be one of: "
            + ", ".join(DISTANCE_REFERENCES)
            + "."
        )

    hosts = tuple(base_urls) if base_urls else DEFAULT_BASE_URLS
    hosts = tuple(host.rstrip("/") for host in hosts if host and host.strip())
    if not hosts:
        raise ConfigError("At least one Binance base URL must be provided.")

    return Config(
        symbol=normalized_symbol,
        htf_candles=htf_candles,
        ltf_candles=ltf_candles,
        swing_lookback=swing_lookback,
        distance_reference=distance_reference,
        include_atr=include_atr,
        output_dir=output_dir,
        base_urls=hosts,
    )
