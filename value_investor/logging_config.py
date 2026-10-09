"""02 · logging_config — readable console logging for the entry points.

Library modules log through `logging`; scripts call configure_logging()
once. print() is only for a script's own output.
"""

import logging
import os

_CONFIGURED = False


def configure_logging(level: "str | int | None" = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    level = level or os.getenv("LOG_LEVEL", "INFO")
    logging.basicConfig(level=level, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("value_investor").setLevel(level)
    for noisy in ("yfinance", "urllib3", "httpx", "LiteLLM", "peewee"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True
