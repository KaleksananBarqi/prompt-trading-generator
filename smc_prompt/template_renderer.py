"""Build the placeholder map and render the byte-frozen Jinja2 template.

Byte-stability contract (spec §8.1):
  * UTF-8, LF line endings only, no trailing whitespace, exactly one final ``\\n``.
  * Values are pre-formatted strings; the template uses plain substitution.
  * Missing/empty placeholders are a hard error — a prompt is never emitted
    with an empty field or an ``N/A`` placeholder.
"""

from __future__ import annotations

from decimal import Decimal
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Sequence

from jinja2 import Environment, StrictUndefined, TemplateError

from . import config as cfg
from .errors import SmcPromptError
from .models import (
    Candle,
    OPTIONAL_PLACEHOLDERS,
    REQUIRED_PLACEHOLDERS,
    RenderedPrompt,
    TimeframeAnalysis,
)

TEMPLATE_PACKAGE = "smc_prompt"
TEMPLATE_DIR = "templates"
TEMPLATE_NAME = "prompt_template.j2"

#: Lines in the template that carry ATR and are removed under ``--no-atr``.
_ATR_TEMPLATE_LINES = (
    "- ATR(14): {{HTF_ATR14}} (opsional)",
    "- ATR(14): {{LTF_ATR14}} (opsional)",
)


def load_template_text() -> str:
    """Read the template asset (works from source tree and installed wheel)."""

    try:
        asset = resources.files(TEMPLATE_PACKAGE).joinpath(
            TEMPLATE_DIR, TEMPLATE_NAME
        )
        return asset.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as exc:  # pragma: no cover
        raise SmcPromptError(f"Prompt template asset not found ({exc}).")


def _template_source(include_atr: bool) -> str:
    text = load_template_text()
    if not include_atr:
        lines = [line for line in text.split("\n") if line not in _ATR_TEMPLATE_LINES]
        text = "\n".join(lines)
    return text


def render_csv_table(candles: Sequence[Candle], *, htf: bool) -> str:
    """Render the raw candle CSV block (no header, no index column)."""

    rows: list[str] = []
    for candle in candles:
        stamp = (
            cfg.fmt_htf_date(candle.open_time)
            if htf
            else cfg.fmt_ltf_datetime(candle.open_time)
        )
        rows.append(
            ",".join(
                [
                    stamp,
                    cfg.fmt_price(candle.open),
                    cfg.fmt_price(candle.high),
                    cfg.fmt_price(candle.low),
                    cfg.fmt_price(candle.close),
                ]
            )
        )
    return "\n".join(rows)


def build_payload(
    *,
    symbol: str,
    generated_at: datetime,
    current_price: Decimal,
    htf: TimeframeAnalysis,
    ltf: TimeframeAnalysis,
    htf_candles: Sequence[Candle],
    ltf_candles: Sequence[Candle],
    config: cfg.Config,
) -> dict[str, str]:
    """Build the complete placeholder map (spec §10)."""

    payload: dict[str, str] = {
        "PAIR": symbol.upper(),
        "GENERATED_AT_UTC": cfg.fmt_generated_at(generated_at),
        "CURRENT_PRICE": cfg.fmt_price(current_price),
        "HTF_STRUCTURE_CLASS": htf.structure_class.value,
        "HTF_SWING_HIGH": cfg.fmt_price(htf.swing_high.price),
        "HTF_SWING_HIGH_DATE": cfg.fmt_htf_date(htf.swing_high.open_time),
        "HTF_DIST_TO_HIGH": htf.dist_to_high.text,
        "HTF_SWING_LOW": cfg.fmt_price(htf.swing_low.price),
        "HTF_SWING_LOW_DATE": cfg.fmt_htf_date(htf.swing_low.open_time),
        "HTF_DIST_TO_LOW": htf.dist_to_low.text,
        "HTF_CANDLE_COUNT": str(htf.candle_count),
        "HTF_CANDLE_TABLE_CSV": render_csv_table(htf_candles, htf=True),
        "LTF_STRUCTURE_CLASS": ltf.structure_class.value,
        "LTF_SWING_HIGH": cfg.fmt_price(ltf.swing_high.price),
        "LTF_SWING_HIGH_DATE": cfg.fmt_ltf_datetime(ltf.swing_high.open_time),
        "LTF_DIST_TO_HIGH": ltf.dist_to_high.text,
        "LTF_SWING_LOW": cfg.fmt_price(ltf.swing_low.price),
        "LTF_SWING_LOW_DATE": cfg.fmt_ltf_datetime(ltf.swing_low.open_time),
        "LTF_DIST_TO_LOW": ltf.dist_to_low.text,
        "LTF_CANDLE_COUNT": str(ltf.candle_count),
        "LTF_CANDLE_TABLE_CSV": render_csv_table(ltf_candles, htf=False),
    }

    if config.include_atr:
        if htf.atr is None or ltf.atr is None:
            raise SmcPromptError(
                "ATR requested but not computable; aborting before render."
            )
        payload["HTF_ATR14"] = cfg.fmt_atr(htf.atr)
        payload["LTF_ATR14"] = cfg.fmt_atr(ltf.atr)

    _validate_payload(payload, include_atr=config.include_atr)
    return payload


def _validate_payload(payload: dict[str, str], *, include_atr: bool) -> None:
    required = list(REQUIRED_PLACEHOLDERS)
    if include_atr:
        required.extend(OPTIONAL_PLACEHOLDERS)

    missing = [key for key in required if key not in payload]
    if missing:
        raise SmcPromptError(
            "Missing placeholder values: " + ", ".join(missing) + "."
        )

    empty = [key for key in required if not str(payload[key]).strip()]
    if empty:
        raise SmcPromptError(
            "Empty placeholder values: " + ", ".join(empty) + "."
        )


def _tidy(text: str) -> str:
    """Normalize to byte-stable output: LF only, no trailing ws, one final LF."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def render(payload: dict[str, str], *, include_atr: bool = True) -> RenderedPrompt:
    """Render the template with strict undefined handling."""

    env = Environment(
        undefined=StrictUndefined,
        keep_trailing_newline=False,
        autoescape=False,
        trim_blocks=False,
        lstrip_blocks=False,
        newline_sequence="\n",
    )
    try:
        template = env.from_string(_template_source(include_atr))
        text = template.render(**payload)
    except TemplateError as exc:
        raise SmcPromptError(f"Template rendering failed: {exc}.")

    if "{{" in text or "}}" in text:
        raise SmcPromptError(
            "Template rendering left an unresolved placeholder; aborting."
        )

    return RenderedPrompt(text=_tidy(text), placeholders=dict(payload))
