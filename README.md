# WakeLink for Home Assistant

Brings the alarms of the WakeLink Android alarm clock into Home Assistant: when the next alarm rings, whether it
is ringing or snoozing right now, and whether the phone is able to ring at all.
No YAML, no webhook IDs to type: add the integration, scan a code, done.

## What you get

For every phone, one device with:

| Entity | What it tells |
|---|---|
| Next alarm | Timestamp of the next alarm. Attributes: `label`, `alarm_id`, `nap`, and `alarms` with the full list |
| Alarm status | `idle`, `ringing` or `snoozed` |
| Snooze round | How often the current alarm was snoozed |
| Alarm set | On while at least one alarm is switched on |
| Alarm readiness | A problem sensor: on if notifications, the full-screen alarm or the alarm volume are blocked. Attribute `warnings` lists issues that only delay the sync |
| Alarms (calendar) | Every alarm of the next 14 days |
| Alarm (event) | Fires on `triggered`, `snoozed`, `dismissed`, `nap_scheduled`, `pre_alarm` |
| Last contact | When the phone last reported (diagnostic) |

The optional **household** adds:

| Entity | What it tells |
|---|---|
| Earliest alarm | The earliest upcoming alarm of everyone at home |
| Someone is waking up | An alarm at home is ringing or snoozing |
| Everyone awake | Everyone at home whose alarm rang today has switched it off |

Link a phone to a person and the household only counts it while that person
is at home, so a trip does not heat the bathroom at 5 am.

## Examples

Light up 20 minutes before the alarm, with any lead you like:

```yaml
triggers:
  - trigger: calendar
    event: start
    entity_id: calendar.pixel_alarms
    offset: "-0:20:0"
```

Lights on after the third snooze:

```yaml
triggers:
  - trigger: state
    entity_id: event.pixel_alarm
conditions:
  - condition: template
    value_template: >
      {{ trigger.to_state.attributes.event_type == 'snoozed'
         and trigger.to_state.attributes.snooze_count >= 3 }}
```

Morning routine once everyone is up:

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.household_everyone_awake
    to: "on"
```

## Installation

1. HACS → Integrations → ⋮ → Custom repositories → add this repository as
   *Integration*, then install **WakeLink** and restart Home Assistant.
2. Settings → Devices & services → Add integration → **WakeLink** →
   *Connect a phone*.
3. In the app: Settings → Home Assistant → **Connect**, scan the code.
4. Optionally add the *household overview* the same way.

Home Assistant 2026.10 or newer. The phone reports over your home Wi-Fi only.

## Protocol

The app and the integration talk over one webhook per phone, see
[docs/protocol.md](docs/protocol.md).

## Development

```bash
pip install -r requirements_test.txt
python -m pytest
```
