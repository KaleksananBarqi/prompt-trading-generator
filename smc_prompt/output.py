"""Deliver the rendered prompt: clipboard first, file fallback second.

The clipboard path uses ``pyperclip``; on headless systems (no xclip/xsel) it
raises and we fall back to ``./output/<SYMBOL>_<timestamp>.md``. If both fail
the tool raises :class:`OutputError` (exit 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pyperclip

from . import config as cfg
from .errors import ClipboardUnavailable, OutputError


@dataclass(frozen=True)
class DeliveryResult:
    """Outcome of a delivery attempt."""

    copied_to_clipboard: bool
    fallback_path: Path | None
    clipboard_error: str | None

    @property
    def used_fallback(self) -> bool:
        return self.fallback_path is not None


def make_fallback_path(symbol: str, output_dir: str, moment: datetime) -> Path:
    """``<output_dir>/<SYMBOL>_<YYYYMMDDTHHMMSSZ>.md`` (spec §11)."""

    stamp = cfg.fmt_fallback_stamp(moment)
    return Path(output_dir) / f"{symbol.upper()}_{stamp}.md"


def copy_to_clipboard(text: str) -> None:
    """Copy ``text`` to the system clipboard.

    Raises :class:`ClipboardUnavailable` when ``pyperclip`` reports failure.
    """

    try:
        pyperclip.copy(text)
    except Exception as exc:  # pyperclip raises various platform exceptions
        raise ClipboardUnavailable(f"{type(exc).__name__}: {exc}") from exc


def write_fallback_file(path: Path, text: str) -> Path:
    """Write the prompt to ``path``, creating parent directories as needed."""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except OSError as exc:
        raise OutputError(
            f"Could not copy to clipboard or write fallback file ({exc})."
        ) from exc
    return path


def deliver(
    text: str,
    *,
    symbol: str,
    output_dir: str = cfg.DEFAULT_OUTPUT_DIR,
    moment: datetime | None = None,
) -> DeliveryResult:
    """Copy to clipboard; fall back to a file on a headless environment."""

    clipboard_error: str | None = None
    try:
        copy_to_clipboard(text)
        return DeliveryResult(True, None, None)
    except ClipboardUnavailable as exc:
        clipboard_error = str(exc)

    fallback = make_fallback_path(
        symbol, output_dir, moment or datetime.now(timezone.utc)
    )
    write_fallback_file(fallback, text)
    return DeliveryResult(False, fallback, clipboard_error)
