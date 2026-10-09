"""16 · tracing: optional LangSmith tracing.

LangChain reads LANGSMITH_* straight from the environment (config.py loads
.env), so there's nothing to wire. this only logs whether a run is traced.
"""

import logging

from value_investor import config

logger = logging.getLogger(__name__)


def check_langsmith_tracing() -> bool:
    on = config.LANGSMITH_TRACING.lower() == "true" and bool(config.LANGSMITH_API_KEY)
    if on:
        logger.info("LangSmith tracing on, project '%s'", config.LANGSMITH_PROJECT)
    else:
        logger.info("LangSmith tracing off (LANGSMITH_TRACING=true in .env to turn it on)")
    return on


if __name__ == "__main__":
    from value_investor.logging_config import configure_logging

    configure_logging()
    check_langsmith_tracing()
