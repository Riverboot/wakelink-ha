"""Base entities."""

from __future__ import annotations

from homeassistant.helpers.entity import Entity

from .household import Household
from .phone import Phone


class WakeLinkPhoneEntity(Entity):
    """An entity of a paired phone."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, phone: Phone, key: str) -> None:
        """Initialize."""
        self.phone = phone
        self._attr_unique_id = f"{phone.entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = phone.device_info

    async def async_added_to_hass(self) -> None:
        """Follow the phone."""
        self.async_on_remove(self.phone.async_add_listener(self.async_write_ha_state))


class WakeLinkHouseholdEntity(Entity):
    """An entity of the household."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, household: Household, key: str) -> None:
        """Initialize."""
        self.household = household
        self._attr_unique_id = f"{household.entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = household.device_info

    async def async_added_to_hass(self) -> None:
        """Follow the household."""
        self.async_on_remove(
            self.household.async_add_listener(self.async_write_ha_state)
        )
