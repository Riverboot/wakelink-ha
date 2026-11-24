"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import copy
import json
from pathlib import Path
from typing import Any

from aiohttp import ClientResponse
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import CONF_NAME, CONF_URL, CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.wakelink.const import (
    CONF_KIND,
    CONF_SECRET,
    DOMAIN,
    HOUSEHOLD_UNIQUE_ID,
    KIND_HOUSEHOLD,
    KIND_PHONE,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOW = "2026-11-24T20:00:00+00:00"  # 21:00 in Berlin, the evening before

type PostMessage = Callable[..., Awaitable[ClientResponse]]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ in every test."""


@pytest.fixture(autouse=True)
async def berlin(hass: HomeAssistant, freezer) -> None:
    """Local time matters for "today"."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(NOW)


def load_fixture(name: str) -> dict[str, Any]:
    """A protocol message from tests/fixtures."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def message(name: str, **changes: Any) -> dict[str, Any]:
    """A copy of a fixture with some fields replaced."""
    data = copy.deepcopy(load_fixture(name))
    data.update(changes)
    return data


def event(event_type: str, seq: int, **fields: Any) -> dict[str, Any]:
    """An event message."""
    data = message("event_snoozed.json", event=event_type, seq=seq)
    for key in ("snooze_minutes", "snooze_count"):
        data.pop(key)
    data.update(fields)
    return data


def phone_entry(
    hass: HomeAssistant, name: str = "Pixel", webhook_id: str = "pixel_hook", **options: Any
) -> MockConfigEntry:
    """A paired phone."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=name,
        unique_id=webhook_id,
        data={
            CONF_KIND: KIND_PHONE,
            CONF_NAME: name,
            CONF_URL: "http://192.168.1.20:8123",
            CONF_WEBHOOK_ID: webhook_id,
            CONF_SECRET: "secret",
        },
        options=options,
    )
    entry.add_to_hass(hass)
    return entry


def household_entry(hass: HomeAssistant) -> MockConfigEntry:
    """The household overview."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Household",
        unique_id=HOUSEHOLD_UNIQUE_ID,
        data={CONF_KIND: KIND_HOUSEHOLD},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def pixel(hass: HomeAssistant) -> MockConfigEntry:
    """A set-up phone called Pixel."""
    entry = phone_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture
async def post(hass: HomeAssistant, hass_client_no_auth) -> PostMessage:
    """Post a message to a webhook like the app does."""
    assert await async_setup_component(hass, "webhook", {})
    client = await hass_client_no_auth()

    async def _post(data: dict[str, Any], webhook_id: str = "pixel_hook") -> ClientResponse:
        response = await client.post(f"/api/webhook/{webhook_id}", json=data)
        await hass.async_block_till_done()
        return response

    return _post
