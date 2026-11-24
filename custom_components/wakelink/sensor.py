"""Sensors: next alarm, status, snooze round, last contact."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WakeLinkConfigEntry
from .const import STATUSES
from .entity import WakeLinkHouseholdEntity, WakeLinkPhoneEntity
from .phone import Phone, parse_time


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WakeLinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    runtime = entry.runtime_data
    if isinstance(runtime, Phone):
        async_add_entities(
            [
                NextAlarmSensor(runtime),
                StatusSensor(runtime),
                SnoozeRoundSensor(runtime),
                LastSeenSensor(runtime),
            ]
        )
    else:
        async_add_entities([HouseholdNextAlarmSensor(runtime)])


class NextAlarmSensor(WakeLinkPhoneEntity, SensorEntity):
    """When the phone rings next."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    # The full list is for templates such as an Alexa announcement, not for
    # the history: it would be stored again with every change
    _unrecorded_attributes = frozenset({"alarms"})

    def __init__(self, phone: Phone) -> None:
        """Initialize."""
        super().__init__(phone, "next_alarm")

    @property
    def native_value(self) -> datetime | None:
        """Time of the next alarm."""
        occurrence = self.phone.next_occurrence()
        return occurrence.at if occurrence else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Details of the next alarm and the full alarm list."""
        occurrence = self.phone.next_occurrence()
        return {
            "label": occurrence.label if occurrence else None,
            "alarm_id": occurrence.alarm_id if occurrence else None,
            "nap": occurrence.nap if occurrence else None,
            "alarms": self.phone.state.alarms,
        }


class StatusSensor(WakeLinkPhoneEntity, SensorEntity):
    """Idle, ringing or snoozed."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUSES

    def __init__(self, phone: Phone) -> None:
        """Initialize."""
        super().__init__(phone, "status")

    @property
    def native_value(self) -> str:
        """Current status."""
        return self.phone.state.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Which alarm rings and until when it snoozes."""
        ringing = self.phone.state.ringing or {}
        return {
            "alarm_name": ringing.get("label"),
            "snoozed_until": self.phone.state.snoozed_until,
        }


class SnoozeRoundSensor(WakeLinkPhoneEntity, SensorEntity):
    """How often the current alarm has been snoozed."""

    def __init__(self, phone: Phone) -> None:
        """Initialize."""
        super().__init__(phone, "snooze_round")

    @property
    def native_value(self) -> int:
        """Snoozes so far, 0 when idle."""
        return self.phone.state.snooze_round


class LastSeenSensor(WakeLinkPhoneEntity, SensorEntity):
    """When the phone last reported."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, phone: Phone) -> None:
        """Initialize."""
        super().__init__(phone, "last_seen")

    @property
    def native_value(self) -> datetime | None:
        """Time of the last message."""
        return parse_time(self.phone.state.last_seen)


class HouseholdNextAlarmSensor(WakeLinkHouseholdEntity, SensorEntity):
    """The earliest upcoming alarm of everyone at home."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, household) -> None:
        """Initialize."""
        super().__init__(household, "household_next_alarm")

    @property
    def native_value(self) -> datetime | None:
        """Time of the earliest alarm."""
        upcoming = self.household.next_alarm()
        return upcoming[1].at if upcoming else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Whose alarm it is."""
        upcoming = self.household.next_alarm()
        if upcoming is None:
            return {"phone": None, "person": None, "label": None}
        phone, occurrence = upcoming
        return {
            "phone": phone.entry.title,
            "person": phone.person,
            "label": occurrence.label,
        }
