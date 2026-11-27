"""Keep open-mastr's log output in our download log.

open-mastr configures the global Python logging when it is imported. This
context manager lets it run, sends its messages to the given handlers (those
of the download logger from settings.LOGGING) and restores everything after.
"""

import logging
import os
from contextlib import contextmanager


@contextmanager
def capture_open_mastr_logs(handlers, mastr_home_directory):
    """Yield open-mastr's Mastr class with its log output sent to `handlers`."""
    root_logger = logging.getLogger()
    old_root_handlers = root_logger.handlers[:]
    old_root_level = root_logger.level

    old_home = os.environ.get("MASTR_PROJECT_HOME_DIR")
    os.environ["MASTR_PROJECT_HOME_DIR"] = str(mastr_home_directory)

    package_logger = None
    old_package_handlers = None
    old_package_level = None
    old_package_propagate = None
    try:
        from open_mastr import Mastr

        package_logger = logging.getLogger("open-MaStR")
        old_package_handlers = package_logger.handlers[:]
        old_package_level = package_logger.level
        old_package_propagate = package_logger.propagate
        for handler in handlers:            # keep open-mastr's own handlers too
            package_logger.addHandler(handler)
        package_logger.setLevel(logging.INFO)
        package_logger.propagate = False
        yield Mastr
    finally:
        if package_logger is not None:
            package_logger.handlers = old_package_handlers
            package_logger.setLevel(old_package_level)
            package_logger.propagate = old_package_propagate

        for root_handler in root_logger.handlers[:]:
            if root_handler not in old_root_handlers:
                root_handler.close()
        root_logger.handlers = old_root_handlers
        root_logger.setLevel(old_root_level)

        if old_home is None:
            os.environ.pop("MASTR_PROJECT_HOME_DIR", None)
        else:
            os.environ["MASTR_PROJECT_HOME_DIR"] = old_home
