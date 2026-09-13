"""Deterministic fixture generator for the offline CSV test suite.

Run with ``python tests/fixtures/generate_fixtures.py`` to (re)create the three
committed CSV fixtures:

    tests/fixtures/htf_daily.csv   (HTF, 1d, 80 rows)
    tests/fixtures/mtf_4h.csv      (MTF, 4h, 120 rows)
    tests/fixtures/ltf_hourly.csv  (LTF, 1h, 150 rows)

The generator is fully deterministic (a fixed ``random.Random`` seed plus a
closed-form sine/trend base) so the golden render hash in
``tests/test_golden_render.py`` is reproducible on any machine. The committed
CSVs are what the suite actually consumes; this script exists so the fixtures
can be regenerated and reviewed as a normal diff.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent

HEADER = "open_time,open,high,low,close,volume"


def _fmt(value: float) -> str:
    return f"{value:.2f}"


def _volume(value: float) -> str:
    return f"{value:.8f}"


def generate(
    path: Path,
    *,
    start: datetime,
    step: timedelta,
    count: int,
    base: float,
    seed: int,
) -> None:
    """Write a mean-reverting deterministic OHLCV series to ``path``."""

    rnd = random.Random(seed)
    lines = [HEADER]
    moment = start
    previous_close = base
    for i in range(count):
        # Mean-reverting wave around ``base`` -> repeatable swings + gaps.
        anchor = base * (
            1.0
            + 0.080 * math.sin(i / 9.0)
            + 0.028 * math.sin(i / 3.5)
        )
        open_ = previous_close
        close = anchor + rnd.uniform(-base * 0.004, base * 0.004)
        high = max(open_, close) * (1.0 + rnd.uniform(0.0012, 0.0055))
        low = min(open_, close) * (1.0 - rnd.uniform(0.0012, 0.0055))
        volume = rnd.uniform(500.0, 2500.0)

        lines.append(
            ",".join(
                [
                    moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    _fmt(open_),
                    _fmt(high),
                    _fmt(low),
                    _fmt(close),
                    _volume(volume),
                ]
            )
        )
        previous_close = close
        moment += step

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    generate(
        FIXTURE_DIR / "htf_daily.csv",
        start=datetime(2026, 5, 1, tzinfo=timezone.utc),
        step=timedelta(days=1),
        count=80,
        base=64000.0,
        seed=20260501,
    )
    generate(
        FIXTURE_DIR / "mtf_4h.csv",
        start=datetime(2026, 6, 30, tzinfo=timezone.utc),
        step=timedelta(hours=4),
        count=120,
        base=66000.0,
        seed=20260630,
    )
    generate(
        FIXTURE_DIR / "ltf_hourly.csv",
        start=datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc),
        step=timedelta(hours=1),
        count=150,
        base=68000.0,
        seed=20260620,
    )


if __name__ == "__main__":
    main()
