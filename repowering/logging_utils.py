"""Shared logging helper. Where messages are written is configured in settings.LOGGING."""

from contextlib import contextmanager


@contextmanager
def log_run(logger, name, **details):
    """Mark one command run in the log: STARTED, then SUCCEEDED or FAILED.

    Usage:
        logger = logging.getLogger(__name__)
        with log_run(logger, "import_wind_data", source=path):
            ...
    """
    suffix = " ".join(f"{key}={value}" for key, value in details.items())
    logger.info("STARTED: %s%s", name, f" ({suffix})" if suffix else "")
    try:
        yield logger
    except BaseException:
        logger.exception("FAILED: %s", name)
        raise
    logger.info("SUCCEEDED: %s", name)
