import unittest
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from custom_components.gartan.core import client
from custom_components.gartan.core.model import Member, check_crew, next_on_off, runs_from_flags
from custom_components.gartan.core.parse import classify_cell, parse_day, parse_status
from custom_components.gartan.core.view import CoreConfig, build_view, crew_groups, display_name

from .fixtures import N, table, window

TZ = ZoneInfo("Europe/London")
DAY = date(2026, 11, 2)  # GMT
CFG = CoreConfig("KT52P1", "CLABON, T", frozenset({"WARD, S", "SIMON WARD"}))
NOW = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)


def crew(extra=None, me_cells="book", p1=None):
    people = [
        dict(name="CLABON, T", skills=["BA", "DRV"], cells=me_cells, mine=True),
        dict(name="ALPHA, A", skills=["IC1", "BA"], cells="on"),
        dict(name="BRAVO, B", skills=["ERD/Ang"], cells="on"),
        dict(name="CHARLIE, C", skills=["BA"], cells="on"),
    ]
    people += extra or []
    return people, (p1 or (lambda i: "Off the Run"))


def view_for(people, p1, baseline=None, now=NOW):
    day = parse_day(table(people, p1), DAY, TZ)
    return build_view([day], CFG, baseline or {}, now), day


class ParseTests(unittest.TestCase):
    def test_basic_shape(self):
        people, p1 = crew()
        day = parse_day(table(people, p1), DAY, TZ)
        self.assertEqual(len(day.slot_starts), N)
        self.assertEqual(day.issues, {})
        self.assertEqual([p.name for p in day.people][:2], ["CLABON, T", "ALPHA, A"])
        me = day.people[0]
        self.assertTrue(all(me.bookable) and not any(me.on))
        self.assertEqual(day.people[1].skills, frozenset({"IC1", "BA"}))
        self.assertEqual(day.appliances["KT52P1"][0], "off_the_run")

    def test_cell_classes(self):
        self.assertEqual(classify_cell({"class": "schTD"})[:2], (True, False))
        self.assertEqual(classify_cell({"class": "schTD_AutoContract"})[:2], (False, True))
        self.assertEqual(classify_cell({"class": "schTD_AutoContract", "data-codeid": "31"})[:2], (False, False))
        self.assertEqual(classify_cell({"class": "schTD", "data-codeid": "32"})[:2], (True, False))
        self.assertEqual(classify_cell({"class": "schTD_off", "data-codeid": "1"})[:2], (False, False))
        on, book, key, _ = classify_cell({"class": "schTD", "data-codeid": "99"})
        self.assertEqual((on, book, key), (False, False, "code:99"))

    def test_unknown_code_raises_issue(self):
        people, p1 = crew([dict(name="ZULU, Z", skills=[], cells="weird")])
        day = parse_day(table(people, p1), DAY, TZ)
        self.assertIn("unknown_code:99", day.issues)

    def test_status_text(self):
        self.assertEqual(parse_status("KT52P1 (0000 - 0015) Available")[0], "available")
        self.assertEqual(parse_status("KT52P1 (0000 - 0015) Off Station")[0], "off_station")
        status, raw = parse_status("KT52P1 (0000 - 0015) Intermediate")
        self.assertEqual((status, raw), ("unknown", "Intermediate"))

    def test_clock_change_day_flagged(self):
        people, p1 = crew()
        day = parse_day(table(people, p1), date(2026, 3, 29), TZ)
        self.assertIn("slot_count", day.issues)


class CrewTests(unittest.TestCase):
    def m(self, key, *skills):
        return Member(key, key, frozenset(skills))

    def test_valid_crew(self):
        c = check_crew([self.m("a", "IC1", "BA"), self.m("b", "ERD/Ang"), self.m("c", "BA"), self.m("d")], frozenset())
        self.assertTrue(c.valid_strict)

    def test_three_is_not_enough(self):
        c = check_crew([self.m("a", "IC1", "BA"), self.m("b", "ERD/Ang"), self.m("c", "BA")], frozenset())
        self.assertFalse(c.valid_dual)
        self.assertIn("crew", c.missing)

    def test_dual_role_needs_allowance(self):
        members = [self.m("SIMON WARD", "IC1", "ERD/Ang"), self.m("b", "BA"), self.m("c", "BA"), self.m("d")]
        self.assertFalse(check_crew(members, frozenset()).valid_dual)
        members[0] = Member("w", "WARD, S", frozenset({"IC1", "ERD/Ang"}))
        c = check_crew(members, frozenset({"WARD, S"}))
        self.assertTrue(c.valid_dual and not c.valid_strict)


class ViewTests(unittest.TestCase):
    def test_booking_window_found(self):
        people, p1 = crew(p1=window("09:00", "12:00", "Available", "Off the Run"))
        # P1 only on 09-12 but we want Tom bookable only 10-11: make him blue then
        people[0]["cells"] = window("10:00", "11:00", "book", "off")
        people[1]["cells"] = people[2]["cells"] = people[3]["cells"] = "on"
        view, _ = view_for(people, lambda i: "Off the Run")
        self.assertEqual(len(view.windows), 1)
        w = view.windows[0]
        self.assertTrue(w.goes_on)
        self.assertEqual((w.start.hour, w.end.hour), (10, 11))
        self.assertEqual(w.minutes, 60)

    def test_no_window_when_truck_already_on(self):
        people, p1 = crew()
        view, _ = view_for(people, lambda i: "Available")
        self.assertEqual(view.windows, [])

    def test_partial_fix_labelled(self):
        people, p1 = crew([dict(name="DELTA, D", skills=[], cells="on")])
        people.pop(2)  # nobody holds ERD/Ang and Tom lacks it
        view, _ = view_for(people, lambda i: "Off the Run")
        self.assertTrue(view.windows)
        self.assertFalse(view.windows[0].goes_on)
        self.assertIn("ERD/Ang", view.windows[0].missing)

    def test_what_if_driver_skill(self):
        people, p1 = crew([dict(name="DELTA, D", skills=[], cells="on")])
        people.pop(2)
        cfg = CoreConfig("KT52P1", "CLABON, T", extra_skills=frozenset({"ERD/Ang"}))
        day = parse_day(table(people, lambda i: "Off the Run"), DAY, TZ)
        view = build_view([day], cfg, {}, NOW)
        self.assertTrue(view.windows[0].goes_on)

    def test_callout_keeps_baseline(self):
        people, _ = crew(me_cells="off")
        base_iso = {}
        start = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
        from datetime import timedelta
        for i in range(N):
            base_iso[(start + i * timedelta(minutes=15)).isoformat()] = "available"
        # pink from 07:00 onwards (truck out now)
        pink = window("07:00", "24:00", "Off Station", "Available")
        view, _ = view_for(people, pink, baseline=base_iso)
        self.assertTrue(view.deployed)
        idx_future = view.timeline.index_at(datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(view.p1_effective[idx_future], "available")
        idx_now = view.timeline.index_at(NOW)
        self.assertEqual(view.p1_effective[idx_now], "off_station")

    def test_oracle_matches_on_clean_day(self):
        people, _ = crew(me_cells="on")
        view, _ = view_for(people, lambda i: "Available")
        self.assertEqual(view.diagnostics["mismatched_slots"], 0)

    def test_oracle_flags_disagreement(self):
        people, _ = crew(me_cells="off")  # 3 people, Gartan says Available: rule disagrees
        view, _ = view_for(people, lambda i: "Available")
        self.assertGreater(view.diagnostics["mismatched_slots"], 0)

    def test_dual_cover_import_dropped_from_crew(self):
        people, p1 = crew(me_cells="off")
        people.append(dict(name="SIMON WARD", skills=["ERD/Ang"], cells="on", imp=True))
        view, _ = view_for(people, p1)
        self.assertEqual(len(view.timeline.series), 4)  # cover row not a person
        self.assertTrue(all(view.timeline.dual_import_on))

    def test_visitor_import_counts(self):
        people, p1 = crew(me_cells="off")
        people.append(dict(name="VISITOR, V", skills=["BA", "DRV"], cells="on", imp=True))
        view, _ = view_for(people, p1)
        i = view.timeline.index_at(NOW)
        self.assertEqual(len(view.timeline.members_on(i)), 4)

    def test_groups_exclusive(self):
        people, p1 = crew(me_cells="off")
        view, _ = view_for(people, p1)
        g = crew_groups(view, CFG, NOW)
        self.assertEqual((g["ic"], g["driver"], g["ba"]), (["A Alpha"], ["B Bravo"], ["C Charlie"]))
        self.assertEqual(g["off"], ["T Clabon"])

    def test_display_names(self):
        self.assertEqual(display_name("WALLIS, D", {"WALLIS, D": "Danny"}), "Danny")
        self.assertEqual(display_name("WALLIS, D", {}), "D Wallis")


class RunTests(unittest.TestCase):
    def test_runs_and_next(self):
        people, _ = crew(me_cells=window("09:00", "10:00", "on", "off"))
        view, _ = view_for(people, lambda i: "Off the Run")
        flags = view.timeline.series["CLABON, T"].on
        runs = runs_from_flags(view.timeline, flags)
        self.assertEqual(len(runs), 1)
        nxt_on, nxt_off, cur = next_on_off(runs, NOW, view.timeline.end)
        self.assertFalse(cur)
        self.assertEqual(nxt_on.hour, 9)
        self.assertEqual(nxt_off.hour, 10)

    def test_run_to_end_of_horizon_has_no_off(self):
        people, _ = crew(me_cells=window("20:00", "24:00", "on", "off"))
        view, _ = view_for(people, lambda i: "Off the Run")
        runs = runs_from_flags(view.timeline, view.timeline.series["CLABON, T"].on)
        _, nxt_off, _ = next_on_off(runs, NOW, view.timeline.end)
        self.assertIsNone(nxt_off)


class ClientTests(unittest.TestCase):
    PAGE = (
        '<input type="text" name="txtSearch">'  # decoy text box before the login fields
        '<input type="hidden" name="__VIEWSTATE" value="abc">'
        '<input type="hidden" name="__VIEWSTATEGENERATOR" value="C40DB9C1">'
        '<input type="hidden" name="__EVENTVALIDATION" value="def">'
        '<input type="text" name="txt_userid"><input type="password" name="txt_pword">'
        '<input type="submit" name="btnForgot" value="Forgot">'
        '<input type="submit" name="btnLogin" value="Sign In">'
    )

    def test_login_form(self):
        f = client.build_login_form(self.PAGE, "u", "p")
        self.assertEqual(
            f,
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
        self.assertEqual(
            set(b),
            {"brigadeId", "brigadeName", "employeeBrigadeId", "bookingDate", "resolution",
             "dayCount", "showDetails", "showHours", "highlightContractDetails",
             "highlightEmployeesOffStation", "includeApplianceStatus", "showEmpShiftTypes"},
        )


class ParseDetailTests(unittest.TestCase):
    def test_bid_without_code_not_bookable(self):
        self.assertEqual(
            classify_cell({"class": "schTD_AutoContract", "data-bid": "5"})[:2], (False, False)
        )

    def test_appliance_label_from_title(self):
        html = table(crew()[0], lambda i: "Available").replace("<td>KT52P1</td>", "<td><b>?</b></td>")
        day = parse_day(html, DAY, TZ)
        self.assertIn("KT52P1", day.appliances)


if __name__ == "__main__":
    unittest.main()
