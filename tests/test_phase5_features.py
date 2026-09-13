"""Tests for the Phase 5 additions (scope #6, #11, #16).

Covers the ATR-normalized distance / ATR-as-%-of-price facts (#6), the
post-render prompt-size guard (#11), and the usability items: ``--dry-run``,
the volume-derived signals, and the regex-based unresolved-placeholder guard.

All tests are network-free.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from click.testing import CliRunner

from smc_prompt import cli
from smc_prompt import config as cfg
from smc_prompt.errors import ConfigError, NetworkError
from smc_prompt.models import (
    Candle,
    StructureClass,
    SwingPoint,
    SwingType,
    TimeframeAnalysis,
)
from smc_prompt.structure_analyzer import compute_relative_volume
from smc_prompt.template_renderer import (
    _atr_normalized_distance,
    _atr_pct_of_price,
    _volume_relative,
    _volume_spike,
    build_payload,
    check_unresolved_placeholders,
    render,
)

from .conftest import HTF_CSV, LTF_CSV, make_candle, make_swing


# --------------------------------------------------------------------------
# #6 ATR-normalized distance + ATR as % of price
# --------------------------------------------------------------------------


def test_fmt_atr_distance_basic() -> None:
    assert cfg.fmt_atr_distance(Decimal("105"), Decimal("100"), Decimal("2")) == "x2.50"


def test_fmt_atr_distance_uses_absolute_value() -> None:
    # Direction is carried by the sibling percent field; this ratio is unsigned.
    assert cfg.fmt_atr_distance(Decimal("95"), Decimal("100"), Decimal("2")) == "x2.50"


def test_atr_normalized_distance_guards_zero_and_none() -> None:
    assert _atr_normalized_distance(Decimal("100"), Decimal("110"), Decimal("0")) == "n/a"
    assert _atr_normalized_distance(Decimal("100"), Decimal("110"), None) == "n/a"


def test_fmt_atr_pct_of_price() -> None:
    assert cfg.fmt_atr_pct(Decimal("1067.24"), Decimal("61791.35")) == "1.73% of price"


def test_atr_pct_of_price_guards_zero_atr_and_price() -> None:
    analysis = _analysis(atr=Decimal("0"))
    assert _atr_pct_of_price(analysis, Decimal("100")) == "n/a"
    analysis = _analysis(atr=Decimal("5"))
    assert _atr_pct_of_price(analysis, Decimal("0")) == "n/a"


# --------------------------------------------------------------------------
# #16 Volume-derived signals
# --------------------------------------------------------------------------


def _volume_series(volumes: list[str]) -> list[Candle]:
    return [
        make_candle(i, str(100 + i), str(90 + i), volume=v)
        for i, v in enumerate(volumes)
    ]


def test_relative_volume_last_over_mean() -> None:
    candles = _volume_series(["10", "10", "10", "10", "20"])

    metrics = compute_relative_volume(candles, period=20)

    assert metrics is not None
    assert metrics.relative == Decimal("1.6667")  # 20 / mean(12) quantized
    assert metrics.window == 5
    assert metrics.last == Decimal("20")


def test_relative_volume_spike_flag() -> None:
    candles = _volume_series(["10", "10", "10", "10", "100"])

    metrics = compute_relative_volume(candles, spike_mult=Decimal("1.5"))

    assert metrics is not None
    assert metrics.is_spike is True


def test_relative_volume_not_spike() -> None:
    candles = _volume_series(["10", "10", "10", "10", "10"])

    metrics = compute_relative_volume(candles, spike_mult=Decimal("1.5"))

    assert metrics is not None
    assert metrics.relative == Decimal("1.0000")
    assert metrics.is_spike is False


def test_relative_volume_zero_mean_is_safe() -> None:
    candles = _volume_series(["0", "0", "0"])

    metrics = compute_relative_volume(candles, period=20)

    assert metrics is not None
    assert metrics.relative == Decimal("0")
    assert metrics.is_spike is False


def test_relative_volume_needs_two_candles() -> None:
    assert compute_relative_volume(_volume_series(["10"])) is None
    assert compute_relative_volume([]) is None


def test_fmt_relative_volume_two_decimals() -> None:
    assert cfg.fmt_relative_volume(Decimal("1.4")) == "x1.40"
    assert cfg.fmt_relative_volume(Decimal("0.5")) == "x0.50"


def test_volume_renderers_handle_missing_metrics() -> None:
    analysis = _analysis()
    assert _volume_relative(analysis) == "n/a"
    assert _volume_spike(analysis) == "unknown"


# --------------------------------------------------------------------------
# #16 Regex unresolved-placeholder guard
# --------------------------------------------------------------------------


def test_check_unresolved_placeholders_flags_tags() -> None:
    assert check_unresolved_placeholders("a {{PAIR}} b") == ["PAIR"]
    assert check_unresolved_placeholders("a {{ PAIR }} b") == ["PAIR"]
    assert check_unresolved_placeholders("no tags here") == []


def test_check_unresolved_placeholders_allows_literal_braces() -> None:
    # A literal ``{{`` / ``}}`` in the body must NOT false-positive; only a tag
    # naming a declared placeholder is reported.
    text = "range {{100}} and literal }} and {{not_a_placeholder"
    assert check_unresolved_placeholders(text, {"PAIR"}) == []


def test_check_unresolved_placeholders_only_declared() -> None:
    # Only a tag naming a DECLARED placeholder is reported; an undeclared tag is
    # already rejected by StrictUndefined during the render itself.
    text = "{{PAIR}} {{UNKNOWN}}"
    assert check_unresolved_placeholders(text, {"PAIR"}) == ["PAIR"]


# --------------------------------------------------------------------------
# #11 Prompt-size guard
# --------------------------------------------------------------------------


def test_prompt_size_notes_warns_when_over_threshold() -> None:
    config = replace(cfg.build_config("TESTUSDT"), prompt_bytes_warn=10)

    notes = cli._prompt_size_notes("x" * 100, config)

    assert len(notes) == 1
    assert "100 bytes" in notes[0]
    assert "~25 tokens" in notes[0]


def test_prompt_size_notes_silent_under_threshold() -> None:
    config = replace(cfg.build_config("TESTUSDT"), prompt_bytes_warn=1000)

    assert cli._prompt_size_notes("x" * 10, config) == []


def test_prompt_size_hard_limit_raises_config_error() -> None:
    config = replace(cfg.build_config("TESTUSDT"), max_prompt_bytes=10)

    with pytest.raises(ConfigError, match="exceeding --max-prompt-bytes"):
        cli._prompt_size_notes("x" * 100, config)


def test_cli_max_prompt_bytes_offline_aborts(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli.main,
        [
            "BTCUSDT",
            "--input-csv",
            str(HTF_CSV),
            "--htf-file",
            str(HTF_CSV),
            "--ltf-file",
            str(LTF_CSV),
            "--output-dir",
            str(tmp_path),
            "--max-prompt-bytes",
            "10",
        ],
    )

    assert result.exit_code == 2
    assert "--max-prompt-bytes" in result.output
    assert not list(tmp_path.glob("BTCUSDT_*.md"))


# --------------------------------------------------------------------------
# #16 --dry-run
# --------------------------------------------------------------------------


def test_dry_run_does_not_fetch_or_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("dry-run must not construct a data source")

    monkeypatch.setattr("smc_prompt.cli.DataFetcher", _boom)
    monkeypatch.setattr("smc_prompt.cli.LocalCsvSource", _boom)

    result = cli.run(
        "BTCUSDT",
        htf_candles=60,
        ltf_candles=100,
        swing_lookback=5,
        distance_reference="nearest",
        include_atr=True,
        output_dir=str(tmp_path),
        dry_run=True,
    )

    assert result.dry_run is True
    assert result.prompt == ""
    assert result.output_path == ""
    assert not list(tmp_path.glob("BTCUSDT_*.md"))


def test_dry_run_cli_exits_zero_and_prints_settings(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli.main,
        ["BTCUSDT", "--dry-run", "--output-dir", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert "DRY RUN" in result.output
    assert "symbol=BTCUSDT" in result.output
    assert not list(tmp_path.glob("BTCUSDT_*.md"))


def test_dry_run_still_validates_symbol_argument() -> None:
    runner = CliRunner()
    result = runner.invoke(cli.main, ["", "--dry-run"])

    assert result.exit_code == 2


def test_run_has_no_debug_parameter() -> None:
    import inspect

    assert "debug" not in inspect.signature(cli.run).parameters


# --------------------------------------------------------------------------
# Placeholder contract: every declared required placeholder is populated
# --------------------------------------------------------------------------


def _offline_prompt(tmp_path: Path) -> str:
    return cli.run(
        "BTCUSDT",
        htf_candles=60,
        ltf_candles=100,
        swing_lookback=5,
        distance_reference="nearest",
        include_atr=True,
        output_dir=str(tmp_path),
        htf_interval="1d",
        ltf_interval="1h",
        input_csv=str(HTF_CSV),
        htf_file=str(HTF_CSV),
        ltf_file=str(LTF_CSV),
    ).prompt


def test_offline_prompt_renders_phase5_facts(tmp_path: Path) -> None:
    prompt = _offline_prompt(tmp_path)

    assert "- ATR ≈ " in prompt
    assert "% of price (ATR(14) HTF)" in prompt
    assert "×ATR(14))" in prompt  # ATR-normalized distance appended per swing
    assert "Volume candle terakhir" in prompt
    assert "spike:" in prompt
    # The ATR-normalized distance is rendered as a single x-prefixed ratio.
    assert "x" in prompt


def test_render_accepts_literal_braces_in_payload() -> None:
    from datetime import datetime, timezone

    from smc_prompt.models import ReferenceFacts

    config = cfg.build_config("TESTUSDT")
    htf = _analysis(atr=Decimal("100"), price=Decimal("1000"))
    ltf = _analysis(atr=Decimal("50"), price=Decimal("1000"))
    facts = ReferenceFacts(
        recent_high="1000.00 pada x (DI ATAS harga), status: untested",
        recent_low="900.00 pada x (DI BAWAH harga), status: untested",
        nearest_high="1000.00 pada x (DI ATAS harga), status: untested",
        nearest_low="900.00 pada x (DI BAWAH harga), status: untested",
        window_high="1000.00 pada x (DI ATAS harga), status: untested",
        window_low="900.00 pada x (DI BAWAH harga), status: untested",
    )
    htf = replace(htf, reference_facts=facts)
    ltf = replace(ltf, reference_facts=facts)

    payload = build_payload(
        symbol="TESTUSDT",
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        current_price=Decimal("1000"),
        htf=htf,
        ltf=ltf,
        htf_candles=_volume_series(["10", "10", "20"]),
        ltf_candles=_volume_series(["10", "10", "30"]),
        config=config,
    )
    # Injecting a literal ``{{`` into a value must not trip the guard (the guard
    # runs on the rendered text after substitution).
    payload["PAIR"] = "{{LITERAL}}"

    rendered = render(payload)

    assert "{{LITERAL}}" in rendered.text


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _dt():
    from datetime import datetime, timezone

    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _swing(index: int, price: str, swing_type: SwingType) -> SwingPoint:
    from datetime import timedelta

    return SwingPoint(
        index=index,
        open_time=_dt() + timedelta(hours=index),
        price=Decimal(price),
        type=swing_type,
    )


def _analysis(*, atr: Decimal | None = None, price: Decimal = Decimal("100")) -> TimeframeAnalysis:
    high = _swing(0, str(price), SwingType.HIGH)
    low = _swing(1, str(price - Decimal("10")), SwingType.LOW)
    return TimeframeAnalysis(
        timeframe="1h",
        structure_class=StructureClass.RANGING,
        swing_high=high,
        swing_low=low,
        dist_to_high=type("D", (), {"reference": high, "text": ""})(),
        dist_to_low=type("D", (), {"reference": low, "text": ""})(),
        atr=atr,
        candle_count=3,
        swings=(high, low),
    )
