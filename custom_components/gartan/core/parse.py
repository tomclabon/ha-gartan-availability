"""Parse Gartan HTML (schedule table, brigade list) into plain data. Stdlib only."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from html.parser import HTMLParser

from .const import CODES_OFF, CODES_ON, SLOT, STATUS_BY_TEXT, STATUS_UNKNOWN


# ---------------------------------------------------------------------------
# generic table reader


@dataclass
class Cell:
    attrs: dict[str, str]
    text: str = ""
    parts: list[tuple[str, str]] = field(default_factory=list)  # (text, font colour)


@dataclass
class Row:
    attrs: dict[str, str]
    cells: list[Cell] = field(default_factory=list)


class _TableParser(HTMLParser):
    """Collects <tr>/<td> (lower-cased attribute names), cell text, and the font
    colour each piece of text was written in."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[Row] = []
        self._row: Row | None = None
        self._cell: Cell | None = None
        self._parts: list[tuple[str, str]] = []
        self._fonts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "tr":
            self._close_cell()
            self._close_row()
            self._row = Row(a)
        elif tag == "td" and self._row is not None:
            self._close_cell()
            self._cell = Cell(a)
        elif tag == "font":
            self._fonts.append(a.get("color", "").strip().lower())

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag == "font":
            if self._fonts:
                self._fonts.pop()
        elif tag == "td":
            self._close_cell()
        elif tag == "tr":
            self._close_cell()
            self._close_row()

    def handle_data(self, data):
        if not self._skip and self._cell is not None:
            self._parts.append((data, self._fonts[-1] if self._fonts else ""))

    def _close_cell(self):
        if self._cell is not None and self._row is not None:
            self._cell.text = "".join(t for t, _ in self._parts).replace("\xa0", " ").strip()
            self._cell.parts = [
                (t.replace("\xa0", " ").strip(), colour)
                for t, colour in self._parts
                if t.strip()
            ]
            self._row.cells.append(self._cell)
        self._cell = None
        self._parts = []
        self._fonts = []

    def _close_row(self):
        if self._row is not None:
            self.rows.append(self._row)
        self._row = None


# ---------------------------------------------------------------------------
# schedule


@dataclass
class PersonDay:
    name: str  # data-name: "SURNAME, I" for crew, free text for imports
    role: str
    skills: frozenset[str]
    expiring: frozenset[str]  # skills shown in red
    is_import: bool
    on: list[bool]
    bookable: list[bool]
    is_me: bool = False  # the logged-in user's row: its cells have "emp_" ids


@dataclass
class DaySchedule:
    date: date
    slot_starts: list[datetime]  # UTC, aware
    people: list[PersonDay]
    appliances: dict[str, list[str]]  # row label -> status per slot
    issues: dict[str, str] = field(default_factory=dict)  # key -> detail


_PERSON_ID = re.compile(r"^emp(RO)?_(\d+)-(\d+)$")
_APP_ID = re.compile(r"^app_(\d+)_(\d+)$")
_STATUS_TEXT = re.compile(r"\)\s*(.+?)\s*$")


def _is_red(colour: str) -> bool:
    c = colour.lstrip("#").lower()
    return c in ("red", "ff0000", "f00")


def classify_cell(attrs: dict[str, str]) -> tuple[bool, bool, str | None, str | None]:
    """Return (on, bookable, unknown_key, unknown_detail) for one person cell."""
    classes = set(attrs.get("class", "").split())
    code = attrs.get("data-codeid", "").strip()
    alias = attrs.get("data-alias", "").strip(", ")
    if code:
        try:
            c = int(code)
        except ValueError:
            return False, False, f"code:{code}", f"alias {alias!r}"
        if c in CODES_ON:
            return True, False, None, None
        if c in CODES_OFF:
            return False, False, None, None
        return False, False, f"code:{c}", f"alias {alias!r}"
    if "schTD_AutoContract" in classes:
        # blue "-": bookable only when it carries no booking id
        return False, "data-bid" not in attrs, None, None
    if "schTD_off" in classes:
        return False, False, None, None
    if "schTD" in classes:
        return True, False, None, None  # on by contract
    return False, False, "class:" + (attrs.get("class", "") or "none"), "no code"


def parse_status(title: str) -> tuple[str, str | None]:
    m = _STATUS_TEXT.search(title or "")
    raw = m.group(1) if m else (title or "")
    status = STATUS_BY_TEXT.get(raw.strip().lower())
    return (status, None) if status else (STATUS_UNKNOWN, raw)


def day_slot_starts(day: date, tz: tzinfo, n: int) -> tuple[list[datetime], int]:
    """Slot starts (UTC) for n 15-minute slots from local midnight, plus the
    number of slots the local day really has (differs on clock-change days)."""
    mid = datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc)
    nxt = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz).astimezone(
        timezone.utc
    )
    expected = int((nxt - mid) / SLOT)
    return [mid + i * SLOT for i in range(n)], expected


def parse_day(html: str, day: date, tz: tzinfo) -> DaySchedule:
    parser = _TableParser()
    parser.feed(html)
    parser.close()

    after_divider = False
    raw_people: list[tuple[Row, bool]] = []
    app_rows: dict[str, dict[int, str]] = {}
    for row in parser.rows:
        classes = set(row.attrs.get("class", "").split())
        if "importDivider" in classes:
            after_divider = True
            continue
        if "employee" in classes and "data-name" in row.attrs:
            raw_people.append((row, after_divider))
            continue
        statuses: dict[int, str] = {}
        label = ""
        for c in row.cells:
            m = _APP_ID.match(c.attrs.get("id", ""))
            if m:
                title = c.attrs.get("title", "")
                statuses[int(m.group(2))] = title
                # titles look like "KT52P1 (0000 - 0015) Available"
                label = label or title.split(" (", 1)[0].strip()
        if statuses:
            app_rows[label or (row.cells[0].text if row.cells else "")] = statuses

    n = max((max(s) + 1 for s in app_rows.values()), default=0)
    gathered = []
    for row, is_import in raw_people:
        cells: dict[int, Cell] = {}
        skills: list[str] = []
        expiring: list[str] = []
        editable = False
        for c in row.cells:
            m = _PERSON_ID.match(c.attrs.get("id", ""))
            if m:
                cells[int(m.group(3))] = c
                editable = editable or m.group(1) is None
            elif "skillCol" in c.attrs.get("class", ""):
                for text, colour in c.parts:
                    for tok in text.split():
                        skills.append(tok)
                        if _is_red(colour):
                            expiring.append(tok)
        if cells:
            n = max(n, max(cells) + 1)
        role = row.cells[0].attrs.get("data-role", "") if row.cells else ""
        gathered.append((row.attrs["data-name"], role, skills, expiring, is_import, cells, editable))

    issues: dict[str, str] = {}
    unknown: dict[str, str] = {}
    people: list[PersonDay] = []
    for name, role, skills, expiring, is_import, cells, editable in gathered:
        on: list[bool] = []
        bookable: list[bool] = []
        for i in range(n):
            if i in cells:
                c_on, c_book, key, detail = classify_cell(cells[i].attrs)
                if key:
                    unknown.setdefault(key, detail or "")
            else:
                c_on, c_book = False, False
            on.append(c_on)
            bookable.append(c_book)
        people.append(
            PersonDay(
                name=name,
                role=role,
                skills=frozenset(skills),
                expiring=frozenset(expiring),
                is_import=is_import,
                on=on,
                bookable=bookable,
                is_me=editable and not is_import,
            )
        )

    appliances: dict[str, list[str]] = {}
    unknown_status: set[str] = set()
    for label, statuses in app_rows.items():
        out = []
        for i in range(n):
            status, raw = parse_status(statuses.get(i, ""))
            if raw is not None:
                unknown_status.add(raw)
            out.append(status)
        appliances[label] = out

    starts, expected = day_slot_starts(day, tz, n)
    if n != expected:
        issues["slot_count"] = (
            f"{day}: schedule has {n} slots, expected {expected} for the local day"
        )
    for key, detail in unknown.items():
        issues[f"unknown_{key}"] = (
            f"Unknown booking cell ({key}, {detail}); treated as not available"
        )
    for raw in sorted(unknown_status):
        issues[f"status_{raw}"] = (
            f"Unknown appliance status {raw!r}; treated as not on the run"
        )
    return DaySchedule(day, starts, people, appliances, issues)


# ---------------------------------------------------------------------------
# brigade list (schedule page, after login)


@dataclass(frozen=True)
class Brigade:
    id: int
    name: str
    selected: bool


class _SelectParser(HTMLParser):
    def __init__(self, select_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self._want = select_id
        self._inside = False
        self._opt: dict[str, str] | None = None
        self._text: list[str] = []
        self.options: list[tuple[dict[str, str], str]] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v if v is not None else "") for k, v in attrs}
        if tag == "select" and a.get("id") == self._want:
            self._inside = True
        elif tag == "option" and self._inside:
            self._finish()
            self._opt, self._text = a, []

    def handle_endtag(self, tag):
        if tag == "option":
            self._finish()
        elif tag == "select" and self._inside:
            self._finish()
            self._inside = False

    def handle_data(self, data):
        if self._opt is not None:
            self._text.append(data)

    def _finish(self):
        if self._opt is not None:
            self.options.append((self._opt, "".join(self._text).strip()))
        self._opt = None


BRIGADE_SELECT_ID = "ctrlBrigade_dropBrigade"


def parse_brigades(html: str) -> list[Brigade]:
    p = _SelectParser(BRIGADE_SELECT_ID)
    p.feed(html)
    p.close()
    out: list[Brigade] = []
    for attrs, text in p.options:
        try:
            bid = int(attrs.get("value", ""))
        except ValueError:
            continue
        if bid <= 0 or not text:
            continue
        out.append(Brigade(bid, text, "selected" in attrs))
    return out
