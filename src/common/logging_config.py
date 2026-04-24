"""Centralised loguru configuration.

Each MCP server and the agent call :func:`configure_logging` on startup with
their component name. Logs go to both stderr (for MCP stdio debugging) and a
rotating file under ``<project_root>/logs/<component>.log``.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger


def configure_logging(component: str, log_dir: str | Path, level: str = "INFO") -> None:
    """Add a rotating file sink for this component. Idempotent per-component."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{component}.log"
    logger.add(
        str(log_file),
        rotation="10 MB",
        retention="7 days",
        enqueue=True,
        level=level,
        filter=lambda record: record["extra"].get("component", component) == component,
    )
    # Bind the component name so filtered sinks work and log lines are attributable.
    logger.configure(extra={"component": component})
