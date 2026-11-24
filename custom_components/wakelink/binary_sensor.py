"""Binary sensors: alarm set, readiness, household state."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WakeLinkConfigEntry
from .entity import WakeLinkHouseholdEntity, WakeLinkPhoneEntity
from .household import Household
from .phone import Phone


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WakeLinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    runtime = entry.runtime_data
    if isinstance(runtime, Phone):
        async_add_entities([AlarmSetSensor(runtime), ProblemSensor(runtime)])
    else:
        async_add_entities(
            [SomeoneWakingSensor(runtime), AllAwakeSensor(runtime)]
        )


class AlarmSetSensor(WakeLinkPhoneEntity, BinarySensorEntity):
    """At least one alarm is switched on."""

    def __init__(self, phone: Phone) -> None:
        """Initialize."""
        super().__init__(phone, "alarm_set")

    @property
    def is_on(self) -> bool:
        """Whether an alarm is on."""
        return self.phone.alarm_set

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Counts, as in the YAML sensors before."""
        alarms = self.phone.state.alarms
        return {
            "count": len(alarms),
            "enabled_count": sum(1 for alarm in alarms if alarm.get("enabled")),
        }


class ProblemSensor(WakeLinkPhoneEntity, BinarySensorEntity):
    """Something on the phone keeps the alarm from working.

    The app already checks this for its own start screen. Reporting it means
    a permission lost after an update is noticed in the evening, not when the
    alarm stays silent in the morning.
    """

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, phone: Phone) -> None:
        """Initialize."""
        super().__init__(phone, "problem")

    @property
    def is_on(self) -> bool | None:
        """Whether a critical issue exists. Unknown until the app has reported."""
        if self.phone.state.ready is None:
            return None
        return bool(self.phone.critical_issues)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Which issues."""
        return {
            "issues": self.phone.critical_issues,
            "warnings": self.phone.warnings,
        }


class SomeoneWakingSensor(WakeLinkHouseholdEntity, BinarySensorEntity):
    """An alarm at home is ringing or snoozing."""

    def __init__(self, household: Household) -> None:
        """Initialize."""
        super().__init__(household, "someone_waking")

    @property
    def is_on(self) -> bool:
        """Whether someone is being woken."""
        return self.household.someone_waking


class AllAwakeSensor(WakeLinkHouseholdEntity, BinarySensorEntity):
    """Everyone at home whose alarm rang today has switched it off."""

    def __init__(self, household: Household) -> None:
        """Initialize."""
        super().__init__(household, "all_awake")

    @property
    def is_on(self) -> bool:
        """Whether everyone is up."""
        return self.household.all_awake
