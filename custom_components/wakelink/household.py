"""The household: what all paired phones mean together."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_HOME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_PHONES_CHANGED, STATUS_RINGING, STATUS_SNOOZED
from .phone import Occurrence, Phone

# A person in one of these states may be at home
_MAYBE_HOME = {STATE_HOME, STATE_UNKNOWN, STATE_UNAVAILABLE}


class Household:
    """Runtime data of the household config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._persons: frozenset[str] = frozenset()
        self._unsub_persons: CALLBACK_TYPE | None = None
        self._unsub_rollover: CALLBACK_TYPE | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Device that groups the household entities."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=self.entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )

    @callback
    def async_start(self) -> None:
        """Follow phones, persons and the date."""
        self._unsubs.append(
            async_dispatcher_connect(
                self.hass, SIGNAL_PHONES_CHANGED, self._async_phones_changed
            )
        )
        # "Everyone awake" starts over every day
        self._unsubs.append(
            async_track_time_change(
                self.hass, self._async_refresh, hour=0, minute=0, second=5
            )
        )
        self._async_phones_changed()

    @callback
    def async_stop(self) -> None:
        """Stop following."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for unsub in (self._unsub_persons, self._unsub_rollover):
            if unsub is not None:
                unsub()
        self._unsub_persons = None
        self._unsub_rollover = None

    @callback
    def async_add_listener(self, update: Callable[[], None]) -> CALLBACK_TYPE:
        """Call update whenever a household value may have changed."""
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    # ---- phones ---------------------------------------------------------

    def phones(self) -> list[Phone]:
        """All phones that are set up."""
        phones = []
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            phone = getattr(entry, "runtime_data", None)
            if isinstance(phone, Phone) and phone.active:
                phones.append(phone)
        return phones

    def is_present(self, phone: Phone) -> bool:
        """Whether the phone's person may be at home.

        Phones without a linked person always count. So does a person whose
        location is unknown: better to heat the bathroom once too often than
        to leave someone in the cold.
        """
        if phone.person is None:
            return True
        state = self.hass.states.get(phone.person)
        return state is None or state.state in _MAYBE_HOME

    def present_phones(self) -> list[Phone]:
        """Phones of everyone who may be at home."""
        return [phone for phone in self.phones() if self.is_present(phone)]

    # ---- values ---------------------------------------------------------

    def next_alarm(self, now: datetime | None = None) -> tuple[Phone, Occurrence] | None:
        """The earliest upcoming alarm of everyone at home."""
        candidates = [
            (phone, occurrence)
            for phone in self.present_phones()
            if (occurrence := phone.next_occurrence(now)) is not None
        ]
        return min(candidates, key=lambda pair: pair[1].at, default=None)

    @property
    def someone_waking(self) -> bool:
        """An alarm at home is ringing or snoozing."""
        return any(
            phone.state.status in (STATUS_RINGING, STATUS_SNOOZED)
            for phone in self.present_phones()
        )

    @property
    def all_awake(self) -> bool:
        """Everyone at home whose alarm rang today has switched it off."""
        today = dt_util.now().date()
        woken = [phone for phone in self.present_phones() if phone.rang_on(today)]
        return bool(woken) and all(phone.awake for phone in woken)

    # ---- updates --------------------------------------------------------

    @callback
    def _async_phones_changed(self) -> None:
        persons = frozenset(
            phone.person for phone in self.phones() if phone.person is not None
        )
        if persons != self._persons:
            self._persons = persons
            if self._unsub_persons is not None:
                self._unsub_persons()
                self._unsub_persons = None
            if persons:
                self._unsub_persons = async_track_state_change_event(
                    self.hass, list(persons), self._async_person_changed
                )
        self._async_refresh()

    @callback
    def _async_person_changed(self, _event: Event) -> None:
        self._async_refresh()

    @callback
    def _async_refresh(self, _now: datetime | None = None) -> None:
        if self._unsub_rollover is not None:
            self._unsub_rollover()
            self._unsub_rollover = None
        if (upcoming := self.next_alarm()) is not None:
            self._unsub_rollover = async_track_point_in_utc_time(
                self.hass, self._async_refresh, upcoming[1].at + timedelta(seconds=1)
            )
        for update in list(self._listeners):
            update()
