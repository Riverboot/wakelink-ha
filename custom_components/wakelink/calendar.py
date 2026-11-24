"""Calendar with the alarms of the next 14 days.

Its main use is the calendar trigger with an offset: "20 minutes before the
alarm" becomes an ordinary trigger, and every automation picks its own lead.
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import WakeLinkConfigEntry
from .const import CALENDAR_EVENT_LENGTH
from .entity import WakeLinkPhoneEntity
from .phone import Occurrence, Phone


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WakeLinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the calendar of a phone."""
    if isinstance(entry.runtime_data, Phone):
        async_add_entities([AlarmCalendar(entry.runtime_data)])


def _event(occurrence: Occurrence) -> CalendarEvent:
    start = dt_util.as_local(occurrence.at)
    return CalendarEvent(
        start=start,
        end=start + CALENDAR_EVENT_LENGTH,
        summary=occurrence.label or "Alarm",
        description="Power Nap" if occurrence.nap else None,
        uid=f"{occurrence.alarm_id}-{occurrence.at.isoformat()}",
    )


class AlarmCalendar(WakeLinkPhoneEntity, CalendarEntity):
    """Upcoming alarms of a phone."""

    def __init__(self, phone: Phone) -> None:
        """Initialize."""
        super().__init__(phone, "alarms")

    @property
    def event(self) -> CalendarEvent | None:
        """The alarm ringing right now or next."""
        now = dt_util.utcnow()
        for occurrence in self.phone.occurrences:
            if occurrence.at + CALENDAR_EVENT_LENGTH > now:
                return _event(occurrence)
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Alarms between start and end."""
        return [
            _event(occurrence)
            for occurrence in self.phone.occurrences
            if occurrence.at < end_date
            and occurrence.at + CALENDAR_EVENT_LENGTH > start_date
        ]
