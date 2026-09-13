"""Exception hierarchy and exit-code mapping for smc-prompt.

Exit codes map 1:1 to exception types (see ``docs/DESIGN_SPEC.md`` §9).

    SmcPromptError            base, exit 1
    ├── ConfigError           exit 2
    ├── SymbolNotFoundError   exit 3
    ├── NetworkError          exit 4
    ├── InsufficientDataError exit 5
    └── OutputError           exit 6

``DelistedWarning`` is deliberately NOT an exception: it is a non-fatal
warning payload that is surfaced to stderr while the exit code stays 0.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Type


class SmcPromptError(Exception):
    """Base error; used for unexpected internal failures (exit 1)."""

    exit_code: int = 1


class ConfigError(SmcPromptError):
    """Invalid CLI arguments / configuration (exit 2)."""

    exit_code = 2


class SymbolNotFoundError(SmcPromptError):
    """Symbol is not listed on Binance Spot (exit 3)."""

    exit_code = 3


class NetworkError(SmcPromptError):
    """Binance API unreachable after retries were exhausted (exit 4)."""

    exit_code = 4


class InsufficientDataError(SmcPromptError):
    """Not enough closed history to compute structure (exit 5)."""

    exit_code = 5


class OutputError(SmcPromptError):
    """Neither clipboard nor fallback file could be produced (exit 6)."""

    exit_code = 6


class ClipboardUnavailable(SmcPromptError):
    """Internal signal: clipboard access failed; triggers the file fallback.

    Never propagated to the user as a fatal error on its own.
    """

    exit_code = 6


@dataclass(frozen=True)
class DelistedWarning:
    """Non-fatal warning: latest candles show zero volume."""

    symbol: str
    count: int

    def message(self) -> str:
        return (
            f"Latest {self.count} candles have zero volume; {self.symbol} "
            f"may be delisted or halted. Prompt generated with caution."
        )


def exit_code_for(error: BaseException) -> int:
    """Return the process exit code mapped to ``error``."""

    if isinstance(error, SmcPromptError):
        return error.exit_code
    return SmcPromptError.exit_code


#: Convenience mapping (exception class -> exit code), used by the CLI tests.
EXIT_CODE_MAP: dict[Type[SmcPromptError], int] = {
    SmcPromptError: SmcPromptError.exit_code,
    ConfigError: ConfigError.exit_code,
    SymbolNotFoundError: SymbolNotFoundError.exit_code,
    NetworkError: NetworkError.exit_code,
    InsufficientDataError: InsufficientDataError.exit_code,
    OutputError: OutputError.exit_code,
}
