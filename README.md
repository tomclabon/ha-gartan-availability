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
| `image.gartan_availability_crew` | Who is on now (until when) and off (from when), soonest change first |
| `binary_sensor.gartan_availability_needs_attention` | Any issue (also raised in Settings > Repairs) |
| `sensor.gartan_availability_last_scrape` | Diagnostic |

**Gartan Availability `<APPLIANCE>`** (one device per selected appliance)

| Entity | Meaning |
|---|---|
| `calendar.gartan_availability_<appliance>` | On-the-run periods (Available or Alternate), plus "out on a call" |
| `binary_sensor.gartan_availability_<appliance>_on_the_run` | On the run now; attribute `status` |
| `binary_sensor.gartan_availability_<appliance>_deployed` | Out on a call (Off Station) now |
| `sensor.gartan_availability_<appliance>_next_on_the_run` / `_next_off_the_run` | Timestamps; unknown while out on a call |
| `image.gartan_availability_<appliance>_week` | Week-at-a-glance picture: the appliance and you, 7 days |

"Next off" timestamps are unknown when a run reaches the end of the known 7 days.

## History: hours against contract, and call-outs

The integration keeps its own history ledger, rebuilt from Gartan. Your Home
Assistant recorder history isn't needed.

**Loading**
- On first setup it loads, in the background and throttled (about one request
  every 2.5 s):
  - your weekly contract figures, two weeks per request
  - then every past day, for call-outs and your on-call time
- It goes back to when you started, up to the configured number of years
  (default 5). About three years takes roughly 50 minutes, once.
- Progress is saved as it goes. A restart resumes rather than starting again.
- Every night at 03:30 the last 4 weeks and 14 days are re-fetched, to catch late
  corrections.
- **Rebuild history** (button) clears the ledger and loads it all again.
- `sensor.gartan_availability_history` shows the progress.

**Hours** (Gartan's weekly figures: contract, and actual in brackets), rounded
to 15 minutes. Each period has an Actual and a Contract sensor:

| Period | Actual | Contract | Covers |
|---|---|---|---|
| This week | `sensor.gartan_availability_hours_this_week` | `..._contract_hours_this_week` | Monday 00:00 to now (contract pro-rata) |
| Last 4 weeks | `..._hours_last_4_weeks` | `..._contract_hours_last_4_weeks` | previous 4 weeks plus this week so far |
| Last 52 weeks | `..._hours_last_52_weeks` | `..._contract_hours_last_52_weeks` | previous 52 weeks plus this week so far |
| Since start | `..._hours_since_start` | `..._contract_hours_since_start` | every week since you started plus this week so far |

Only completed 15-minute slots count towards this week. Both sensors carry the
attributes `actual`, `contract`, `difference`, `under_contract` and `complete`;
`complete` is false while history is still loading. This week also has
`week_contract` and `week_scheduled`, Gartan's figures for the whole week.

**Call-outs**
- A run of Off Station slots on an appliance counts as one call-out. You count as
  on it if you were on call when it started; Gartan doesn't record who rode.
- Per appliance there are `sensor.gartan_availability_<appliance>_call_outs_<period>`
  and `..._my_call_outs_<period>`, for the same four periods.
- Past call-outs appear on the appliance calendar ("out on a call"). The ones you
  were on call for also appear on `calendar.gartan_availability_on_call` as
  "Call-out <appliance>".

**Long-term statistics.** For the Statistics graph card, the ledger is also
written to these statistics (`b<id>` is your brigade id):
- `gartan_availability:b<id>_on_call_hours` (daily)
- `..._contract_hours` and `..._actual_hours` (weekly)
- `..._<appliance>_call_outs` and `..._<appliance>_my_call_outs` (daily)

**Options**
- Years of history to load (0 turns it off).
- Your employee id for the two-week view. It's normally read from the schedule,
  so only set it if `sensor.gartan_availability_history` says it's missing.

## Home-screen widget

`image.gartan_availability_<appliance>_week` draws 7 rows (today plus 6 days), each
a single bar across 00-24 with a faint grey mark every hour, coloured by slot:

| Colour | Meaning |
|---|---|
| Green | Appliance on the run and you on call |
| Blue | Appliance on, you not |
| Amber | You on, appliance not |
| Pink | Appliance out on a call |
| Dark grey | Neither |
| Light grey | Appliance status unknown, or no data |

Today's past hours are dimmed and a thick white line marks now. The header shows
"Updated HH:MM", which is when the picture was drawn. If today's data hasn't been
fetched for 15 minutes, it shows "Data HH:MM" in red instead. Under each day label,
"Updated HH:MM" shows that day's last fetch. Today is refreshed every 5 minutes and
the other days about hourly; a time turns red once it's over 15 minutes old for
today or 2 hours old for other days.

`image.gartan_availability_crew` lists who is on now with when they go off, and who
is off with when they come on, each sorted by soonest change. You're shown in amber,
imported rows are marked "(import)", skills are shown small after each name, and
changes within the hour are highlighted. "beyond week" means on past the known
7 days; "not this week" means not on at all in that time.

On Android, add the Home Assistant app's **Picture** widget and pick that entity.
The picture is drawn fresh each time it's fetched. The widget fetches about hourly
and whenever you tap it (set the tap action to Refresh).

## Notifications blueprint

`blueprints/automation/gartan_availability/heads_up.yaml` sends:
- "On call in 15 minutes", with when you come off and whether the appliance is on
  then (or out on a call)
- "<Appliance> on in 15 minutes", only if you'll be on call then and it isn't out on
  a call
- an alert when the integration has needed attention for 10 minutes

Import it via Settings > Automations & scenes > Blueprints > Import blueprint, using
the file's GitHub URL. Then create an automation from it and pick the calendars,
sensors and phone.

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

## Refresh settings

These are on the **Gartan Availability** device page, under Configuration. Changes
apply immediately with no reload, survive restarts, and can be set from
automations (for example, faster polling while the appliance is out):

| Setting | Default | Range | What it does |
|---|---|---|---|
| Today refresh | 5 min | 2–60 min | How often today's schedule is fetched |
| Week refresh | 60 min | 15–360 min | How often the other 6 days are fetched (checked at each today refresh) |
| History request gap | 2.5 s | 1–60 s | Pause between history requests |

The "stale" warnings (attention sensor, red times on the images) scale with these:
today is stale after 3 × Today refresh (at least 15 min), and other days after
2 × Week refresh (at least 2 h).

## Behaviour

- Fetches today every 5 minutes and the full 7 days hourly, at 15-minute resolution
  (see Refresh settings).
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
