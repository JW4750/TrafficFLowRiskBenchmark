"""HighD-based traffic risk benchmarking toolkit."""

from importlib.metadata import version, PackageNotFoundError

try:  # pragma: no cover - runtime metadata guard
    __version__ = version("highd_hsm")
except PackageNotFoundError:  # pragma: no cover - dev mode fallback
    __version__ = "0.0.0"

__all__ = ["__version__"]
