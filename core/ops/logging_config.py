"""Application logging configuration."""

from __future__ import annotations

import logging


NOISY_FRAMEWORK_LOGGERS = (
    "flet_controls",
    "flet_transport",
    "flet_object_patch",
    "flet_components",
)


def configure_logging(level: str = "INFO") -> None:
    """Configure useful application logs without Flet control-tree noise."""
    normalized = (level or "INFO").upper()
    numeric_level = getattr(logging, normalized, logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )

    framework_level = logging.DEBUG if numeric_level <= logging.DEBUG else logging.WARNING
    for logger_name in NOISY_FRAMEWORK_LOGGERS:
        logging.getLogger(logger_name).setLevel(framework_level)
