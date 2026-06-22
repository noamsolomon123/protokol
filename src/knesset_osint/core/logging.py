"""Minimal, dependency-free logging setup (stdlib only)."""

from __future__ import annotations

import logging
import sys

from knesset_osint.core.config import settings

_CONFIGURED = False


def configure_logging(level: str | None = None) -> logging.Logger:
    """Configure root logging once and return the package logger."""
    global _CONFIGURED
    if not _CONFIGURED:
        logging.basicConfig(
            level=(level or settings.log_level).upper(),
            format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            stream=sys.stdout,
        )
        _CONFIGURED = True
    return logging.getLogger("knesset_osint")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"knesset_osint.{name}")
