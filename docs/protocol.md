# WakeLink protocol, version 2

How the WakeLink Android app talks to this integration. The app is the only
source of truth for alarms: it decides when something rings, so it also
computes every date it reports. The integration never re-derives schedules.

## Pairing

Adding a phone in Home Assistant creates a random webhook ID and a secret and
shows them as a QR code. The code holds a link:

```
wakelink://pair?v=1&url=<home assistant url>&id=<webhook id>&secret=<secret>&name=<phone name>
```

| Parameter | Meaning |
|---|---|
| `v` | Link format version, currently `1` |
| `url` | Base URL of Home Assistant as the phone reaches it, e.g. `http://192.168.1.20:8123` |
| `id` | Webhook ID. Whoever knows it can post data, so the app treats it like a password |
| `secret` | Reserved for commands from Home Assistant to the app (phase 2) |
| `name` | Name given in Home Assistant, shown in the app |

After scanning, the app sends a `state` message right away. The setup dialog in
Home Assistant waits for that message before it creates the entry, which also
proves that the phone reaches Home Assistant.

## Transport

`POST <url>/api/webhook/<id>` with a JSON body. The webhook only accepts
requests from the local network. The integration answers `{"ok": true}`; any
other answer (including an empty body from an unknown webhook) means the
message was not taken.

## Envelope

Every message carries:

| Field | Type | Meaning |
|---|---|---|
| `v` | int | Always `2` |
| `type` | string | `state` or `event` |
| `seq` | int | Increases with every message the app sends |
| `epoch` | string | Random ID chosen at pairing. A new epoch resets `seq` tracking |
| `sent_at` | ISO 8601 | When the app sent the message |
| `device` | object | `model`, `manufacturer`, `app_version` |

Messages may arrive late or twice. The integration applies a `state` only if
its `seq` is higher than the last applied state, and fires each event `seq`
at most once.

## `state`: the full picture

Sent after every change, when the phone joins the home Wi-Fi, after a reboot
and hourly as a safety net, but only when its content changed since the last
successful send.

```json
{
  "v": 2,
  "type": "state",
  "seq": 41,
  "epoch": "3f9c2a7d",
  "sent_at": "2026-11-24T21:14:03+01:00",
  "device": {"model": "Pixel 9 Pro XL", "manufacturer": "Google", "app_version": "1.1.0"},
  "status": "idle",
  "ringing": null,
  "snoozed_until": null,
  "snooze_round": 0,
  "alarms": [
    {
      "id": 1, "hour": 6, "minute": 30, "time": "06:30", "label": "Arbeit",
      "enabled": true, "one_time": false, "days": [1, 2, 3, 4, 5],
      "next_trigger": "2026-11-25T06:30:00+01:00"
    }
  ],
  "upcoming": [
    {"alarm_id": 1, "label": "Arbeit", "at": "2026-11-25T06:30:00+01:00", "nap": false}
  ],
  "ready": true,
  "issues": [{"key": "battery_restricted", "critical": false}]
}
```

| Field | Meaning |
|---|---|
| `status` | `idle`, `ringing` or `snoozed` |
| `ringing` | `{alarm_id, label, time}` while ringing, else `null` |
| `snoozed_until` | End of the current snooze, else `null` |
| `snooze_round` | Snoozes in the current wake-up, `0` when idle |
| `alarms` | Every alarm, enabled or not. `days`: 1 = Monday … 7 = Sunday, empty = one-time |
| `upcoming` | Every time an alarm will ring in the next 14 days, sorted. Snoozes are not included |
| `ready` | `false` if something stops the alarm from working (critical issue) |
| `issues` | `notifications_blocked`, `full_screen_blocked`, `alarm_volume_muted`, `total_silence` (critical) and `battery_restricted` (not critical) |

## `event`: something just happened

```json
{
  "v": 2,
  "type": "event",
  "seq": 42,
  "epoch": "3f9c2a7d",
  "sent_at": "2026-11-25T06:30:01+01:00",
  "device": {"model": "Pixel 9 Pro XL", "manufacturer": "Google", "app_version": "1.1.0"},
  "event": "snoozed",
  "alarm_id": 1,
  "alarm_name": "Arbeit",
  "time": "06:30",
  "snooze_minutes": 7,
  "snooze_count": 2
}
```

| `event` | Extra fields | Status afterwards |
|---|---|---|
| `triggered` | | `ringing` |
| `snoozed` | `snooze_minutes`, `snooze_count` | `snoozed` |
| `dismissed` | `reason`: `user`, `timeout`, or `replaced` (a second alarm went off while this one rang) | `idle`, unless a different alarm is ringing by now |
| `nap_scheduled` | `scheduled_for` | unchanged |
| `pre_alarm` | `scheduled_for`, `minutes_before` | unchanged |

Events with `"test": true` come from the test buttons in the app. They are
passed on to automations but never change the status.

Events are not queued: an alarm event from two hours ago would only trigger
nonsense. A cancelled snooze has no event of its own; the following `state`
reports `idle`.
