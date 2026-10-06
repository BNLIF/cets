"""Log record formatting shared by every handler in settings.LOGGING."""

import logging
import time


class UtcFormatter(logging.Formatter):
    """``asctime`` in UTC, so the ops page's error tail reads in the same
    clock as the rest of the app (TIME_ZONE = "UTC") whatever the server's
    local zone is."""
    converter = time.gmtime
