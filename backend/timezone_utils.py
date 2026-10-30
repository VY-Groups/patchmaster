"""
Timezone Utilities for Patch-SecOps Solution.

Provides common timezone conversion and handling functions.
Ensures consistent timezone handling throughout the application.
"""

import os
from datetime import datetime, timezone as pytz
from typing import Optional


# Common timezone names
SUPPORTED_TIMEZONES = [
    "UTC",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Anchorage",
    "Pacific/Honolulu",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Asia/Tokyo",
    "Asia/Shanghai",
    "Asia/Singapore",
    "Australia/Sydney",
]

# Aliases for common timezone names
TIMEZONE_ALIASES = {
    "EST": "America/New_York",
    "CST": "America/Chicago",
    "MST": "America/Denver",
    "PST": "America/Los_Angeles",
    "GMT": "Europe/London",
    "CET": "Europe/Paris",
    "JST": "Asia/Tokyo",
}


def _utcnow():
    """Get current UTC time as naive datetime for DB storage."""
    return datetime.now(pytz.utc).replace(tzinfo=None)


def get_current_utc() -> datetime:
    """Get current UTC datetime (naive, for database storage)."""
    return _utcnow()


def get_current_time_in_timezone(tz_name: str) -> datetime:
    """Get current time in specified timezone.

    Args:
        tz_name: Timezone name (e.g., 'America/New_York')

    Returns:
        datetime in the specified timezone (naive)
    """
    tz = pytz.timezone(tz_name)
    return datetime.now(tz).replace(tzinfo=None)


def to_utc(dt: datetime, source_tz: Optional[str] = None) -> datetime:
    """Convert datetime to UTC.

    Args:
        dt: datetime to convert (naive or aware)
        source_tz: Source timezone (if dt is naive). Defaults to UTC.

    Returns:
        datetime in UTC (naive)
    """
    if dt.tzinfo is not None:
        # Already aware - convert to UTC
        return dt.astimezone(pytz.UTC).replace(tzinfo=None)

    # Naive - assume source timezone or UTC
    if source_tz:
        tz = pytz.timezone(source_tz)
        aware = tz.localize(dt)
        return aware.astimezone(pytz.UTC).replace(tzinfo=None)

    # Default to UTC
    return dt.replace(tzinfo=None)


def from_utc(dt: datetime, target_tz: str) -> datetime:
    """Convert UTC datetime to target timezone.

    Args:
        dt: datetime in UTC (naive or aware)
        target_tz: Target timezone name

    Returns:
        datetime in target timezone (naive)
    """
    if dt.tzinfo is not None:
        utc_dt = dt.astimezone(pytz.UTC)
    else:
        utc_dt = pytz.utc.localize(dt)

    tz = pytz.timezone(target_tz)
    return utc_dt.astimezone(tz).replace(tzinfo=None)


def parse_timezone(tz_name: str) -> str:
    """Normalize timezone name.

    Args:
        tz_name: Timezone name or alias

    Returns:
        Normalized timezone name
    """
    # Check aliases first
    if tz_name.upper() in TIMEZONE_ALIASES:
        return TIMEZONE_ALIASES[tz_name.upper()]

    # Check if valid timezone
    try:
        pytz.timezone(tz_name)
        return tz_name
    except pytz.exceptions.UnknownTimeZoneError:
        pass

    # Default to UTC
    return "UTC"


def is_valid_timezone(tz_name: str) -> bool:
    """Check if timezone name is valid.

    Args:
        tz_name: Timezone name

    Returns:
        True if valid timezone
    """
    try:
        pytz.timezone(tz_name)
        return True
    except pytz.exceptions.UnknownTimeZoneError:
        return False


def format_datetime_with_timezone(
    dt: datetime,
    tz_name: str,
    fmt: str = "%Y-%m-%d %H:%M:%S",
) -> str:
    """Format datetime with timezone.

    Args:
        dt: datetime to format (naive)
        tz_name: Target timezone
        fmt: Format string

    Returns:
        Formatted string with timezone
    """
    local_dt = from_utc(dt, tz_name)
    tz = pytz.timezone(tz_name)
    return f"{local_dt.strftime(fmt)} {tzname_from_tz(tz)}"


def tzname_from_tz(tz: pytz.timezone) -> str:
    """Get timezone name from tz object."""
    # Get the timezone name
    return str(tz)


def get_user_timezone() -> str:
    """Get timezone from user settings or environment.

    Returns:
        Timezone name (defaults to UTC)
    """
    # Check environment variable
    tz = os.getenv("PM_USER_TIMEZONE")
    if tz and is_valid_timezone(tz):
        return tz

    # Default to UTC
    return "UTC"


def get_current_timezone() -> str:
    """Get current system timezone.

    Returns:
        Timezone name (defaults to UTC)
    """
    # First try user timezone, then server timezone
    tz = get_user_timezone()
    if tz != "UTC":
        return tz

    # Try server timezone
    tz = get_server_timezone()
    if tz != "UTC":
        return tz

    # Fall back to UTC
    return "UTC"


def get_server_timezone() -> str:
    """Get server timezone from environment.

    Returns:
        Timezone name (defaults to UTC)
    """
    tz = os.getenv("PM_SERVER_TIMEZONE")
    if tz and is_valid_timezone(tz):
        return tz

    return "UTC"


def convert_timestamp_to_timezone(
    timestamp: float,
    target_tz: str,
) -> datetime:
    """Convert Unix timestamp to datetime in target timezone.

    Args:
        timestamp: Unix timestamp
        target_tz: Target timezone name

    Returns:
        datetime in target timezone
    """
    utc_dt = datetime.fromtimestamp(timestamp, tz=pytz.utc)
    tz = pytz.timezone(target_tz)
    return utc_dt.astimezone(tz).replace(tzinfo=None)


def get_utc_offset(tz_name: str) -> str:
    """Get UTC offset for timezone.

    Args:
        tz_name: Timezone name

    Returns:
        UTC offset string (e.g., '+05:30', '-08:00')
    """
    if not is_valid_timezone(tz_name):
        return "+00:00"

    tz = pytz.timezone(tz_name)
    now = datetime.now(tz)
    offset = now.strftime("%z")

    # Format as +HH:MM
    if offset:
        if len(offset) == 4:  # +HHMM
            return f"{offset[:3]}:{offset[3:]}"
        return offset
    return "+00:00"


def get_timezone_display_name(tz_name: str) -> str:
    """Get display-friendly timezone name.

    Args:
        tz_name: Timezone name

    Returns:
        Display name with UTC offset
    """
    if not is_valid_timezone(tz_name):
        return f"UTC (invalid: {tz_name})"

    offset = get_utc_offset(tz_name)
    return f"{tz_name} (UTC{offset})"
