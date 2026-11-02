import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from custom_components.gartan_availability.core import client
from custom_components.gartan_availability.core.history import (
    CallOut,
    DayRecord,
    Ledger,
    all_callouts,
    callout_counts,
    hours_summary,
    merge_callouts,
    record_day,
)
from custom_components.gartan_availability.core.parse import WeekHours, parse_day, parse_employee_weeks
from custom_components.gartan_availability.core.view import CoreConfig, build_view

from .fixtures import table, window
from .test_core import crew

TZ = ZoneInfo("Europe/London")
DATA = Path(__file__).parent / "data"
U = timezone.utc


def day(d, people=None, p1=lambda i: "Available"):
    return parse_day(table(people or crew(me_cells="on"), p1), d, TZ)


class EmployeeViewTests(unittest.TestCase):
    def test_weekly_figures(self):
        html = json.loads((DATA / "employee_two_weeks.json").read_text())["d"]
        weeks = parse_employee_weeks(html)
        self.assertEqual(weeks[date(2026, 11, 2)], WeekHours(date(2026, 11, 2), 51.0, 28.0))
        self.assertEqual(weeks[date(2026, 11, 9)].contract, 80.0)

    def test_request_body(self):
        b = client.build_employee_body(date(2026, 11, 2), 2, "KT52 Cricklade", 2440, 14)
        self.assertEqual((b["bookingDate"], b["employeeBrigadeId"], b["dayCount"]), ("02/11/2026", 2440, 14))

    def test_ebid_captured_from_station_view(self):
        html = table(crew(), lambda i: "Available").replace(
            '<td class="nameCol">CLABON, T</td>', '<td class="nameCol" data-ebid="2440">CLABON, T</td>'
        )
        d = parse_day(html, date(2026, 11, 2), TZ)
        self.assertEqual(d.people[0].ebid, 2440)


class CallOutTests(unittest.TestCase):
    def test_record_day(self):
        people = crew(me_cells=window("02:00", "03:00", "on", "off"))
        p1 = window("02:00", "04:00", "Off Station", "Available")
        rec = record_day(day(date(2026, 10, 30), people, p1))
        self.assertEqual(rec.on_minutes, 60)
        self.assertEqual(len(rec.callouts), 1)
        c = rec.callouts[0]
        self.assertEqual((c.start.hour, c.end.hour, c.me, c.appliance), (2, 4, True, "KT52P1"))

    def test_not_mine_when_off_at_start(self):
        people = crew(me_cells=window("03:00", "05:00", "on", "off"))
        rec = record_day(day(date(2026, 10, 30), people, window("02:00", "04:00", "Off Station", "Available")))
        self.assertFalse(rec.callouts[0].me)

    def test_merge_across_midnight(self):
        a = CallOut("P1", datetime(2026, 10, 30, 23, 0, tzinfo=U), datetime(2026, 10, 31, 0, 0, tzinfo=U), 4, True)
        b = CallOut("P1", datetime(2026, 10, 31, 0, 0, tzinfo=U), datetime(2026, 10, 31, 1, 0, tzinfo=U), 5, False)
        m = merge_callouts([b, a])
        self.assertEqual(len(m), 1)
        self.assertEqual((m[0].end.hour, m[0].crew, m[0].me), (1, 5, True))

    def test_ledger_round_trip(self):
        led = Ledger()
        led.weeks[date(2026, 11, 2)] = WeekHours(date(2026, 11, 2), 51, 28)
        led.empty_windows.add(date(2020, 1, 6))
        led.days[date(2026, 10, 30)] = DayRecord(
            date(2026, 10, 30), 60,
            [CallOut("P1", datetime(2026, 10, 30, 2, tzinfo=U), datetime(2026, 10, 30, 4, tzinfo=U), 4, True)],
        )
        again = Ledger.from_json(json.loads(json.dumps(led.to_json())))
        self.assertEqual(again.to_json(), led.to_json())


class SummaryTests(unittest.TestCase):
    # Wednesday 4 Nov 2026 12:00 UTC (GMT): 2.5 days into the week
    NOW = datetime(2026, 11, 4, 12, 0, tzinfo=U)

    def ledger(self):
        led = Ledger()
        for k in range(1, 10):
            m = date(2026, 11, 2) - timedelta(weeks=k)
            led.weeks[m] = WeekHours(m, 80.0, 70.0)
        led.weeks[date(2026, 11, 2)] = WeekHours(date(2026, 11, 2), 84.0, 90.0)
        led.days[date(2026, 11, 2)] = DayRecord(date(2026, 11, 2), 600)  # 10 h Monday
        led.days[date(2026, 11, 3)] = DayRecord(date(2026, 11, 3), 300)  # 5 h Tuesday
        return led

    def test_periods(self):
        led = self.ledger()
        today = day(date(2026, 11, 4), crew(me_cells=window("06:00", "10:00", "on", "off")))
        view = build_view([today], CoreConfig(), {}, self.NOW)
        s = hours_summary(led, view, self.NOW, TZ)
        # so far: 10 + 5 + 4 (06-10 today) = 19 h; contract so far: 84 * 2.5/7 = 30
        self.assertEqual(s["this_week"].actual, 19.0)
        self.assertEqual(s["this_week"].contract, 30.0)
        self.assertEqual(s["last_4_weeks"].actual, 4 * 70 + 19)
        self.assertEqual(s["last_4_weeks"].contract, 4 * 80 + 30)
        self.assertEqual(s["last_4_weeks"].difference, (4 * 70 + 19) - (4 * 80 + 30))
        self.assertFalse(s["last_52_weeks"].complete)  # only 9 past weeks known
        self.assertEqual(s["since_start"].weeks, 9)
        self.assertTrue(s["since_start"].complete)

    def test_callout_counts_include_today(self):
        led = self.ledger()
        led.days[date(2026, 11, 3)].callouts = [
            CallOut("KT52P1", datetime(2026, 11, 3, 2, tzinfo=U), datetime(2026, 11, 3, 3, tzinfo=U), 4, True)
        ]
        led.days[date(2026, 10, 1)] = DayRecord(
            date(2026, 10, 1), 0,
            [CallOut("KT52P1", datetime(2026, 10, 1, 2, tzinfo=U), datetime(2026, 10, 1, 3, tzinfo=U), 4, False)],
        )
        today = day(
            date(2026, 11, 4),
            crew(me_cells="off"),
            window("09:00", "10:00", "Off Station", "Available"),
        )
        view = build_view([today], CoreConfig(), {}, self.NOW)
        cos = all_callouts(led, view, self.NOW)
        self.assertEqual(len(cos), 3)
        counts = callout_counts(cos, led, "KT52P1", self.NOW, TZ)
        self.assertEqual(counts["this_week"], {"all": 2, "me": 1})
        self.assertEqual(counts["last_4_weeks"], {"all": 2, "me": 1})
        self.assertEqual(counts["last_52_weeks"], {"all": 3, "me": 1})

    def test_future_pink_not_counted(self):
        led = self.ledger()
        today = day(date(2026, 11, 4), crew(), window("11:00", "24:00", "Off Station", "Available"))
        view = build_view([today], CoreConfig(), {}, self.NOW)
        cos = all_callouts(led, view, self.NOW)
        self.assertEqual(len(cos), 1)
        self.assertEqual(cos[0].end, datetime(2026, 11, 4, 12, 15, tzinfo=U))


if __name__ == "__main__":
    unittest.main()
