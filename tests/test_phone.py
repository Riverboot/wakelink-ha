"""Messages from a phone and what they do to its entities."""

from __future__ import annotations

from datetime import timedelta

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .conftest import PostMessage, event, message

NEXT_ALARM = "sensor.pixel_next_alarm"
STATUS = "sensor.pixel_alarm_status"
SNOOZE_ROUND = "sensor.pixel_snooze_round"
LAST_SEEN = "sensor.pixel_last_contact"
ALARM_SET = "binary_sensor.pixel_alarm_set"
PROBLEM = "binary_sensor.pixel_alarm_readiness"
CALENDAR = "calendar.pixel_alarms"
EVENT = "event.pixel_alarm"


async def test_entities_before_first_message(hass: HomeAssistant, pixel: MockConfigEntry) -> None:
    """A new phone has entities right away, with nothing known yet."""
    assert hass.states.get(NEXT_ALARM).state == "unknown"
    assert hass.states.get(STATUS).state == "idle"
    assert hass.states.get(PROBLEM).state == "unknown"


async def test_state_fills_entities(
    hass: HomeAssistant, pixel: MockConfigEntry, post: PostMessage
) -> None:
    """A state message sets next alarm, readiness and the alarm list."""
    response = await post(message("state.json"))
    assert response.status == 200
    assert await response.json() == {"ok": True}

    next_alarm = hass.states.get(NEXT_ALARM)
    assert next_alarm.state == "2026-11-25T05:30:00+00:00"
    assert next_alarm.attributes["label"] == "Arbeit"
    assert next_alarm.attributes["alarm_id"] == 1
    assert len(next_alarm.attributes["alarms"]) == 2

    assert hass.states.get(STATUS).state == "idle"
    assert hass.states.get(SNOOZE_ROUND).state == "0"
    assert hass.states.get(LAST_SEEN).state == "2026-11-24T20:00:00+00:00"
    assert hass.states.get(ALARM_SET).state == "on"
    assert hass.states.get(ALARM_SET).attributes["enabled_count"] == 1

    problem = hass.states.get(PROBLEM)
    assert problem.state == "off"
    assert problem.attributes["issues"] == []
    assert problem.attributes["warnings"] == ["battery_restricted"]


async def test_device_reports_model_and_version(
    hass: HomeAssistant, pixel: MockConfigEntry, post: PostMessage
) -> None:
    """The device page shows what the app reports."""
    from homeassistant.helpers import device_registry as dr

    await post(message("state.json"))
    [device] = dr.async_entries_for_config_entry(dr.async_get(hass), pixel.entry_id)
    assert device.name == "Pixel"
    assert device.model == "Pixel 9 Pro XL"
    assert device.manufacturer == "Google"
    assert device.sw_version == "1.1.0"


async def test_critical_issue_is_a_problem(
    hass: HomeAssistant, pixel: MockConfigEntry, post: PostMessage
) -> None:
    """A blocked alarm screen turns the readiness sensor on."""
    await post(
        message(
            "state.json",
            ready=False,
            issues=[{"key": "full_screen_blocked", "critical": True}],
        )
    )
    problem = hass.states.get(PROBLEM)
    assert problem.state == "on"
    assert problem.attributes["issues"] == ["full_screen_blocked"]


async def test_older_state_is_ignored(
    hass: HomeAssistant, pixel: MockConfigEntry, post: PostMessage
) -> None:
    """A snapshot that arrives late must not undo a newer one."""
    await post(message("state.json", seq=50))
    await post(message("state.json", seq=49, upcoming=[], alarms=[]))
    assert hass.states.get(NEXT_ALARM).state == "2026-11-25T05:30:00+00:00"
    assert hass.states.get(ALARM_SET).state == "on"


async def test_new_epoch_resets_the_counter(
    hass: HomeAssistant, pixel: MockConfigEntry, post: PostMessage
) -> None:
    """After pairing again, the app counts from the start."""
    await post(message("state.json", seq=500))
    await post(message("state.json", seq=1, epoch="new", upcoming=[], alarms=[]))
    assert hass.states.get(NEXT_ALARM).state == "unknown"
    assert hass.states.get(ALARM_SET).state == "off"


async def test_wake_up_sequence(
    hass: HomeAssistant, pixel: MockConfigEntry, post: PostMessage
) -> None:
    """Ring, snooze, ring again, switch off."""
    await post(message("state.json"))

    await post(event("triggered", 42))
    status = hass.states.get(STATUS)
    assert status.state == "ringing"
    assert status.attributes["alarm_name"] == "Arbeit"
    assert hass.states.get(EVENT).attributes["event_type"] == "triggered"

    await post(event("snoozed", 43, snooze_minutes=7, snooze_count=1))
    status = hass.states.get(STATUS)
    assert status.state == "snoozed"
    assert status.attributes["snoozed_until"] == "2026-11-24T20:07:00+00:00"
    assert hass.states.get(SNOOZE_ROUND).state == "1"
    assert hass.states.get(EVENT).attributes["snooze_minutes"] == 7

    await post(event("triggered", 44))
    assert hass.states.get(STATUS).state == "ringing"
    assert hass.states.get(SNOOZE_ROUND).state == "1"

    await post(event("dismissed", 45, reason="user"))
    assert hass.states.get(STATUS).state == "idle"
    assert hass.states.get(SNOOZE_ROUND).state == "0"
    assert hass.states.get(EVENT).attributes["reason"] == "user"


async def test_replaced_alarm_dismissal_arriving_late(
    hass: HomeAssistant, pixel: MockConfigEntry, post: PostMessage
) -> None:
    """Alarm 2 replaces alarm 1; alarm 1's 'dismissed' must not stop alarm 2."""
    await post(event("triggered", 42, alarm_id=1))
    await post(event("triggered", 43, alarm_id=2, alarm_name="Zweiter"))
    await post(event("dismissed", 44, alarm_id=1, reason="replaced"))
    status = hass.states.get(STATUS)
    assert status.state == "ringing"
    assert status.attributes["alarm_name"] == "Zweiter"
    assert hass.states.get(EVENT).attributes["reason"] == "replaced"

    await post(event("dismissed", 45, alarm_id=2, reason="user"))
    assert hass.states.get(STATUS).state == "idle"


async def test_duplicate_event_fires_once(
    hass: HomeAssistant, pixel: MockConfigEntry, post: PostMessage
) -> None:
    """The same event sent twice reaches automations once."""
    fired = []
    hass.bus.async_listen(
        "state_changed",
        lambda e: fired.append(e) if e.data["entity_id"] == EVENT else None,
    )
    await post(event("triggered", 42))
    await post(event("triggered", 42))
    assert len(fired) == 1


async def test_test_event_leaves_status(
    hass: HomeAssistant, pixel: MockConfigEntry, post: PostMessage
) -> None:
    """The test buttons in the app reach automations but change nothing."""
    await post(event("triggered", 42, test=True))
    assert hass.states.get(STATUS).state == "idle"
    assert hass.states.get(EVENT).attributes["test"] is True


async def test_cancelled_snooze_reported_by_state(
    hass: HomeAssistant, pixel: MockConfigEntry, post: PostMessage
) -> None:
    """Cancelling a snooze has no event; the next snapshot says idle."""
    await post(event("snoozed", 42, snooze_minutes=10, snooze_count=1))
    await post(message("state.json", seq=43, status="idle"))
    assert hass.states.get(STATUS).state == "idle"
    assert hass.states.get(SNOOZE_ROUND).state == "0"


async def test_older_snapshot_does_not_override_event_status(
    hass: HomeAssistant, pixel: MockConfigEntry, post: PostMessage
) -> None:
    """A snapshot built before the alarm rang must not reset the status."""
    await post(message("state.json", seq=60))
    await post(event("triggered", 70))
    # Sent after the event, but numbered before it: alarms apply, status not
    await post(message("state.json", seq=65, status="idle", upcoming=[]))
    assert hass.states.get(STATUS).state == "ringing"
    assert hass.states.get(NEXT_ALARM).state == "unknown"


async def test_invalid_messages_are_rejected(
    hass: HomeAssistant, pixel: MockConfigEntry, post: PostMessage
) -> None:
    """Wrong version, type or event: HTTP 400, nothing changes."""
    for bad in (
        message("state.json", v=1),
        message("state.json", type="hello"),
        message("state.json", seq="7"),
        event("exploded", 42),
        [],
    ):
        response = await post(bad)
        assert response.status == 400
    assert hass.states.get(NEXT_ALARM).state == "unknown"


async def test_next_alarm_moves_on_when_time_passes(
    hass: HomeAssistant, pixel: MockConfigEntry, post: PostMessage, freezer
) -> None:
    """Even without a new message, the next alarm advances after it rang."""
    await post(message("state.json"))
    freezer.move_to("2026-11-25T05:31:00+00:00")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert hass.states.get(NEXT_ALARM).state == "2026-11-26T05:30:00+00:00"


async def test_calendar_lists_upcoming_alarms(
    hass: HomeAssistant, pixel: MockConfigEntry, post: PostMessage
) -> None:
    """Both upcoming alarms are calendar events."""
    await post(message("state.json"))
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {"entity_id": CALENDAR, "duration": {"days": 3}},
        blocking=True,
        return_response=True,
    )
    events = response[CALENDAR]["events"]
    assert [item["start"] for item in events] == [
        "2026-11-25T06:30:00+01:00",
        "2026-11-26T06:30:00+01:00",
    ]
    assert events[0]["summary"] == "Arbeit"
    assert hass.states.get(CALENDAR).attributes["message"] == "Arbeit"


async def test_state_survives_restart(
    hass: HomeAssistant, pixel: MockConfigEntry, post: PostMessage
) -> None:
    """Reloading keeps the last known values instead of 'unknown'."""
    await post(message("state.json"))
    await post(event("snoozed", 42, snooze_minutes=7, snooze_count=2))

    assert await hass.config_entries.async_reload(pixel.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(NEXT_ALARM).state == "2026-11-25T05:30:00+00:00"
    assert hass.states.get(STATUS).state == "snoozed"
    assert hass.states.get(SNOOZE_ROUND).state == "2"

    # And the seq tracking survived: the same event is still a duplicate
    await post(event("dismissed", 42))
    assert hass.states.get(STATUS).state == "snoozed"


async def test_unload_stops_webhook(
    hass: HomeAssistant, pixel: MockConfigEntry, post: PostMessage
) -> None:
    """After unloading, messages no longer reach the phone."""
    assert await hass.config_entries.async_unload(pixel.entry_id)
    await hass.async_block_till_done()
    response = await post(message("state.json"))
    assert await response.text() == ""  # Home Assistant's answer for unknown webhooks


async def test_snooze_time_from_event(
    hass: HomeAssistant, pixel: MockConfigEntry, post: PostMessage, freezer
) -> None:
    """snoozed_until counts from when the event arrived."""
    freezer.tick(timedelta(minutes=5))
    await post(event("snoozed", 42, snooze_minutes=10, snooze_count=1))
    assert hass.states.get(STATUS).attributes["snoozed_until"] == "2026-11-24T20:15:00+00:00"
