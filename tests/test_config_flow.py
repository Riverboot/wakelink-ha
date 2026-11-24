"""Pairing a phone and adding the household."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.wakelink.const import DOMAIN

from .conftest import PostMessage, event, household_entry, message, phone_entry


def _link_params(result: dict[str, Any]) -> dict[str, str]:
    link = urlsplit(result["description_placeholders"]["link"])
    assert (link.scheme, link.netloc) == ("wakelink", "pair")
    return {key: values[0] for key, values in parse_qs(link.query).items()}


async def _to_pair_step(hass: HomeAssistant, **form: Any) -> dict[str, Any]:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "phone"}
    )
    assert result["step_id"] == "phone"
    data = {"name": "Anna", "url": "http://192.168.1.20:8123/", **form}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], data)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pair"
    return result


async def test_pair_phone(hass: HomeAssistant, post: PostMessage) -> None:
    """Scan, report, submit: the entry starts with the pairing message's data."""
    hass.states.async_set("person.anna", "home")
    result = await _to_pair_step(hass, person="person.anna")
    params = _link_params(result)
    assert params["v"] == "1"
    assert params["url"] == "http://192.168.1.20:8123"
    assert params["name"] == "Anna"
    assert len(params["id"]) == 64
    assert params["secret"]

    # Submitted before the phone reported
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "not_connected"}

    response = await post(message("state.json"), params["id"])
    assert await response.json() == {"ok": True}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Anna"
    assert result["options"] == {"person": "person.anna"}
    await hass.async_block_till_done()

    assert hass.states.get("sensor.anna_next_alarm").state == "2026-11-25T05:30:00+00:00"

    # The webhook now belongs to the entry
    await post(event("triggered", 50), params["id"])
    assert hass.states.get("sensor.anna_alarm_status").state == "ringing"


async def test_pairing_rejects_garbage(hass: HomeAssistant, post: PostMessage) -> None:
    """Only a valid protocol message completes the pairing."""
    result = await _to_pair_step(hass)
    params = _link_params(result)

    response = await post({"hello": "world"}, params["id"])
    assert response.status == 400
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "not_connected"}


async def test_invalid_url(hass: HomeAssistant) -> None:
    """The address must be http or https."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "phone"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Anna", "url": "192.168.1.20:8123"}
    )
    assert result["step_id"] == "phone"
    assert result["errors"] == {"url": "invalid_url"}


async def test_abandoned_pairing_frees_the_webhook(
    hass: HomeAssistant, post: PostMessage
) -> None:
    """Closing the dialog unregisters the pairing webhook."""
    result = await _to_pair_step(hass)
    params = _link_params(result)
    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()

    response = await post(message("state.json"), params["id"])
    assert await response.text() == ""  # unknown webhook


async def test_add_household_once(hass: HomeAssistant) -> None:
    """The menu offers the household until it exists."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "household"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Household"
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "phone"


async def test_options_link_person(hass: HomeAssistant) -> None:
    """A phone can be linked to a person later."""
    entry = phone_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"person": "person.anna"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options == {"person": "person.anna"}
    assert entry.runtime_data.person == "person.anna"


async def test_household_has_no_options(hass: HomeAssistant) -> None:
    """Only phones have something to configure."""
    phone = phone_entry(hass)
    household = household_entry(hass)
    assert phone.supports_options
    assert not household.supports_options
