# Gartan Availability (Home Assistant custom integration)

Scrapes the Gartan availability tool and exposes the appliance (52P1) and your own
on-call schedule as calendars, plus sensors for next on/off, who's on, and
bookable windows. Replaces the Node-RED flow.

Stage 1 and 2 only: **no notifications, widgets or automations yet.**

## Install

Copy `custom_components/gartan/` to `/config/custom_components/gartan/`, restart, then
Settings > Devices & services > Add integration > Gartan Availability. For HACS, put
this repo's contents at the repo root and add it as a custom repository (replace
`REPLACE_ME` in `manifest.json`). Rotate the Gartan password first: it was in
plaintext in the old flow export.

## Entities (device "Gartan")

| Entity | Meaning |
|---|---|
| `calendar.gartan_52p1` | Appliance on-the-run periods (Available/Alternate) + "out on shout" |
| `calendar.gartan_tom` | Your on-call periods |
| `binary_sensor.gartan_52p1_on` / `_deployed` | On the run now / Off Station (pink) |
| `binary_sensor.gartan_tom_on_call` | You are on call now |
| `binary_sensor.gartan_needs_attention` | Any issue (also raised in Repairs) |
| `sensor.gartan_52p1_next_on` / `_next_off` | Timestamps; unknown while deployed or if the run reaches the end of the known week |
| `sensor.gartan_tom_next_on_call` / `_next_off_call` | Same, for you |
| `sensor.gartan_who_is_on` | Count; attributes `ic`, `driver`, `ba`, `others`, `visiting`, `off` |
| `sensor.gartan_bookable_windows` | Count; attributes `windows` and ready-made `text` |
| `sensor.gartan_last_scrape`, `sensor.gartan_crew_rule_mismatches` | Diagnostics |

Entity ids come from the names chosen at setup (`52p1`, `Tom`); changing them later
doesn't rename existing entities.

## Behaviour

- Today every 5 minutes; the full 7 days roughly hourly. 15-minute resolution.
- The appliance calendar uses Gartan's own appliance row, not our crew rule.
- During a call-out the future pink slots are replaced by the last pre-call-out
  schedule (kept in `.storage`), so the calendar stays useful.
- Bookable = blue-dash cell with no booking id. Unknown booking codes or appliance
  statuses are treated as not available and raise an issue. A raw capture of the
  response is saved to `/config/gartan_captures/` (max 20) for each new oddity and
  for call-outs.
- Dual-role cover imports (only skill ERD/Ang) are dropped from crew counts;
  other imports count as visitors.
- `crew_rule_mismatches` counts slots where our rule disagrees with Gartan's row.
  Informational only. Persistent mismatches mean the booking-window logic needs
  tuning (the calendars are unaffected).

## Tests

    python -m unittest discover -s tests -t .
    python tools/replay.py capture.json 2026-11-02 --me "CLABON, T"

Fixtures in `tests/` are synthetic. Scrub names and payroll numbers from real
captures before committing them.
