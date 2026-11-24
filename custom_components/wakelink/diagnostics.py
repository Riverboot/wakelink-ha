"""Diagnostics download, without the webhook ID and secret."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant

from . import WakeLinkConfigEntry
from .const import CONF_SECRET
from .phone import Phone

TO_REDACT = {CONF_WEBHOOK_ID, CONF_SECRET}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: WakeLinkConfigEntry
) -> dict[str, Any]:
    """Entry data and, for a phone, its last known state."""
    diagnostics: dict[str, Any] = {
        "data": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
    }
    if isinstance(entry.runtime_data, Phone):
        diagnostics["state"] = asdict(entry.runtime_data.state)
    return diagnostics
