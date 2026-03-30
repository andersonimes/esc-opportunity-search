"""ESC Opportunity Search — MCP server and data ingestion for ESC volunteering opportunities."""

import logging
import os
import sys


def setup_logging(context: str = "server") -> logging.Logger:
    """Configure logging for the given context.

    Args:
        context: "server" logs to stderr (safe for stdio MCP transport).
                 "ingestion" logs to a file (configurable via ESC_LOG_FILE env var).
    """
    logger = logging.getLogger("esc_opportunity_search")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    if context == "ingestion":
        log_file = os.environ.get("ESC_LOG_FILE", "esc-ingestion.log")
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        # Also log to stderr for interactive use
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(formatter)
        logger.addHandler(stderr_handler)
    else:
        # Server context: stderr only (never stdout — corrupts stdio transport)
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
