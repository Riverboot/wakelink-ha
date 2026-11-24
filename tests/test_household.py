"""The household overview across phones."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.wakelink.const import DOMAIN

from .conftest import PostMessage, event, household_entry, message, phone_entry

EARLIEST = "sensor.household_earliest_alarm"
WAKING = "binary_sensor.household_someone_is_waking_up"
ALL_AWAKE = "binary_sensor.household_everyone_awake"


def _upcoming(at: str, label: str) -> list[dict]:
    return [{"alarm_id": 1, "label": label, "at": at, "nap": False}]


async def _setup(hass: HomeAssistant) -> None:
    hass.states.async_set("person.anna", "home")
    hass.states.async_set("person.ben", "home")
    phone_entry(hass, "Anna", "anna_hook", person="person.anna")
    phone_entry(hass, "Ben", "ben_hook", person="person.ben")
    household_entry(hass)
    # Sets up all three entries
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()


async def test_earliest_alarm_of_everyone_at_home(
    hass: HomeAssistant, post: PostMessage
) -> None:
    """Ben gets up earlier; while Ben is away, Anna's alarm counts."""
    await _setup(hass)
    await post(
        message("state.json", upcoming=_upcoming("2026-11-25T06:30:00+01:00", "Anna")),
        "anna_hook",
    )
    await post(
        message("state.json", upcoming=_upcoming("2026-11-25T05:15:00+01:00", "Ben")),
        "ben_hook",
    )

    earliest = hass.states.get(EARLIEST)
    assert earliest.state == "2026-11-25T04:15:00+00:00"
    assert earliest.attributes["phone"] == "Ben"
    assert earliest.attributes["person"] == "person.ben"

    hass.states.async_set("person.ben", "not_home")
    await hass.async_block_till_done()
    assert hass.states.get(EARLIEST).state == "2026-11-25T05:30:00+00:00"

    hass.states.async_set("person.ben", "home")
    await hass.async_block_till_done()
    assert hass.states.get(EARLIEST).attributes["phone"] == "Ben"


async def test_waking_and_all_awake(hass: HomeAssistant, post: PostMessage) -> None:
    """All awake once everyone whose alarm rang has switched it off."""
    await _setup(hass)
    assert hass.states.get(WAKING).state == "off"
    assert hass.states.get(ALL_AWAKE).state == "off"

    await post(event("triggered", 1), "anna_hook")
    assert hass.states.get(WAKING).state == "on"
    assert hass.states.get(ALL_AWAKE).state == "off"

    await post(event("triggered", 1), "ben_hook")
    await post(event("dismissed", 2), "anna_hook")
    assert hass.states.get(WAKING).state == "on"
    assert hass.states.get(ALL_AWAKE).state == "off"

    await post(event("snoozed", 2, snooze_minutes=5, snooze_count=1), "ben_hook")
    assert hass.states.get(ALL_AWAKE).state == "off"

    await post(event("dismissed", 3), "ben_hook")
    assert hass.states.get(WAKING).state == "off"
    assert hass.states.get(ALL_AWAKE).state == "on"


async def test_all_awake_ignores_who_is_away(
    hass: HomeAssistant, post: PostMessage
) -> None:
    """Someone away does not hold up the morning at home."""
    await _setup(hass)
    hass.states.async_set("person.ben", "not_home")
    await post(event("triggered", 1), "ben_hook")
    await post(event("triggered", 1), "anna_hook")
    await post(event("dismissed", 2), "anna_hook")
    assert hass.states.get(ALL_AWAKE).state == "on"


async def test_phone_removed_from_household(
    hass: HomeAssistant, post: PostMessage
) -> None:
    """An unloaded phone no longer counts."""
    await _setup(hass)
    await post(
        message("state.json", upcoming=_upcoming("2026-11-25T05:15:00+01:00", "Ben")),
        "ben_hook",
    )
    ben = next(
        entry for entry in hass.config_entries.async_entries("wakelink") if entry.title == "Ben"
    )
    assert await hass.config_entries.async_unload(ben.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(EARLIEST).state == "unknown"
