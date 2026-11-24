"""A paired phone: receives the app's messages and keeps its last known state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, timedelta
import logging
from typing import Any

from aiohttp import web

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_PERSON,
    DATA_PENDING,
    DOMAIN,
    EVENT_ATTRIBUTES,
    EVENT_DISMISSED,
    EVENT_SNOOZED,
    EVENT_TRIGGERED,
    EVENT_TYPES,
    MSG_EVENT,
    MSG_STATE,
    PROTOCOL_VERSION,
    RECENT_EVENT_SEQS,
    SAVE_DELAY,
    SIGNAL_PHONES_CHANGED,
    STATUS_IDLE,
    STATUS_RINGING,
    STATUS_SNOOZED,
    STATUSES,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


class InvalidMessage(ValueError):
    """The app sent something that is not a valid protocol message."""


def validate_message(message: Any) -> dict[str, Any]:
    """Check the envelope of a message, see docs/protocol.md."""
    if not isinstance(message, dict):
        raise InvalidMessage("message is not a JSON object")
    if message.get("v") != PROTOCOL_VERSION:
        raise InvalidMessage(f"unsupported protocol version {message.get('v')!r}")
    if message.get("type") not in (MSG_STATE, MSG_EVENT):
        raise InvalidMessage(f"unknown message type {message.get('type')!r}")
    seq = message.get("seq")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
        raise InvalidMessage("seq must be a non-negative integer")
    if message["type"] == MSG_EVENT and message.get("event") not in EVENT_TYPES:
        raise InvalidMessage(f"unknown event {message.get('event')!r}")
    return message


def parse_time(value: Any) -> datetime | None:
    """Parse an ISO timestamp from the app into UTC. Naive values are local time."""
    if not isinstance(value, str):
        return None
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.as_utc(parsed)


@dataclass(frozen=True)
class Occurrence:
    """One time an alarm will ring."""

    alarm_id: int | None
    label: str
    at: datetime
    nap: bool


@dataclass
class PhoneState:
    """Everything known about a phone. Stored as is, so it survives restarts."""

    epoch: str | None = None
    state_seq: int = -1
    status_seq: int = -1
    recent_event_seqs: list[int] = field(default_factory=list)
    device: dict[str, Any] = field(default_factory=dict)
    alarms: list[dict[str, Any]] = field(default_factory=list)
    upcoming: list[dict[str, Any]] = field(default_factory=list)
    status: str = STATUS_IDLE
    ringing: dict[str, Any] | None = None
    snoozed_until: str | None = None
    snooze_round: int = 0
    ready: bool | None = None
    issues: list[dict[str, Any]] = field(default_factory=list)
    last_seen: str | None = None
    ring_started_at: str | None = None
    dismissed_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PhoneState:
        """Restore from storage, ignoring keys a newer version may have added."""
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})


class Phone:
    """Runtime data of a phone config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self.state = PhoneState()
        self.active = False
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, storage_key(entry.entry_id)
        )
        self._occurrences: list[Occurrence] = []
        self._listeners: list[Callable[[], None]] = []
        self._event_listeners: list[Callable[[str, dict[str, Any]], None]] = []
        self._unsub_rollover: CALLBACK_TYPE | None = None

    @property
    def webhook_id(self) -> str:
        """Webhook the app posts to."""
        return self.entry.data[CONF_WEBHOOK_ID]

    @property
    def person(self) -> str | None:
        """Person entity this phone belongs to, if linked."""
        return self.entry.options.get(CONF_PERSON) or None

    @property
    def device_info(self) -> DeviceInfo:
        """Device of this phone."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=self.entry.title,
            manufacturer=self.state.device.get("manufacturer"),
            model=self.state.device.get("model"),
            sw_version=self.state.device.get("app_version"),
        )

    # ---- lifecycle ------------------------------------------------------

    async def async_load(self) -> None:
        """Restore the last known state."""
        if (stored := await self._store.async_load()) is not None:
            self.state = PhoneState.from_dict(stored)
        self._rebuild_occurrences()

    @callback
    def async_start(self) -> None:
        """Start receiving messages."""
        webhook.async_register(
            self.hass,
            DOMAIN,
            self.entry.title,
            self.webhook_id,
            self._async_handle_webhook,
            local_only=True,
            allowed_methods=["POST"],
        )
        self.active = True
        # The message that completed pairing arrived before this entry existed
        pending = self.hass.data.get(DOMAIN, {}).get(DATA_PENDING, {})
        if (message := pending.pop(self.webhook_id, None)) is not None:
            try:
                self.async_process(message)
            except InvalidMessage as err:
                _LOGGER.warning("Ignored pairing message: %s", err)
        self._schedule_rollover()
        async_dispatcher_send(self.hass, SIGNAL_PHONES_CHANGED)

    async def async_stop(self) -> None:
        """Stop receiving messages and save the state."""
        self.active = False
        webhook.async_unregister(self.hass, self.webhook_id)
        if self._unsub_rollover is not None:
            self._unsub_rollover()
            self._unsub_rollover = None
        await self._store.async_save(asdict(self.state))
        async_dispatcher_send(self.hass, SIGNAL_PHONES_CHANGED)

    # ---- listeners ------------------------------------------------------

    @callback
    def async_add_listener(self, update: Callable[[], None]) -> CALLBACK_TYPE:
        """Call update whenever the state changes."""
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def async_add_event_listener(
        self, handle: Callable[[str, dict[str, Any]], None]
    ) -> CALLBACK_TYPE:
        """Call handle with every event the app reports."""
        self._event_listeners.append(handle)
        return lambda: self._event_listeners.remove(handle)

    @callback
    def _async_notify(self) -> None:
        for update in list(self._listeners):
            update()
        async_dispatcher_send(self.hass, SIGNAL_PHONES_CHANGED)

    # ---- messages -------------------------------------------------------

    async def _async_handle_webhook(
        self, hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        try:
            message = await request.json()
        except ValueError:
            return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
        try:
            self.async_process(message)
        except InvalidMessage as err:
            _LOGGER.warning("Ignored message from %s: %s", self.entry.title, err)
            return web.json_response({"ok": False, "error": str(err)}, status=400)
        return web.json_response({"ok": True})

    @callback
    def async_process(self, raw: Any) -> None:
        """Apply a message from the app."""
        message = validate_message(raw)
        state = self.state
        now = dt_util.utcnow()

        if message.get("epoch") != state.epoch:
            # Paired again or app data reset: its counter starts over
            state.epoch = message.get("epoch")
            state.state_seq = -1
            state.status_seq = -1
            state.recent_event_seqs = []

        state.last_seen = now.isoformat()
        if isinstance(device := message.get("device"), dict):
            self._update_device(device)

        if message["type"] == MSG_STATE:
            self._apply_state(message)
        else:
            self._apply_event(message, now)

        self._store.async_delay_save(lambda: asdict(self.state), SAVE_DELAY)
        self._async_notify()

    def _update_device(self, device: dict[str, Any]) -> None:
        reported = {
            key: device.get(key) for key in ("model", "manufacturer", "app_version")
        }
        if reported == self.state.device:
            return
        self.state.device = reported
        dr.async_get(self.hass).async_get_or_create(
            config_entry_id=self.entry.entry_id, **self.device_info
        )

    def _apply_state(self, message: dict[str, Any]) -> None:
        state = self.state
        seq = message["seq"]
        if seq <= state.state_seq:
            return  # an older snapshot overtook a newer one

        state.state_seq = seq
        state.alarms = _dict_list(message.get("alarms"))
        state.upcoming = _dict_list(message.get("upcoming"))
        ready = message.get("ready")
        state.ready = ready if isinstance(ready, bool) else None
        state.issues = _dict_list(message.get("issues"))

        status = message.get("status")
        if seq > state.status_seq and status in STATUSES:
            state.status_seq = seq
            if status != STATUS_IDLE and state.status == STATUS_IDLE:
                state.ring_started_at = dt_util.utcnow().isoformat()
            if status == STATUS_IDLE and state.status != STATUS_IDLE:
                state.dismissed_at = dt_util.utcnow().isoformat()
            state.status = status
            ringing = message.get("ringing")
            state.ringing = ringing if isinstance(ringing, dict) else None
            snoozed_until = parse_time(message.get("snoozed_until"))
            state.snoozed_until = snoozed_until.isoformat() if snoozed_until else None
            state.snooze_round = _int(message.get("snooze_round"))

        self._rebuild_occurrences()
        self._schedule_rollover()

    def _apply_event(self, message: dict[str, Any], now: datetime) -> None:
        state = self.state
        seq = message["seq"]
        if seq in state.recent_event_seqs:
            return  # sent twice
        state.recent_event_seqs = [*state.recent_event_seqs, seq][-RECENT_EVENT_SEQS:]

        event_type = message["event"]
        attributes = {key: message[key] for key in EVENT_ATTRIBUTES if key in message}

        if not message.get("test") and seq > state.status_seq:
            self._apply_event_status(event_type, message, now)

        for handle in list(self._event_listeners):
            handle(event_type, attributes)

    def _apply_event_status(
        self, event_type: str, message: dict[str, Any], now: datetime
    ) -> None:
        state = self.state
        if event_type == EVENT_TRIGGERED:
            if state.status == STATUS_IDLE:
                state.ring_started_at = now.isoformat()
            state.status = STATUS_RINGING
            state.ringing = {
                "alarm_id": message.get("alarm_id"),
                "label": message.get("alarm_name"),
                "time": message.get("time"),
            }
            state.snoozed_until = None
        elif event_type == EVENT_SNOOZED:
            state.status = STATUS_SNOOZED
            state.ringing = None
            state.snooze_round = _int(message.get("snooze_count")) or state.snooze_round + 1
            minutes = _int(message.get("snooze_minutes"))
            state.snoozed_until = (
                (now + timedelta(minutes=minutes)).isoformat() if minutes else None
            )
        elif event_type == EVENT_DISMISSED:
            ringing_id = (state.ringing or {}).get("alarm_id")
            dismissed_id = message.get("alarm_id")
            if (
                state.status == STATUS_RINGING
                and ringing_id is not None
                and dismissed_id is not None
                and ringing_id != dismissed_id
            ):
                # A second alarm replaced the first, and the first one's
                # "dismissed" overtook the second one's "triggered"
                return
            state.status = STATUS_IDLE
            state.ringing = None
            state.snoozed_until = None
            state.snooze_round = 0
            state.dismissed_at = now.isoformat()
        else:
            return  # nap_scheduled and pre_alarm do not change the status
        state.status_seq = message["seq"]

    # ---- derived values -------------------------------------------------

    def _rebuild_occurrences(self) -> None:
        occurrences = []
        for item in self.state.upcoming:
            if (at := parse_time(item.get("at"))) is None:
                continue
            alarm_id = item.get("alarm_id")
            occurrences.append(
                Occurrence(
                    alarm_id=alarm_id if isinstance(alarm_id, int) else None,
                    label=str(item.get("label") or ""),
                    at=at,
                    nap=bool(item.get("nap")),
                )
            )
        self._occurrences = sorted(occurrences, key=lambda occurrence: occurrence.at)

    @property
    def occurrences(self) -> list[Occurrence]:
        """Upcoming alarms as last reported, oldest first."""
        return self._occurrences

    def next_occurrence(self, now: datetime | None = None) -> Occurrence | None:
        """The next time this phone will ring.

        Filtered by the current time rather than trusting the app's order: if
        the phone was away from home when an alarm passed, Home Assistant
        still moves on to the next one.
        """
        now = now or dt_util.utcnow()
        return next((occ for occ in self._occurrences if occ.at > now), None)

    @property
    def alarm_set(self) -> bool:
        """At least one alarm is switched on."""
        return any(alarm.get("enabled") for alarm in self.state.alarms)

    @property
    def critical_issues(self) -> list[str]:
        """Problems that keep the alarm from working."""
        return [
            str(issue.get("key"))
            for issue in self.state.issues
            if issue.get("critical")
        ]

    @property
    def warnings(self) -> list[str]:
        """Problems that only delay the sync with Home Assistant."""
        return [
            str(issue.get("key"))
            for issue in self.state.issues
            if not issue.get("critical")
        ]

    def rang_on(self, day: date) -> bool:
        """An alarm started ringing on this local day."""
        started = parse_time(self.state.ring_started_at)
        return started is not None and dt_util.as_local(started).date() == day

    @property
    def awake(self) -> bool:
        """The last wake-up ended with the alarm switched off."""
        started = parse_time(self.state.ring_started_at)
        dismissed = parse_time(self.state.dismissed_at)
        return (
            self.state.status == STATUS_IDLE
            and started is not None
            and dismissed is not None
            and dismissed >= started
        )

    # ---- rollover -------------------------------------------------------

    def _schedule_rollover(self) -> None:
        """Refresh entities when the next alarm time has passed."""
        if self._unsub_rollover is not None:
            self._unsub_rollover()
            self._unsub_rollover = None
        if not self.active or (upcoming := self.next_occurrence()) is None:
            return
        self._unsub_rollover = async_track_point_in_utc_time(
            self.hass, self._async_rollover, upcoming.at + timedelta(seconds=1)
        )

    @callback
    def _async_rollover(self, _now: datetime) -> None:
        self._unsub_rollover = None
        self._schedule_rollover()
        self._async_notify()


def storage_key(entry_id: str) -> str:
    """Storage file of a phone entry."""
    return f"{DOMAIN}.{entry_id}"


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)
