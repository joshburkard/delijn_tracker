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

# Delay thresholds (in minutes)
DELAY_HIGH: Final = 10
DELAY_MEDIUM: Final = 5
DELAY_LOW: Final = 1
EARLY_HIGH: Final = 6
EARLY_MEDIUM: Final = 3
EARLY_LOW: Final = 1

# Delay threshold labels
DELAY_HIGH_LABEL: Final = f"High Delay (> {DELAY_HIGH} minutes)"
DELAY_MEDIUM_LABEL: Final = f"Medium Delay (> {DELAY_MEDIUM} minutes < {DELAY_HIGH} minutes)"
DELAY_LOW_LABEL: Final = f"Low Delay (> {DELAY_LOW} minute < {DELAY_MEDIUM} minutes)"
EARLY_HIGH_LABEL: Final = f"High Early (> {EARLY_HIGH} minutes)"
EARLY_MEDIUM_LABEL: Final = f"Medium Early (> {EARLY_MEDIUM} minutes < {EARLY_HIGH} minutes)"
EARLY_LOW_LABEL: Final = f"Low Early (> {EARLY_LOW} minute < {EARLY_MEDIUM} minutes)"

# Error messages
ERROR_CANNOT_CONNECT: Final = "cannot_connect"
ERROR_INVALID_AUTH: Final = "invalid_auth"
ERROR_NO_LINES: Final = "no_lines_available"
ERROR_NO_TIMES: Final = "no_times_available"
