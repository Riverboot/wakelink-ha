"""Set up WakeLink: pair a phone by QR code, or add the household overview."""

from __future__ import annotations

import secrets
from typing import Any
from urllib.parse import urlencode, urlsplit

from aiohttp import web
import voluptuous as vol

from homeassistant.components import webhook
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME, CONF_URL, CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    QrCodeSelector,
    QrCodeSelectorConfig,
    QrErrorCorrectionLevel,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_KIND,
    CONF_PERSON,
    CONF_SECRET,
    DATA_PENDING,
    DOMAIN,
    HOUSEHOLD_UNIQUE_ID,
    KIND_HOUSEHOLD,
    KIND_PHONE,
    LINK_SCHEME,
    LINK_VERSION,
)
from .phone import InvalidMessage, validate_message

PERSON_SELECTOR = EntitySelector(EntitySelectorConfig(domain="person"))


def pairing_link(data: dict[str, Any]) -> str:
    """The link the QR code holds, see docs/protocol.md."""
    query = urlencode(
        {
            "v": LINK_VERSION,
            "url": data[CONF_URL],
            "id": data[CONF_WEBHOOK_ID],
            "secret": data[CONF_SECRET],
            "name": data[CONF_NAME],
        }
    )
    return f"{LINK_SCHEME}://pair?{query}"


def _normalize_url(value: str) -> str | None:
    """Base URL without trailing slash, or None if it is no http(s) URL."""
    value = value.strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return value


def _default_url(hass: HomeAssistant) -> str:
    """The address phones at home use, if Home Assistant knows it."""
    try:
        return get_url(hass, allow_external=False, allow_cloud=False, allow_ip=True)
    except NoURLAvailableError:
        return ""


class WakeLinkConfigFlow(ConfigFlow, domain=DOMAIN):
    """Pair a phone or add the household."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._data: dict[str, Any] = {}
        self._person: str | None = None
        self._received: dict[str, Any] | None = None
        self._listening = False

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Options of a phone."""
        return PhoneOptionsFlow()

    @classmethod
    @callback
    def async_supports_options_flow(cls, config_entry: ConfigEntry) -> bool:
        """Only phones have options."""
        return config_entry.data.get(CONF_KIND) != KIND_HOUSEHOLD

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose what to add."""
        if any(
            entry.unique_id == HOUSEHOLD_UNIQUE_ID
            for entry in self._async_current_entries(include_ignore=False)
        ):
            return await self.async_step_phone()
        return self.async_show_menu(step_id="user", menu_options=["phone", "household"])

    async def async_step_household(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add the household overview."""
        await self.async_set_unique_id(HOUSEHOLD_UNIQUE_ID)
        self._abort_if_unique_id_configured()
        title = "Haushalt" if self.hass.config.language.startswith("de") else "Household"
        return self.async_create_entry(title=title, data={CONF_KIND: KIND_HOUSEHOLD})

    async def async_step_phone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name the phone, link a person, confirm the address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            url = _normalize_url(user_input[CONF_URL])
            if url is None:
                errors[CONF_URL] = "invalid_url"
            else:
                self._data = {
                    CONF_KIND: KIND_PHONE,
                    CONF_NAME: user_input[CONF_NAME].strip(),
                    CONF_URL: url,
                    CONF_WEBHOOK_ID: webhook.async_generate_id(),
                    CONF_SECRET: secrets.token_urlsafe(24),
                }
                self._person = user_input.get(CONF_PERSON)
                return await self.async_step_pair()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Optional(CONF_PERSON): PERSON_SELECTOR,
                vol.Required(CONF_URL, default=_default_url(self.hass)): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.URL)
                ),
            }
        )
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(step_id="phone", data_schema=schema, errors=errors)

    async def async_step_pair(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the QR code and wait for the phone's first message."""
        webhook_id = self._data[CONF_WEBHOOK_ID]
        if not self._listening:
            webhook.async_register(
                self.hass,
                DOMAIN,
                "WakeLink pairing",
                webhook_id,
                self._async_handle_pairing,
                local_only=True,
                allowed_methods=["POST"],
            )
            self._listening = True

        errors: dict[str, str] = {}
        if user_input is not None:
            if self._received is None:
                errors["base"] = "not_connected"
            else:
                # Hand over to the entry, which registers the same webhook
                self._stop_listening()
                self.hass.data.setdefault(DOMAIN, {}).setdefault(DATA_PENDING, {})[
                    webhook_id
                ] = self._received
                await self.async_set_unique_id(webhook_id)
                options = {CONF_PERSON: self._person} if self._person else {}
                return self.async_create_entry(
                    title=self._data[CONF_NAME], data=self._data, options=options
                )

        link = pairing_link(self._data)
        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema(
                {
                    vol.Optional("qr_code"): QrCodeSelector(
                        QrCodeSelectorConfig(
                            data=link,
                            scale=5,
                            error_correction_level=QrErrorCorrectionLevel.QUARTILE,
                        )
                    )
                }
            ),
            description_placeholders={"link": link},
            errors=errors,
        )

    async def _async_handle_pairing(
        self, hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        try:
            self._received = validate_message(await request.json())
        except (ValueError, InvalidMessage) as err:
            return web.json_response({"ok": False, "error": str(err)}, status=400)
        return web.json_response({"ok": True})

    def _stop_listening(self) -> None:
        if self._listening:
            webhook.async_unregister(self.hass, self._data[CONF_WEBHOOK_ID])
            self._listening = False

    @callback
    def async_remove(self) -> None:
        """Flow closed without pairing: forget the webhook again."""
        self._stop_listening()


class PhoneOptionsFlow(OptionsFlow):
    """Link a phone to a person."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the person."""
        if user_input is not None:
            person = user_input.get(CONF_PERSON)
            return self.async_create_entry(data={CONF_PERSON: person} if person else {})

        schema = self.add_suggested_values_to_schema(
            vol.Schema({vol.Optional(CONF_PERSON): PERSON_SELECTOR}),
            self.config_entry.options,
        )
        return self.async_show_form(step_id="init", data_schema=schema)
