"""Click entrypoint and the single orchestration function.

``cli.py`` is the only module that writes to stdout/stderr and the only module
that maps exceptions to process exit codes. It contains no analysis logic.
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone

import click

from . import __version__, config as cfg
from .data_fetcher import DataFetcher
from .errors import (
    ConfigError,
    DelistedWarning,
    SmcPromptError,
    exit_code_for,
)
from .output import deliver
from .structure_analyzer import analyze
from .template_renderer import build_payload, render

PROG = "smc-prompt"


@dataclass(frozen=True)
class RunResult:
    """Summary of a completed run (used for diagnostics/tests)."""

    prompt: str
    output_path: str | None
    warnings: tuple[str, ...]


def _ensure_utf8_streams() -> None:
    """Force UTF-8 on stdout/stderr.

    The template contains non-ASCII characters (e.g. ``⚠️``, em dashes). On
    Windows the console defaults to cp1252 and would raise
    ``UnicodeEncodeError`` mid-write, corrupting output. Reconfiguring keeps
    the rendered bytes exactly as specified.
    """

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", newline="")
        except (ValueError, OSError):  # pragma: no cover - defensive
            pass


def _warn(message: str) -> None:
    click.echo(f"[{PROG}] WARN: {message}", err=True)


def _error(message: str) -> None:
    click.echo(f"[{PROG}] ERROR: {message}", err=True)


def run(
    symbol: str,
    *,
    htf_candles: int,
    ltf_candles: int,
    swing_lookback: int,
    distance_reference: str,
    include_atr: bool,
    output_dir: str,
    base_urls: tuple[str, ...] | None = None,
    debug: bool = False,
) -> RunResult:
    """Chain fetch -> analyze -> render -> output. Raises on any failure."""

    config = cfg.build_config(
        symbol,
        htf_candles=htf_candles,
        ltf_candles=ltf_candles,
        swing_lookback=swing_lookback,
        distance_reference=distance_reference,
        include_atr=include_atr,
        output_dir=output_dir,
        base_urls=base_urls,
    )

    warnings: list[str] = []
    fetcher = DataFetcher(config)

    fetcher.validate_symbol()
    htf_raw = fetcher.fetch_klines(config.htf_interval, config.htf_fetch_limit)
    ltf_raw = fetcher.fetch_klines(config.ltf_interval, config.ltf_fetch_limit)
    current_price = fetcher.fetch_current_price()
    generated_at = datetime.now(timezone.utc)

    htf_result, htf_table, htf_stats = analyze(
        htf_raw,
        timeframe=config.htf_interval,
        requested=config.htf_candles,
        current_price=current_price,
        config=config,
    )
    ltf_result, ltf_table, ltf_stats = analyze(
        ltf_raw,
        timeframe=config.ltf_interval,
        requested=config.ltf_candles,
        current_price=current_price,
        config=config,
    )

    if htf_stats.was_reduced:
        warnings.append(
            f"Only {htf_stats.emitted_count} closed {config.htf_interval} candles "
            f"available (requested {htf_stats.requested_count}). "
            f"Reduced table to {htf_stats.emitted_count}."
        )
    if ltf_stats.was_reduced:
        warnings.append(
            f"Only {ltf_stats.emitted_count} closed {config.ltf_interval} candles "
            f"available (requested {ltf_stats.requested_count}). "
            f"Reduced table to {ltf_stats.emitted_count}."
        )

    for stats in (htf_stats, ltf_stats):
        if stats.zero_volume_streak >= config.delisted_zero_volume_streak:
            warnings.append(
                DelistedWarning(
                    config.symbol, stats.zero_volume_streak
                ).message()
            )

    for message in warnings:
        _warn(message)

    payload = build_payload(
        symbol=config.symbol,
        generated_at=generated_at,
        current_price=current_price,
        htf=htf_result,
        ltf=ltf_result,
        htf_candles=htf_table,
        ltf_candles=ltf_table,
        config=config,
    )
    rendered = render(payload, include_atr=config.include_atr)

    click.echo(rendered.text, nl=False)

    result = deliver(
        rendered.text,
        symbol=config.symbol,
        output_dir=config.output_dir,
        moment=generated_at,
    )
    output_path: str | None = None
    if result.used_fallback:
        output_path = str(result.fallback_path)
        _warn(
            f"Clipboard unavailable ({result.clipboard_error}). "
            f"Wrote prompt to {output_path} instead."
        )
    else:
        click.echo(f"[{PROG}] Prompt copied to clipboard.", err=True)

    return RunResult(rendered.text, output_path, tuple(warnings))


@click.command(
    name=PROG,
    context_settings={"help_option_names": ["-h", "--help"]},
    help=(
        "Generate a mechanical SMC/ICT [FAKTA] prompt payload from Binance "
        "public market data. No LLM calls, no reasoning, no trading."
    ),
)
@click.argument("symbol")
@click.option(
    "--htf-candles",
    type=int,
    default=cfg.DEFAULT_HTF_CANDLES,
    show_default=True,
    help="Number of CLOSED daily candles in the HTF raw table (>= 10).",
)
@click.option(
    "--ltf-candles",
    type=int,
    default=cfg.DEFAULT_LTF_CANDLES,
    show_default=True,
    help="Number of CLOSED hourly candles in the LTF raw table (>= 10).",
)
@click.option(
    "--swing-lookback",
    type=int,
    default=cfg.DEFAULT_SWING_LOOKBACK,
    show_default=True,
    help="Fractal window size N (odd, >= 3).",
)
@click.option(
    "--distance-reference",
    type=click.Choice(list(cfg.DISTANCE_REFERENCES)),
    default=cfg.DISTANCE_REFERENCE_NEAREST,
    show_default=True,
    help="Reference swing for distance: nearest-by-price or most-recent-by-time.",
)
@click.option(
    "--no-atr",
    "no_atr",
    is_flag=True,
    default=False,
    help="Omit the ATR(14) fields from the prompt.",
)
@click.option(
    "--base-url",
    "base_url",
    default=None,
    help=(
        "Override the Binance REST host. Falls back to "
        + ", ".join(cfg.DEFAULT_BASE_URLS)
        + " on connection errors / HTTP 451 / 403."
    ),
)
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False),
    default=cfg.DEFAULT_OUTPUT_DIR,
    show_default=True,
    help="Directory for the clipboard fallback file.",
)
@click.option("--debug", is_flag=True, default=False, help="Print stack traces.")
@click.version_option(version=__version__, prog_name=PROG)
def main(
    symbol: str,
    htf_candles: int,
    ltf_candles: int,
    swing_lookback: int,
    distance_reference: str,
    no_atr: bool,
    base_url: str | None,
    output_dir: str,
    debug: bool,
) -> None:
    """CLI entrypoint. Parses args, then delegates to :func:`run`."""

    _ensure_utf8_streams()

    base_urls = cfg.DEFAULT_BASE_URLS
    if base_url:
        remainder = tuple(
            host for host in cfg.DEFAULT_BASE_URLS if host.rstrip("/") != base_url.rstrip("/")
        )
        base_urls = (base_url,) + remainder

    try:
        run(
            symbol,
            htf_candles=htf_candles,
            ltf_candles=ltf_candles,
            swing_lookback=swing_lookback,
            distance_reference=distance_reference,
            include_atr=not no_atr,
            output_dir=output_dir,
            base_urls=base_urls,
            debug=debug,
        )
    except SmcPromptError as exc:
        _error(str(exc))
        if debug:
            traceback.print_exc()
        sys.exit(exit_code_for(exc))
    except Exception as exc:  # pragma: no cover - defensive
        _error(f"Unexpected failure: {exc}.")
        if debug:
            traceback.print_exc()
        sys.exit(exit_code_for(exc))
