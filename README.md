# Gartan Availability (Home Assistant custom integration)

For Gartan's **Availability** tool. Domain `gartan_availability`, so integrations for
other Gartan tools can sit alongside it.

Reads the Gartan availability schedule and exposes it to Home Assistant: a calendar
per appliance, your own on-call calendar, current-state and next-change sensors, and
a compact whole-week schedule for your own templates and automations.

Nothing station- or person-specific is built in:
- the station comes from your account
- your own row is detected automatically
- appliances are picked from the rows Gartan returns
- crewing rules, role grouping and booking suggestions are left to your own
  templates (see [Using the schedule sensor](#using-the-schedule-sensor))

## Install

Via HACS: add this repository as a custom repository (type: integration), install,
restart. Or copy `custom_components/gartan_availability/` to `/config/custom_components/gartan_availability/`
and restart.

Then go to Settings > Devices & services > Add integration > Gartan Availability.
Setup asks for the Gartan site URL, username and password, then:
1. reads the stations your login can see. If there's more than one, it asks which.
2. fetches today's schedule and finds your row. If that fails, it asks you to pick it.
3. asks which appliances get their own entities. All of them are selected by default.

## Entities

Entity ids come from the device names. `<appliance>` is the Gartan row label in
lower case, e.g. `kt52p1`. You can rename any entity in the UI.

**Gartan Availability** (station and you)

| Entity | Meaning |
|---|---|
| `calendar.gartan_availability_on_call` | Your on-call periods |
| `binary_sensor.gartan_availability_on_call` | You're on call now |
| `sensor.gartan_availability_next_on_call` / `sensor.gartan_availability_next_off_call` | Timestamps |
| `sensor.gartan_availability_who_is_on` | Number of people on now; attribute `people` (name, imported, skills) |
| `sensor.gartan_availability_schedule` | The whole known week (see below) |
| `binary_sensor.gartan_availability_needs_attention` | Any issue (also raised in Settings > Repairs) |
| `sensor.gartan_availability_last_scrape` | Diagnostic |

**Gartan Availability `<APPLIANCE>`** (one device per selected appliance)

| Entity | Meaning |
|---|---|
| `calendar.gartan_availability_<appliance>` | On-the-run periods (Available or Alternate), plus "out on a call" |
| `binary_sensor.gartan_availability_<appliance>_on_the_run` | On the run now; attribute `status` |
| `binary_sensor.gartan_availability_<appliance>_deployed` | Out on a call (Off Station) now |
| `sensor.gartan_availability_<appliance>_next_on_the_run` / `_next_off_the_run` | Timestamps; unknown while out on a call |

"Next off" timestamps are unknown when a run reaches the end of the known 7 days.

## Using the schedule sensor

`sensor.gartan_availability_schedule` has these attributes. They are excluded from the recorder,
so they don't bloat the database.

```yaml
start: "2026-11-02T00:00:00+00:00"   # slot 0 = local midnight today
slot_minutes: 15
slots: 672                           # 7 days
appliances:
  KT52P1: "OOOOAAAALLLL…"            # one char per slot (see legend)
people:
  - name: "SURNAME, I"
    me: false
    imported: false                  # true for rows below Gartan's import divider
    skills: ["IC1", "BA"]
    expiring: ["BA"]                 # skills Gartan shows in red
    slots: "1111000bbbb…"            # 1 on, 0 off, b bookable (unbooked, can book)
legend:
  appliance: {A: available, L: alternate, O: off_the_run, S: off_station, "?": unknown}
  person: {"1": on, "0": off, b: bookable}
```

Slot `i` covers `start + i × 15 min`. The index for now:

```jinja
{% set s = state_attr('sensor.gartan_availability_schedule', 'start') | as_datetime %}
{% set i = ((now() - s).total_seconds() // 900) | int %}
```

For example, the people on now who hold a given skill:

```jinja
{{ state_attr('sensor.gartan_availability_schedule', 'people')
   | selectattr('slots', 'search', '^.{' ~ i ~ '}1')
   | selectattr('skills', 'contains', 'IC1')
   | map(attribute='name') | list }}
```

While an appliance is out on a call, Gartan marks every future slot Off Station.
The integration replaces those future slots with the last schedule seen before the
call-out (kept in `.storage`), so the export and calendars stay useful.

## Behaviour

- Fetches today every 5 minutes and the full 7 days roughly hourly, at 15-minute
  resolution.
- Appliance status comes from the appliance cell's title. Only Available, Alternate,
  Off the Run and Off Station have been seen. Anything else counts as not on the run
  and raises an attention issue with the exact text.
- A person cell counts as on when it is white (contracted) or booked Available or
  Co-responder. "Bookable" means a blue-dash cell with no booking. Unknown booking
  codes count as not available and raise an issue.
- For each new oddity, and for each call-out, a raw copy of the response is saved to
  `/config/gartan_availability_captures/` (max 20). They contain names, so don't share them as-is.

## Tests

    python -m unittest discover -s tests -t .
    python tools/replay.py capture.json 2026-11-02 --export

Fixtures in `tests/` are synthetic. Scrub names and payroll numbers from real
captures before committing them.
