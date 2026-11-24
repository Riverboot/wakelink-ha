"""WakeLink: alarms of the WakeLink Android app in Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import CONF_KIND, KIND_HOUSEHOLD, STORAGE_VERSION
from .household import Household
from .phone import Phone, storage_key

PHONE_PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
    Platform.EVENT,
    Platform.SENSOR,
]
HOUSEHOLD_PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR]

type WakeLinkConfigEntry = ConfigEntry[Phone | Household]


def _platforms(entry: ConfigEntry) -> list[Platform]:
    if entry.data.get(CONF_KIND) == KIND_HOUSEHOLD:
        return HOUSEHOLD_PLATFORMS
    return PHONE_PLATFORMS


async def async_setup_entry(hass: HomeAssistant, entry: WakeLinkConfigEntry) -> bool:
    """Set up a phone or the household."""
    if entry.data.get(CONF_KIND) == KIND_HOUSEHOLD:
        household = Household(hass, entry)
        entry.runtime_data = household
        await hass.config_entries.async_forward_entry_setups(entry, HOUSEHOLD_PLATFORMS)
        household.async_start()
        return True

    phone = Phone(hass, entry)
    await phone.async_load()
    entry.runtime_data = phone
    await hass.config_entries.async_forward_entry_setups(entry, PHONE_PLATFORMS)
    phone.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WakeLinkConfigEntry) -> bool:
    """Unload a phone or the household."""
    if not await hass.config_entries.async_unload_platforms(entry, _platforms(entry)):
        return False
    runtime = entry.runtime_data
    if isinstance(runtime, Phone):
        await runtime.async_stop()
    else:
        runtime.async_stop()
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete what a removed phone left behind."""
    if entry.data.get(CONF_KIND) != KIND_HOUSEHOLD:
        await Store(hass, STORAGE_VERSION, storage_key(entry.entry_id)).async_remove()


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """A changed person link takes effect after a reload."""
    await hass.config_entries.async_reload(entry.entry_id)
