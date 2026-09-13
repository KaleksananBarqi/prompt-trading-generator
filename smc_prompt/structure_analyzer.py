"""Pure, deterministic structure analysis (spec §7).

Implements, in order:
  1. :func:`prepare_series`       — drop the half-open candle, validate history
  2. :func:`compute_atr`          — ATR(14) with simple-mean smoothing
  3. :func:`detect_swings`        — N-bar Williams fractal + ATR separation filter
  4. :func:`classify_structure`   — mechanical Bullish / Bearish / Ranging
  5. :func:`compute_distance_metrics` — signed distance to reference swings

No randomness; no recursion; no lookahead beyond the fractal window. All
functions are network-free and unit-testable in isolation.

Important: analysis runs over the *full* closed series (which includes the
``context_buffer`` fetched beyond the emitted table), so swings near the left
edge of the emitted table remain detectable. Only the emitted table is
truncated to the requested row count.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

import pandas as pd

from . import config as cfg
from .errors import InsufficientDataError
from .models import (
    Candle,
    DistanceMetrics,
    StructureClass,
    SwingPoint,
    SwingType,
    TimeframeAnalysis,
)


@dataclass(frozen=True)
class SeriesStats:
    """Diagnostics returned alongside the prepared series."""

    closed_count: int
    emitted_count: int
    requested_count: int
    zero_volume_streak: int

    @property
    def was_reduced(self) -> bool:
        """True when fewer closed candles exist than were requested."""

        return self.emitted_count < self.requested_count


# --------------------------------------------------------------------------
# 1. Series preparation
# --------------------------------------------------------------------------


def minimum_required(swing_lookback: int, atr_period: int) -> int:
    """Minimum closed candles needed for ATR + at least one fractal window."""

    return max(cfg.MIN_CANDLES, atr_period + 1, swing_lookback)


def prepare_series(
    candles: Sequence[Candle],
    *,
    timeframe: str,
    requested: int,
    swing_lookback: int = cfg.DEFAULT_SWING_LOOKBACK,
    atr_period: int = cfg.DEFAULT_ATR_PERIOD,
) -> tuple[list[Candle], SeriesStats]:
    """Drop the half-open candle and enforce minimum history.

    Auto-reduces the emitted table length when fewer closed candles exist than
    requested (non-fatal; the caller emits a WARNING). Raises
    :class:`InsufficientDataError` when history is below the minimum needed
    for the fractal window + ATR.
    """

    closed = [candle for candle in candles if candle.is_closed]

    required_min = minimum_required(swing_lookback, atr_period)
    if len(closed) < required_min:
        raise InsufficientDataError(
            f"Not enough closed {timeframe} history to compute structure "
            f"(need >= {required_min}, got {len(closed)})."
        )

    streak = 0
    for candle in reversed(closed):
        if candle.volume == 0:
            streak += 1
        else:
            break

    emitted_count = min(requested, len(closed))
    stats = SeriesStats(
        closed_count=len(closed),
        emitted_count=emitted_count,
        requested_count=requested,
        zero_volume_streak=streak,
    )
    return closed, stats


def emitted_table(closed: Sequence[Candle], emitted_count: int) -> list[Candle]:
    """Return the last ``emitted_count`` closed candles (oldest -> newest)."""

    return list(closed)[-emitted_count:]


# --------------------------------------------------------------------------
# 2. ATR(14)
# --------------------------------------------------------------------------


def compute_atr(
    candles: Sequence[Candle], period: int = cfg.DEFAULT_ATR_PERIOD
) -> Decimal:
    """Classic True Range with simple-mean smoothing over the last ``period``."""

    if len(candles) < period + 1:
        raise InsufficientDataError(
            f"Not enough closed candles to compute ATR({period}) "
            f"(need >= {period + 1}, got {len(candles)})."
        )

    highs = pd.Series([float(c.high) for c in candles], dtype="float64")
    lows = pd.Series([float(c.low) for c in candles], dtype="float64")
    closes = pd.Series([float(c.close) for c in candles], dtype="float64")

    prev_close = closes.shift(1)
    tr = pd.concat(
        [
            (highs - lows),
            (highs - prev_close).abs(),
            (lows - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.iloc[1:].tail(period).mean()
    return Decimal(str(round(float(atr), 10)))


# --------------------------------------------------------------------------
# 3. Swing detection (N-bar Williams fractal)
# --------------------------------------------------------------------------


def detect_swings(
    candles: Sequence[Candle],
    *,
    n: int = cfg.DEFAULT_SWING_LOOKBACK,
    atr_value: Decimal | None = None,
    merge_mult: Decimal = cfg.DEFAULT_SWING_MERGE_ATR_MULT,
) -> list[SwingPoint]:
    """Detect fractal swings and apply the deterministic ATR separation filter."""

    if n % 2 == 0 or n < 3:
        raise ValueError("fractal window n must be an odd integer >= 3")

    half = (n - 1) // 2
    raw: list[SwingPoint] = []

    for i in range(half, len(candles) - half):
        center = candles[i]
        window = candles[i - half : i + half + 1]

        others = [c for j, c in enumerate(window) if j != half]
        if not others:
            continue

        is_high = center.high > max(c.high for c in others)
        is_low = center.low < min(c.low for c in others)

        if is_high:
            raw.append(
                SwingPoint(i, center.open_time, center.high, SwingType.HIGH)
            )
        elif is_low:
            raw.append(
                SwingPoint(i, center.open_time, center.low, SwingType.LOW)
            )

    if atr_value is None:
        return raw

    threshold = merge_mult * atr_value
    filtered: list[SwingPoint] = []
    for swing in raw:
        last_same_index: int | None = None
        for idx in range(len(filtered) - 1, -1, -1):
            if filtered[idx].type is swing.type:
                last_same_index = idx
                break

        if last_same_index is None:
            filtered.append(swing)
            continue

        last_same = filtered[last_same_index]
        if abs(swing.price - last_same.price) < threshold:
            if swing.is_more_extreme_than(last_same):
                filtered.pop(last_same_index)
                filtered.append(swing)
            # else: keep the prior, more significant swing
        else:
            filtered.append(swing)

    return filtered


# --------------------------------------------------------------------------
# 4. Structure classification (mechanical — never "bias")
# --------------------------------------------------------------------------


def classify_structure(
    swings: Sequence[SwingPoint], config: cfg.Config
) -> StructureClass:
    """Classify structure from the most recent swings (spec §4.4/§7.2)."""

    if len(swings) < config.structure_min_swings:
        return StructureClass.RANGING

    recent = list(swings)[-config.structure_last_swings :]
    highs = [s for s in recent if s.type is SwingType.HIGH]
    lows = [s for s in recent if s.type is SwingType.LOW]

    if len(highs) < 2 or len(lows) < 2:
        return StructureClass.RANGING

    hh = highs[-1].price > highs[-2].price
    hl = lows[-1].price > lows[-2].price
    lh = highs[-1].price < highs[-2].price
    ll = lows[-1].price < lows[-2].price

    if hh and hl:
        return StructureClass.BULLISH
    if lh and ll:
        return StructureClass.BEARISH
    return StructureClass.RANGING


# --------------------------------------------------------------------------
# 5. Distance metrics
# --------------------------------------------------------------------------


def select_reference(
    swings: Sequence[SwingPoint],
    swing_type: SwingType,
    current_price: Decimal,
    mode: str,
) -> SwingPoint:
    """Select the reference swing of ``swing_type``.

    ``nearest``      -> closest by absolute price distance to current price.
    ``most-recent``  -> latest by timestamp (spec §4.5 default reading).
    """

    candidates = [s for s in swings if s.type is swing_type]
    if not candidates:
        raise InsufficientDataError(
            f"No {swing_type.value} swing detected; cannot compute distance."
        )
    if mode == cfg.DISTANCE_REFERENCE_MOST_RECENT:
        return candidates[-1]
    return min(candidates, key=lambda s: (abs(current_price - s.price), -s.index))


def compute_distance_metrics(
    current_price: Decimal,
    swings: Sequence[SwingPoint],
    *,
    mode: str = cfg.DISTANCE_REFERENCE_NEAREST,
) -> tuple[SwingPoint, SwingPoint, DistanceMetrics, DistanceMetrics]:
    """Return (ref_high, ref_low, dist_to_high, dist_to_low)."""

    ref_high = select_reference(swings, SwingType.HIGH, current_price, mode)
    ref_low = select_reference(swings, SwingType.LOW, current_price, mode)
    dist_high = DistanceMetrics(
        ref_high, cfg.fmt_distance(current_price, ref_high.price)
    )
    dist_low = DistanceMetrics(
        ref_low, cfg.fmt_distance(current_price, ref_low.price)
    )
    return ref_high, ref_low, dist_high, dist_low


# --------------------------------------------------------------------------
# Orchestration for a single timeframe
# --------------------------------------------------------------------------


def analyze(
    candles: Sequence[Candle],
    *,
    timeframe: str,
    requested: int,
    current_price: Decimal,
    config: cfg.Config,
) -> tuple[TimeframeAnalysis, list[Candle], SeriesStats]:
    """Run the full Layer-A analysis pipeline for one timeframe.

    Returns the analysis, the emitted table candles, and the series stats.
    """

    closed, stats = prepare_series(
        candles,
        timeframe=timeframe,
        requested=requested,
        swing_lookback=config.swing_lookback,
        atr_period=config.atr_period,
    )

    # ATR is ALWAYS computed when enough history exists: it drives the
    # deterministic swing-separation filter (spec §4.2 / §7.1) and must not
    # depend on whether the user wants the ATR lines *displayed*.
    # ``--no-atr`` only suppresses the rendered ATR placeholders, which is
    # handled in ``template_renderer.build_payload``. Coupling it to the
    # computation here would silently change the reported swings/structure.
    atr: Decimal | None = None
    if len(closed) >= config.atr_period + 1:
        atr = compute_atr(closed, config.atr_period)

    swings = detect_swings(
        closed,
        n=config.swing_lookback,
        atr_value=atr,
        merge_mult=config.swing_merge_atr_mult,
    )
    if not swings:
        raise InsufficientDataError(
            f"No swings detected on {timeframe} series "
            f"({len(closed)} closed candles). Prompt not generated."
        )

    structure = classify_structure(swings, config)
    ref_high, ref_low, dist_high, dist_low = compute_distance_metrics(
        current_price, swings, mode=config.distance_reference
    )

    analysis = TimeframeAnalysis(
        timeframe=timeframe,
        structure_class=structure,
        swing_high=ref_high,
        swing_low=ref_low,
        dist_to_high=dist_high,
        dist_to_low=dist_low,
        atr=atr,
        candle_count=stats.emitted_count,
        swings=tuple(swings),
    )
    return analysis, emitted_table(closed, stats.emitted_count), stats
