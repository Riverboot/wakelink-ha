"""Constants for the WakeLink integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "wakelink"

# Config entry data
CONF_KIND: Final = "kind"
CONF_SECRET: Final = "secret"
CONF_PERSON: Final = "person"

KIND_PHONE: Final = "phone"
KIND_HOUSEHOLD: Final = "household"
HOUSEHOLD_UNIQUE_ID: Final = "household"

# hass.data[DOMAIN] keys
DATA_PENDING: Final = "pending"

# Protocol, see docs/protocol.md
PROTOCOL_VERSION: Final = 2
LINK_VERSION: Final = 1
LINK_SCHEME: Final = "wakelink"

MSG_STATE: Final = "state"
MSG_EVENT: Final = "event"

STATUS_IDLE: Final = "idle"
STATUS_RINGING: Final = "ringing"
STATUS_SNOOZED: Final = "snoozed"
STATUSES: Final = [STATUS_IDLE, STATUS_RINGING, STATUS_SNOOZED]

EVENT_TRIGGERED: Final = "triggered"
EVENT_SNOOZED: Final = "snoozed"
EVENT_DISMISSED: Final = "dismissed"
EVENT_NAP_SCHEDULED: Final = "nap_scheduled"
EVENT_PRE_ALARM: Final = "pre_alarm"
EVENT_TYPES: Final = [
    EVENT_TRIGGERED,
    EVENT_SNOOZED,
    EVENT_DISMISSED,
    EVENT_NAP_SCHEDULED,
    EVENT_PRE_ALARM,
]

# Fields of an event message that are passed on as event attributes
EVENT_ATTRIBUTES: Final = (
    "alarm_id",
    "alarm_name",
    "time",
    "scheduled_for",
    "minutes_before",
    "snooze_minutes",
    "snooze_count",
    "reason",
    "test",
)

SIGNAL_PHONES_CHANGED: Final = f"{DOMAIN}_phones_changed"

STORAGE_VERSION: Final = 1
SAVE_DELAY: Final = 5
RECENT_EVENT_SEQS: Final = 50

CALENDAR_EVENT_LENGTH: Final = timedelta(minutes=1)
