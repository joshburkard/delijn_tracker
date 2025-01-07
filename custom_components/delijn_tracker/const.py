# custom_components/delijn_tracker/const.py
"""Constants for the De Lijn Bus Tracker integration."""
from typing import Final

DOMAIN: Final = "delijn_tracker"

# Configuration
CONF_HALTE_NUMBER: Final = "halte_number"
CONF_LINE_NUMBER: Final = "line_number"
CONF_SCHEDULED_TIME: Final = "scheduled_time"
CONF_DESTINATION: Final = "destination"

# Step IDs
STEP_USER: Final = "user"
STEP_ADD_DEVICE: Final = "add_device"
STEP_SELECT_LINE: Final = "select_line"
STEP_SELECT_TIME: Final = "select_time"

# Default values
DEFAULT_SCAN_INTERVAL: Final = 60  # seconds

# Error messages
ERROR_CANNOT_CONNECT: Final = "cannot_connect"
ERROR_INVALID_AUTH: Final = "invalid_auth"
ERROR_NO_LINES: Final = "no_lines_available"
ERROR_NO_TIMES: Final = "no_times_available"
