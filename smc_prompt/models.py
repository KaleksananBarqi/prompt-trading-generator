"""Typed data contracts for smc-prompt (spec §5.1).

Every structure crossing a module boundary is an explicit dataclass so the
two-layer payload contract is independently testable. Prices are ``Decimal``
to keep rendering deterministic and byte-stable.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


class SwingType(str, enum.Enum):
    """Type of a detected swing point."""

    HIGH = "HIGH"
    LOW = "LOW"


class StructureClass(str, enum.Enum):
    """Mechanical structure classification (never called "bias")."""

    BULLISH = "Bullish"
    BEARISH = "Bearish"
    RANGING = "Ranging/Mixed"


@dataclass(frozen=True)
class Candle:
    """A single OHLCV candle.

    ``open_time`` / ``close_time`` are timezone-aware UTC datetimes.
    ``is_closed`` is advisory metadata computed by the fetcher; the analyzer
    operates on series from which the half-open candle has already been
    removed.
    """

    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    close_time: datetime
    is_closed: bool = True


@dataclass(frozen=True)
class SwingPoint:
    """A detected fractal swing high or low."""

    index: int
    open_time: datetime
    price: Decimal
    type: SwingType

    def is_more_extreme_than(self, other: "SwingPoint") -> bool:
        """Return True if this swing is more extreme than ``other``."""

        if self.type is SwingType.HIGH:
            return self.price > other.price
        return self.price < other.price


@dataclass(frozen=True)
class DistanceMetrics:
    """Signed distance from current price to a reference swing."""

    reference: SwingPoint
    text: str


@dataclass(frozen=True)
class TimeframeAnalysis:
    """Complete Layer-A analysis result for one timeframe."""

    timeframe: str
    structure_class: StructureClass
    swing_high: SwingPoint
    swing_low: SwingPoint
    dist_to_high: DistanceMetrics
    dist_to_low: DistanceMetrics
    atr: Decimal | None
    candle_count: int
    swings: tuple[SwingPoint, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PayloadSection:
    """A rendered section of the prompt (used for diagnostics/tests)."""

    name: str
    text: str


@dataclass(frozen=True)
class RenderedPrompt:
    """The final prompt plus the placeholder map that produced it."""

    text: str
    placeholders: dict[str, str]


#: The complete set of required template placeholders (spec §10). A rendered
#: prompt is only produced when every one of these is present and non-empty.
REQUIRED_PLACEHOLDERS: tuple[str, ...] = (
    "PAIR",
    "GENERATED_AT_UTC",
    "CURRENT_PRICE",
    "HTF_STRUCTURE_CLASS",
    "HTF_SWING_HIGH",
    "HTF_SWING_HIGH_DATE",
    "HTF_DIST_TO_HIGH",
    "HTF_SWING_LOW",
    "HTF_SWING_LOW_DATE",
    "HTF_DIST_TO_LOW",
    "HTF_CANDLE_COUNT",
    "HTF_CANDLE_TABLE_CSV",
    "LTF_STRUCTURE_CLASS",
    "LTF_SWING_HIGH",
    "LTF_SWING_HIGH_DATE",
    "LTF_DIST_TO_HIGH",
    "LTF_SWING_LOW",
    "LTF_SWING_LOW_DATE",
    "LTF_DIST_TO_LOW",
    "LTF_CANDLE_COUNT",
    "LTF_CANDLE_TABLE_CSV",
)

#: Placeholders that are dropped entirely when ATR is disabled.
OPTIONAL_PLACEHOLDERS: tuple[str, ...] = ("HTF_ATR14", "LTF_ATR14")
