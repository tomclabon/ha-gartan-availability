"""Gartan Availability client. Needs an aiohttp-style session, nothing else.

Cookies are tracked here and sent explicitly, so the session should not keep its
own (Home Assistant code passes a session with a dummy cookie jar).
"""
from __future__ import annotations

import json
from datetime import date
from html.parser import HTMLParser

# Verified against the original Node-RED flow.
LOGIN_PATH = "/Availability/Account/Login.aspx"
SCHEDULE_PATH = "/Availability/Availability/Schedule/AvailabilityMain1.aspx/GetSchedule"
USER_FIELD = "txt_userid"
PASSWORD_FIELD = "txt_pword"
SUBMIT_FIELD = "btnLogin"
AUTH_COOKIE_MARKER = "AuthCookie"  # e.g. Cookies.AuthCookie.DWFirePRODUCTION


def build_request_body(day: date, brigade_id: int, brigade_name: str) -> dict:
    """GetSchedule is an ASP.NET page method: every parameter must be present."""
    return {
        "brigadeId": brigade_id,
        "brigadeName": brigade_name,
        "employeeBrigadeId": 0,
        "bookingDate": f"{day.day}/{day.month}/{day.year}",  # D/M/YYYY, no padding
        "resolution": 15,
        "dayCount": 0,
        "showDetails": True,
        "showHours": True,
        "highlightContractDetails": False,
        "highlightEmployeesOffStation": True,
        "includeApplianceStatus": True,
        "showEmpShiftTypes": False,
    }


class AuthError(Exception):
    """Credentials rejected."""


class FetchError(Exception):
    """Network/HTTP/parse problem, or a session problem that a retry may fix."""


class _Form(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.inputs: list[dict[str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag == "input":
            self.inputs.append({k.lower(): (v or "") for k, v in attrs})


def build_login_form(page: str, username: str, password: str) -> dict[str, str]:
    """Fresh hidden fields (VIEWSTATE, VIEWSTATEGENERATOR, EVENTVALIDATION) plus
    the known login fields. Only the login button is submitted, never any other
    button on the page."""
    p = _Form()
    p.feed(page)
    form: dict[str, str] = {}
    names = set()
    submit_value = "Sign In"
    for inp in p.inputs:
        name = inp.get("name", "")
        names.add(name)
        if inp.get("type", "text").lower() == "hidden" and name:
            form[name] = inp.get("value", "")
        if name == SUBMIT_FIELD and inp.get("value"):
            submit_value = inp["value"]
    if USER_FIELD not in names or PASSWORD_FIELD not in names:
        raise FetchError("Login page has changed: username/password fields not found")
    if "__VIEWSTATE" not in form:
        raise FetchError("Login page has changed: no __VIEWSTATE")
    form[USER_FIELD] = username
    form[PASSWORD_FIELD] = password
    form[SUBMIT_FIELD] = submit_value
    return form


def has_auth_cookie(cookies: dict[str, str]) -> bool:
    return any(AUTH_COOKIE_MARKER in name and value for name, value in cookies.items())


class GartanClient:
    def __init__(self, session, base_url, username, password, brigade_id, brigade_name):
        self._s = session
        self._base = base_url.rstrip("/")
        self._user = username
        self._pw = password
        self._brigade_id = int(brigade_id)
        self._brigade_name = brigade_name
        self._cookies: dict[str, str] = {}
        self._logged_in = False

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"User-Agent": "gartan-ha/0.1"}
        if self._cookies:
            h["Cookie"] = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
        if extra:
            h.update(extra)
        return h

    def _absorb(self, resp) -> None:
        for name, morsel in resp.cookies.items():
            self._cookies[name] = getattr(morsel, "value", morsel)

    async def login(self) -> None:
        self._cookies.clear()
        self._logged_in = False
        try:
            async with self._s.get(self._base + LOGIN_PATH, headers=self._headers()) as r:
                if r.status >= 400:
                    raise FetchError(f"login page HTTP {r.status}")
                page = await r.text()
                self._absorb(r)
            form = build_login_form(page, self._user, self._pw)
            async with self._s.post(
                self._base + LOGIN_PATH,
                data=form,  # form-urlencoded
                headers=self._headers(),
                allow_redirects=False,  # the auth cookie is set on the redirect
            ) as r:
                self._absorb(r)
                status = r.status
        except FetchError:
            raise
        except Exception as err:
            raise FetchError(f"login failed: {err}") from err
        if status >= 500:
            raise FetchError(f"login HTTP {status}")
        if not has_auth_cookie(self._cookies):
            raise AuthError("Login rejected (check username and password)")
        self._logged_in = True

    async def fetch_day(self, day: date) -> str:
        """Return the schedule HTML for one day (15-minute resolution)."""
        body = build_request_body(day, self._brigade_id, self._brigade_name)
        for attempt in (1, 2):
            if not self._logged_in:
                await self.login()
            try:
                async with self._s.post(
                    self._base + SCHEDULE_PATH,
                    data=json.dumps(body),
                    headers=self._headers(
                        {"Content-Type": "application/json", "Accept": "application/json"}
                    ),
                    allow_redirects=False,
                ) as r:
                    status, text = r.status, await r.text()
            except Exception as err:
                raise FetchError(f"schedule request failed: {err}") from err
            if status >= 500 or status == 404:
                raise FetchError(f"schedule HTTP {status}: {text[:200]}")
            if status < 300:
                try:
                    return json.loads(text)["d"]
                except (ValueError, KeyError, TypeError):
                    pass  # login page instead of JSON: session lapsed
            self._logged_in = False
        # Login succeeded but the schedule still refused us. Not a password problem,
        # so don't trigger re-authentication; retry on the next poll.
        raise FetchError("schedule refused after a fresh login")
