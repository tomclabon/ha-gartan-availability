import unittest
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from custom_components.gartan_availability.core import client
from custom_components.gartan_availability.core.model import build_timeline, next_on_off, runs_from_flags
from custom_components.gartan_availability.core.parse import classify_cell, parse_brigades, parse_day, parse_status
from custom_components.gartan_availability.core.view import (
    CoreConfig,
    appliance_labels,
    build_view,
    find_me,
    people_on,
    schedule_export,
)

from .fixtures import BRIGADE_PAGE, N, table, window

TZ = ZoneInfo("Europe/London")
DAY = date(2026, 11, 2)  # GMT, so local midnight == 00:00 UTC
NOW = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)
CFG = CoreConfig()


def crew(extra=None, me_cells="book"):
    people = [
        dict(name="CLABON, T", skills=["BA", "DRV"], cells=me_cells, mine=True),
        dict(name="ALPHA, A", skills=["IC1", "BA"], cells="on", expiring=["BA"]),
        dict(name="BRAVO, B", skills=["ERD/Ang"], cells="on"),
        dict(name="CHARLIE, C", skills=["BA"], cells="on"),
    ]
    return people + (extra or [])


def day_for(people, p1=lambda i: "Off the Run", d=DAY, v1=None):
    return parse_day(table(people, p1, v1_fn=v1), d, TZ)


def view_for(people, p1=lambda i: "Off the Run", baseline=None, now=NOW, v1=None):
    return build_view([day_for(people, p1, v1=v1)], CFG, baseline or {}, now)


class ParseTests(unittest.TestCase):
    def test_basic_shape(self):
        day = day_for(crew())
        self.assertEqual(len(day.slot_starts), N)
        self.assertEqual(day.issues, {})
        me = day.people[0]
        self.assertTrue(me.is_me and all(me.bookable) and not any(me.on))
        self.assertFalse(day.people[1].is_me)
        self.assertEqual(day.people[1].skills, frozenset({"IC1", "BA"}))
        self.assertEqual(day.people[1].expiring, frozenset({"BA"}))
        self.assertEqual(day.appliances["KT52P1"][0], "off_the_run")

    def test_cell_classes(self):
        self.assertEqual(classify_cell({"class": "schTD"})[:2], (True, False))
        self.assertEqual(classify_cell({"class": "schTD_AutoContract"})[:2], (False, True))
        self.assertEqual(classify_cell({"class": "schTD_AutoContract", "data-bid": "5"})[:2], (False, False))
        self.assertEqual(classify_cell({"class": "schTD_AutoContract", "data-codeid": "31"})[:2], (False, False))
        self.assertEqual(classify_cell({"class": "schTD", "data-codeid": "32"})[:2], (True, False))
        self.assertEqual(classify_cell({"class": "schTD_DefaultBlackText", "data-codeid": "35"})[:2], (True, False))
        self.assertEqual(classify_cell({"class": "schTD_off", "data-codeid": "1"})[:2], (False, False))
        self.assertEqual(classify_cell({"class": "schTD", "data-codeid": "99"})[:3], (False, False, "code:99"))

    def test_unknown_code_raises_issue(self):
        day = day_for(crew([dict(name="ZULU, Z", skills=[], cells="weird")]))
        self.assertIn("unknown_code:99", day.issues)

    def test_status_text(self):
        self.assertEqual(parse_status("KT52P1 (0000 - 0015) Available")[0], "available")
        self.assertEqual(parse_status("KT52P1 (0000 - 0015) Off Station")[0], "off_station")
        self.assertEqual(parse_status("KT52P1 (0000 - 0015) Intermediate"), ("unknown", "Intermediate"))

    def test_unknown_status_raises_issue(self):
        day = day_for(crew(), p1=lambda i: "Intermediate")
        self.assertIn("status_Intermediate", day.issues)

    def test_appliance_label_from_title(self):
        html = table(crew(), lambda i: "Available").replace("<td>KT52P1</td>", "<td><b>?</b></td>")
        self.assertIn("KT52P1", parse_day(html, DAY, TZ).appliances)

    def test_two_appliances(self):
        day = day_for(crew(), v1=lambda i: "Available")
        self.assertEqual(appliance_labels([day]), ["KT52P1", "KT52V1"])

    def test_clock_change_day_flagged(self):
        self.assertIn("slot_count", day_for(crew(), d=date(2026, 3, 29)).issues)

    def test_brigades(self):
        self.assertEqual(
            [(b.id, b.name, b.selected) for b in parse_brigades(BRIGADE_PAGE)],
            [(2, "KT52 Cricklade", True)],
        )
        self.assertEqual(parse_brigades("<html></html>"), [])


class TimelineTests(unittest.TestCase):
    def test_me_auto_detected_and_override(self):
        tl = build_timeline([day_for(crew())])
        self.assertEqual(find_me(tl), "CLABON, T")
        self.assertEqual(find_me(tl, "alpha, a"), "ALPHA, A")
        self.assertIsNone(find_me(tl, "NOBODY, X"))

    def test_imports_are_people(self):
        people = crew([dict(name="SIMON WARD", skills=["ERD/Ang"], cells="on", imp=True)], me_cells="off")
        view = view_for(people)
        on = people_on(view, NOW)
        self.assertEqual(len(on), 4)
        self.assertEqual(on[-1], {"name": "SIMON WARD", "imported": True, "skills": ["ERD/Ang"]})

    def test_same_named_imports_merged(self):
        people = crew(
            [
                dict(name="SIMON WARD", skills=["ERD/Ang"], cells=window("00:00", "06:00", "on"), imp=True),
                dict(name="SIMON WARD", skills=["ERD/Ang"], cells=window("10:00", "12:00", "on"), imp=True),
            ]
        )
        tl = build_timeline([day_for(people)])
        imports = [s for s in tl.series.values() if s.imported]
        self.assertEqual(len(imports), 1)
        self.assertEqual(len(runs_from_flags(tl, imports[0].on)), 2)

    def test_import_on_one_day_only(self):
        d1 = day_for(crew([dict(name="SIMON WARD", skills=["ERD/Ang"], cells="on", imp=True)]))
        d2 = day_for(crew(), d=DAY + timedelta(days=1))
        tl = build_timeline([d1, d2])
        s = tl.series["import|SIMON WARD"]
        self.assertEqual(len(s.on), 2 * N)
        self.assertTrue(all(s.on[:N]) and not any(s.on[N:]))

    def test_runs_and_next(self):
        view = view_for(crew(me_cells=window("09:00", "10:00", "on")))
        runs = runs_from_flags(view.timeline, view.timeline.series["CLABON, T"].on)
        nxt_on, nxt_off, cur = next_on_off(runs, NOW, view.timeline.end)
        self.assertFalse(cur)
        self.assertEqual((nxt_on.hour, nxt_off.hour), (9, 10))

    def test_run_to_end_of_horizon_has_no_off(self):
        view = view_for(crew(me_cells=window("20:00", "24:00", "on")))
        runs = runs_from_flags(view.timeline, view.timeline.series["CLABON, T"].on)
        self.assertIsNone(next_on_off(runs, NOW, view.timeline.end)[1])


class CallOutTests(unittest.TestCase):
    def test_baseline_used_for_future_pink(self):
        start = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
        base = {"KT52P1": {(start + i * timedelta(minutes=15)).isoformat(): "available" for i in range(N)}}
        view = view_for(crew(), p1=window("07:00", "24:00", "Off Station", "Available"), baseline=base)
        app = view.appliances["KT52P1"]
        self.assertTrue(app.deployed)
        tl = view.timeline
        self.assertEqual(app.effective[tl.index_at(NOW)], "off_station")
        self.assertEqual(app.effective[tl.index_at(NOW + timedelta(hours=4))], "available")

    def test_no_baseline_future_unknown(self):
        view = view_for(crew(), p1=window("07:00", "24:00", "Off Station", "Available"))
        tl = view.timeline
        self.assertEqual(view.appliances["KT52P1"].effective[tl.index_at(NOW + timedelta(hours=4))], "unknown")


class ExportTests(unittest.TestCase):
    def test_export_shape(self):
        people = crew(
            [dict(name="SIMON WARD", skills=["ERD/Ang"], cells=window("10:00", "11:00", "on"), imp=True)],
            me_cells=window("09:00", "10:00", "book", "on"),
        )
        view = view_for(people, p1=window("00:00", "01:00", "Alternate", "Available"), v1=lambda i: "Off the Run")
        ex = schedule_export(view)
        self.assertEqual(ex["start"], "2026-11-02T00:00:00+00:00")
        self.assertEqual((ex["slot_minutes"], ex["slots"]), (15, N))
        self.assertEqual(ex["appliances"]["KT52P1"][:5], "LLLLA")
        self.assertEqual(ex["appliances"]["KT52V1"], "O" * N)
        me = next(p for p in ex["people"] if p["me"])
        self.assertEqual(me["slots"][35:41], "1bbbb1")
        alpha = next(p for p in ex["people"] if p["name"] == "ALPHA, A")
        self.assertEqual((alpha["skills"], alpha["expiring"]), (["BA", "IC1"], ["BA"]))
        ward = ex["people"][-1]
        self.assertTrue(ward["imported"])
        self.assertEqual(ward["slots"].index("1"), 40)
        self.assertEqual(ex["legend"]["person"]["b"], "bookable")

    def test_export_stops_at_gap(self):
        d1 = day_for(crew())
        d3 = day_for(crew(), d=DAY + timedelta(days=2))  # day 2 missing
        ex = schedule_export(build_view([d1, d3], CFG, {}, NOW))
        self.assertEqual(ex["slots"], N)

    def test_export_size_is_reasonable(self):
        import json

        people = crew([dict(name=f"PERSON{i}, X", skills=["BA"], cells="on") for i in range(12)])
        days = [day_for(people, d=DAY + timedelta(days=k), v1=lambda i: "Available") for k in range(7)]
        size = len(json.dumps(schedule_export(build_view(days, CFG, {}, NOW))))
        self.assertLess(size, 16_384)


class ClientTests(unittest.TestCase):
    PAGE = (
        '<input type="text" name="txtSearch">'
        '<input type="hidden" name="__VIEWSTATE" value="abc">'
        '<input type="hidden" name="__VIEWSTATEGENERATOR" value="C40DB9C1">'
        '<input type="hidden" name="__EVENTVALIDATION" value="def">'
        '<input type="text" name="txt_userid"><input type="password" name="txt_pword">'
        '<input type="submit" name="btnForgot" value="Forgot">'
        '<input type="submit" name="btnLogin" value="Sign In">'
    )

    def test_login_form(self):
        self.assertEqual(
            client.build_login_form(self.PAGE, "u", "p"),
            {
                "__VIEWSTATE": "abc",
                "__VIEWSTATEGENERATOR": "C40DB9C1",
                "__EVENTVALIDATION": "def",
                "txt_userid": "u",
                "txt_pword": "p",
                "btnLogin": "Sign In",
            },
        )

    def test_login_page_changed(self):
        with self.assertRaises(client.FetchError):
            client.build_login_form("<input name='other'>", "u", "p")

    def test_auth_cookie(self):
        self.assertTrue(client.has_auth_cookie({"Cookies.AuthCookie.DWFirePRODUCTION": "x"}))
        self.assertFalse(client.has_auth_cookie({"ASP.NET_SessionId": "x"}))

    def test_request_body_matches_flow(self):
        b = client.build_request_body(date(2026, 3, 5), 2, "KT52 Cricklade")
        self.assertEqual(b["bookingDate"], "5/3/2026")
        self.assertEqual(len(b), 12)


if __name__ == "__main__":
    unittest.main()
