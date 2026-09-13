"""Shared fixtures/helpers for the smc-prompt test suite.

The suite is network-free: analysis tests use in-memory candles and the render
tests feed the offline CSV source (#10).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from smc_prompt import config as cfg
from smc_prompt.models import Candle, SwingPoint, SwingType

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
HTF_CSV = FIXTURE_DIR / "htf_daily.csv"
LTF_CSV = FIXTURE_DIR / "ltf_hourly.csv"

#: Byte-frozen hash of the offline render produced from the committed fixtures.
#: Regenerate with ``python tests/fixtures/generate_fixtures.py`` then see
#: ``tests/test_golden_render.py`` for how the value is asserted.
#:
#: Phase 5 regenerated this value: the template now also renders the
#: ATR-as-%-of-price line, the ATR-normalized swing distances and the
#: relative-volume / spike facts (see DESIGN_SPEC §4.9 / §8.2).
GOLDEN_SHA256 = "f5a47d8fac567316102faf9a8c19e0a3130d65bb4272b74b0b71f0ebd8bd30c7"
GOLDEN_BYTES = 18684

BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_candle(
    index: int,
    high: str | float,
    low: str | float,
    *,
    open_: str | float | None = None,
    close: str | float | None = None,
    volume: str | float = "1",
    is_closed: bool = True,
    base: datetime = BASE_TIME,
    step: timedelta = timedelta(hours=1),
) -> Candle:
    """Build a deterministic :class:`Candle` at ``base + index * step``."""

    open_time = base + index * step
    open_value = Decimal(str(open_ if open_ is not None else high))
    close_value = Decimal(str(close if close is not None else low))
    return Candle(
        open_time=open_time,
        open=open_value,
        high=Decimal(str(high)),
        low=Decimal(str(low)),
        close=close_value,
        volume=Decimal(str(volume)),
        close_time=open_time + step,
        is_closed=is_closed,
    )


def make_swing(
    index: int,
    price: str | float,
    swing_type: SwingType,
    *,
    base: datetime = BASE_TIME,
) -> SwingPoint:
    """Build a deterministic :class:`SwingPoint`."""

    return SwingPoint(
        index=index,
        open_time=base + timedelta(hours=index),
        price=Decimal(str(price)),
        type=swing_type,
    )


@pytest.fixture()
def config() -> cfg.Config:
    """Default config for a generic test symbol."""

    return cfg.build_config("TESTUSDT")


@pytest.fixture(autouse=True)
def _no_clipboard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralize clipboard access so tests stay headless and deterministic."""

    def _noop(text: str) -> None:
        return None

    monkeypatch.setattr("smc_prompt.output.copy_to_clipboard", _noop)
