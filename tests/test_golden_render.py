"""Golden / byte-frozen render contract (Phase 4, #15).

Feeds the committed CSV fixtures through the offline source (#10) and asserts
the full rendered prompt hash and byte size. This pins the byte-identical
render contract without any network access.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from smc_prompt import cli
from smc_prompt.errors import NetworkError

from .conftest import GOLDEN_BYTES, GOLDEN_SHA256, HTF_CSV, LTF_CSV, MTF_CSV


def _run_offline(output_dir: Path) -> str:
    result = cli.run(
        "BTCUSDT",
        htf_candles=60,
        mtf_candles=120,
        ltf_candles=100,
        swing_lookback=5,
        distance_reference="nearest",
        include_atr=True,
        output_dir=str(output_dir),
        htf_interval="1d",
        mtf_interval="4h",
        ltf_interval="1h",
        input_csv=str(HTF_CSV),
        htf_file=str(HTF_CSV),
        mtf_file=str(MTF_CSV),
        ltf_file=str(LTF_CSV),
    )
    return result.prompt


def test_offline_render_matches_golden_hash(tmp_path: Path) -> None:
    text = _run_offline(tmp_path)
    raw = text.encode("utf-8")

    assert hashlib.sha256(raw).hexdigest() == GOLDEN_SHA256
    assert len(raw) == GOLDEN_BYTES


def test_offline_render_is_deterministic(tmp_path: Path) -> None:
    first = _run_offline(tmp_path / "a")
    second = _run_offline(tmp_path / "b")

    assert first == second
    assert hashlib.sha256(first.encode("utf-8")).hexdigest() == GOLDEN_SHA256


def test_offline_render_byte_contract(tmp_path: Path) -> None:
    text = _run_offline(tmp_path)

    assert "\r" not in text  # LF only
    assert text.endswith("\n") and not text.endswith("\n\n")  # one final LF
    assert "{{" not in text and "}}" not in text  # no unresolved placeholders
    # No trailing whitespace on any line.
    assert all(line == line.rstrip() for line in text.split("\n"))


def test_offline_mode_never_uses_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The offline path must not construct/reach the network fetcher."""

    def _boom(*args: object, **kwargs: object) -> None:
        raise NetworkError("network access is forbidden in offline mode")

    monkeypatch.setattr("smc_prompt.cli.DataFetcher", _boom)

    text = _run_offline(tmp_path)
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == GOLDEN_SHA256


def test_offline_output_file_written(tmp_path: Path) -> None:
    result = cli.run(
        "BTCUSDT",
        htf_candles=60,
        mtf_candles=120,
        ltf_candles=100,
        swing_lookback=5,
        distance_reference="nearest",
        include_atr=True,
        output_dir=str(tmp_path),
        input_csv=str(HTF_CSV),
        htf_file=str(HTF_CSV),
        mtf_file=str(MTF_CSV),
        ltf_file=str(LTF_CSV),
    )

    written = Path(result.output_path)
    assert written.is_file()
    assert written.read_text(encoding="utf-8") == result.prompt
    # Deterministic filename derived from max(close_time) + 1s.
    assert written.name == "BTCUSDT_20260720T000001Z.md"
