"""Write the history ledger into Home Assistant's long-term statistics, so the
Statistics graph card can chart it over the whole period. External statistics
(source = this integration), re-imported in full whenever the ledger changes;
rows for the same hour are overwritten, so corrections flow through."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import CONF_BRIGADE_ID, DOMAIN
from .core.history import Ledger, merge_callouts

_LOGGER = logging.getLogger(__name__)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "x"


def statistic_ids(entry: ConfigEntry, appliances: list[str]) -> dict[str, str]:
    prefix = f"{DOMAIN}:b{entry.data.get(CONF_BRIGADE_ID, 0)}"
    ids = {
        "on_call_hours": f"{prefix}_on_call_hours",
        "contract_hours": f"{prefix}_contract_hours",
        "actual_hours": f"{prefix}_actual_hours",
    }
    for label in appliances:
        ids[f"callouts:{label}"] = f"{prefix}_{_slug(label)}_call_outs"
        ids[f"my_callouts:{label}"] = f"{prefix}_{_slug(label)}_my_call_outs"
    return ids


@callback
def async_import_history(hass: HomeAssistant, entry: ConfigEntry, ledger: Ledger) -> None:
    try:
        from homeassistant.components.recorder.models import StatisticMeanType
        from homeassistant.components.recorder.statistics import async_add_external_statistics
    except ImportError:  # recorder not available
        return
    tz = dt_util.get_default_time_zone()

    def at(d: date) -> datetime:
        return dt_util.as_utc(datetime.combine(d, time.min, tzinfo=tz))

    callouts = merge_callouts(c for r in ledger.days.values() for c in r.callouts)
    appliances = sorted({c.appliance for c in callouts})
    ids = statistic_ids(entry, appliances)

    def series(key: str, name: str, unit: str | None, unit_class: str | None, points):
        rows, total = [], 0.0
        for start, value in sorted(points):
            total += value
            rows.append({"start": start, "state": value, "sum": total})
        if not rows:
            return
        meta = {
            "source": DOMAIN,
            "statistic_id": ids[key],
            "name": name,
            "unit_of_measurement": unit,
            "unit_class": unit_class,
            "mean_type": StatisticMeanType.NONE,
            "has_sum": True,
        }
        try:
            async_add_external_statistics(hass, meta, rows)
        except Exception:  # noqa: BLE001 - statistics are a nice-to-have
            _LOGGER.exception("Could not import statistics %s", ids[key])

    series("on_call_hours", "Gartan on-call hours (daily)", "h", "duration",
           [(at(d), r.on_minutes / 60) for d, r in ledger.days.items()])
    series("contract_hours", "Gartan contract hours (weekly)", "h", "duration",
           [(at(m), w.contract) for m, w in ledger.weeks.items()])
    series("actual_hours", "Gartan actual hours (weekly)", "h", "duration",
           [(at(m), w.actual) for m, w in ledger.weeks.items()])
    for label in appliances:
        daily: dict[date, list[int]] = {}
        for c in callouts:
            if c.appliance != label:
                continue
            d = dt_util.as_local(c.start).date()
            tally = daily.setdefault(d, [0, 0])
            tally[0] += 1
            tally[1] += int(c.me)
        series(f"callouts:{label}", f"Gartan {label} call-outs (daily)", None, None,
               [(at(d), v[0]) for d, v in daily.items()])
        series(f"my_callouts:{label}", f"Gartan my {label} call-outs (daily)", None, None,
               [(at(d), v[1]) for d, v in daily.items()])
