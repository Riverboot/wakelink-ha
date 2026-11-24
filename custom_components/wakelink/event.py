"""Event entity: ringing, snoozing, dismissing as they happen."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WakeLinkConfigEntry
from .const import EVENT_TYPES
from .entity import WakeLinkPhoneEntity
from .phone import Phone


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WakeLinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the event entity of a phone."""
    if isinstance(entry.runtime_data, Phone):
        async_add_entities([AlarmEvent(entry.runtime_data)])


class AlarmEvent(WakeLinkPhoneEntity, EventEntity):
    """Fires with every alarm event the app reports."""

    _attr_event_types = EVENT_TYPES

    def __init__(self, phone: Phone) -> None:
        """Initialize."""
        super().__init__(phone, "alarm")

    async def async_added_to_hass(self) -> None:
        """Follow the phone's events, not its state."""
        self.async_on_remove(self.phone.async_add_event_listener(self._async_handle))

    @callback
    def _async_handle(self, event_type: str, attributes: dict[str, Any]) -> None:
        self._trigger_event(event_type, attributes)
        self.async_write_ha_state()
