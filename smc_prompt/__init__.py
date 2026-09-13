"""smc-prompt — mechanical SMC/ICT [FAKTA] payload generator.

This package performs NO reasoning of its own: it fetches public Binance
market data, computes only objective structural facts, and injects them into a
fixed prompt template. See ``docs/DESIGN_SPEC.md`` for the frozen design.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
