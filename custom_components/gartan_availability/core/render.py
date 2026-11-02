"""Widget pictures (PNG). Needs Pillow only.

Sized for Android home-screen widgets, which scale the picture to fit:
- week:      ~3.8:1, for a 4x1 widget
- crew:      ~2.8:1, for a 3x1 widget
- call-outs: square, for a 1x1 widget
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo

from .const import ON_STATUSES, SLOT, STATUS_OFF_STATION, STATUS_UNKNOWN
from .view import View

# colours (RGB)
BG = (24, 24, 27)
TEXT = (230, 230, 230)
MUTED = (140, 140, 145)
NOTHING = (52, 52, 58)  # neither on
NO_DATA = (85, 85, 92)  # appliance status unknown and you not on, or no data
BOTH = (0, 255, 0)  # appliance on and you on
APP_ONLY = (0, 0, 255)  # appliance on, you not
ME_ONLY = (255, 165, 0)  # you on, appliance not
OUT = (255, 51, 255)  # appliance out on a call
HOUR_TICK = (110, 110, 116)  # subtle hourly marks
NOW = (255, 255, 255)
WARN = (239, 83, 80)


@dataclass(frozen=True)
class RenderInput:
    view: View
    appliance: str
    tz: tzinfo
    now: datetime  # aware
    fetched: dict[date, datetime] = field(default_factory=dict)  # last fetch per local day
    today_stale_after: timedelta = timedelta(minutes=15)
    day_stale_after: timedelta = timedelta(hours=2)
    days: int = 7
    callouts: list = field(default_factory=list)  # history CallOut objects, any appliance
    counts: dict = field(default_factory=dict)  # {period: {"all": n, "me": n}} for appliance


def _font(size: int):
    from PIL import ImageFont

    try:
        return ImageFont.load_default(size=size)  # scalable, bundled with Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _fit(d, text: str, font, room: float) -> str:
    """Shorten text with an ellipsis to fit `room` pixels."""
    if d.textlength(text, font=font) <= room:
        return text
    while text and d.textlength(text + "…", font=font) > room:
        text = text[:-1]
    return (text + "…") if text else ""


def _hhmm(at: datetime, tz: tzinfo, today: date) -> str:
    loc = at.astimezone(tz)
    return f"{loc:%H:%M}" if loc.date() == today else f"{loc:%a %H:%M}"


# ---------------------------------------------------------------------------
# freshness: today's fetch, and the oldest fetch of the other days


def freshness(inp: RenderInput) -> list[tuple[str, tuple[int, int, int]]]:
    """[("Today 18:55", colour), ("Week 18:30", colour)]."""
    today = inp.now.astimezone(inp.tz).date()
    out = []
    got = inp.fetched.get(today)
    if got is None:
        out.append(("Today -", WARN))
    else:
        stale = inp.now - got > inp.today_stale_after
        out.append((f"Today {_hhmm(got, inp.tz, today)}", WARN if stale else MUTED))
    others = [today + timedelta(days=k) for k in range(1, inp.days)]
    times = [inp.fetched.get(d) for d in others]
    if not others:
        return out
    if any(t is None for t in times):
        out.append(("Week -", WARN))
    else:
        oldest = min(times)
        stale = inp.now - oldest > inp.day_stale_after
        out.append((f"Week {_hhmm(oldest, inp.tz, today)}", WARN if stale else MUTED))
    return out


# ---------------------------------------------------------------------------
# week (4x1)


def _day_slots(view: View, tz: tzinfo, first: date, days: int):
    """{local date: [(start_hour, end_hour, index)]} for each 15-minute slot."""
    out: dict[date, list[tuple[float, float, int]]] = {}
    last = first + timedelta(days=days)
    for i, s in enumerate(view.timeline.starts):
        loc = s.astimezone(tz)
        d = loc.date()
        if first <= d < last:
            h = loc.hour + loc.minute / 60
            out.setdefault(d, []).append((h, h + SLOT.total_seconds() / 3600, i))
    return out


def slot_colour(app_status: str | None, me_on: bool) -> tuple[int, int, int]:
    if app_status == STATUS_OFF_STATION:
        return OUT
    app_on = app_status in ON_STATUSES
    if app_on and me_on:
        return BOTH
    if app_on:
        return APP_ONLY
    if me_on:
        return ME_ONLY
    return NO_DATA if app_status in (None, STATUS_UNKNOWN) else NOTHING


def render_week_png(inp: RenderInput, width: int = 1000) -> bytes:
    from PIL import Image, ImageDraw

    s = width / 1000
    px = lambda v: max(1, round(v * s))  # noqa: E731
    f_top, f_axis, f_day = _font(px(22)), _font(px(17)), _font(px(22))

    pad, label_w = px(8), px(70)
    top_h, axis_h, row_h, bar_h = px(28), px(19), px(28), px(23)
    height = pad + top_h + axis_h + inp.days * row_h + pad - (row_h - bar_h)
    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)

    view, tz = inp.view, inp.tz
    app = view.appliances.get(inp.appliance)
    me = view.timeline.series.get(view.me_key) if view.me_key else None
    now_loc = inp.now.astimezone(tz)
    first = now_loc.date()
    x0, x1 = pad + label_w, width - pad
    span = x1 - x0
    hx = lambda h: x0 + span * h / 24  # noqa: E731

    # top bar: legend (aligned with the bars) left, freshness right
    x, y = x0, pad
    for colour, label in ((APP_ONLY, inp.appliance), (ME_ONLY, "You"), (BOTH, "Both"), (OUT, "Out")):
        d.rounded_rectangle((x, y + px(4), x + px(16), y + px(20)), radius=px(3), fill=colour)
        x += px(21)
        d.text((x, y), label, font=f_top, fill=TEXT)
        x += d.textlength(label, font=f_top) + px(14)
    xr = width - pad
    for text, colour in reversed(freshness(inp)):
        w = d.textlength(text, font=f_top)
        d.text((xr - w, y), text, font=f_top, fill=colour)
        xr -= w + px(14)

    # hour axis
    ay = pad + top_h
    for h in (0, 6, 12, 18, 24):
        lbl = f"{h:02d}"
        lw = d.textlength(lbl, font=f_axis)
        d.text((min(max(hx(h) - lw / 2, x0), x1 - lw), ay - px(1)), lbl, font=f_axis, fill=MUTED)

    # one combined bar per day
    slots = _day_slots(view, tz, first, inp.days)
    top = ay + axis_h
    for r in range(inp.days):
        day = first + timedelta(days=r)
        by = top + r * row_h
        d.text((pad, by), "Today" if r == 0 else f"{day:%a}", font=f_day, fill=TEXT if r == 0 else MUTED)
        d.rectangle((x0, by, x1, by + bar_h), fill=NOTHING if day in slots else NO_DATA)
        for start_h, end_h, i in slots.get(day, []):
            colour = slot_colour(app.effective[i] if app else None, bool(me is not None and me.on[i]))
            if colour != NOTHING:
                d.rectangle((hx(start_h), by, hx(end_h), by + bar_h), fill=colour)
        for h in range(1, 24):
            d.line((hx(h), by, hx(h), by + bar_h), fill=HOUR_TICK, width=1)
        if r == 0:  # dim the past, draw "now"
            nh = now_loc.hour + now_loc.minute / 60
            w = max(1, int(hx(nh) - x0))
            overlay = Image.new("RGBA", (w, bar_h + 1), BG + (150,))
            img.paste(overlay, (x0, by), overlay)
            d.line((hx(nh), by - px(3), hx(nh), by + bar_h + px(3)), fill=NOW, width=px(3))
    return _png(img)


# ---------------------------------------------------------------------------
# crew (3x1): who is on now (until when), who is off (from when)


def display_name(name: str, imported: bool) -> str:
    """'SURNAME, I' -> 'I Surname'; imports keep their own text, title-cased."""
    if "," in name and not imported:
        surname, initials = (p.strip() for p in name.split(",", 1))
        label = f"{initials} {surname.title()}".strip()
    else:
        label = name.title()
    return f"{label} (import)" if imported else label


@dataclass
class CrewRow:
    name: str
    skills: list[str]
    me: bool
    on: bool
    change: datetime | None  # next off (if on) or next on (if off)
    beyond: bool  # change is past the known schedule


def crew_rows(view: View, now: datetime) -> list[CrewRow]:
    from .model import next_on_off, runs_from_flags

    tl = view.timeline
    i = tl.index_at(now)
    rows: list[CrewRow] = []
    if i is None:
        return rows
    for s in tl.series.values():
        on = s.on[i]
        nxt_on, nxt_off, _ = next_on_off(runs_from_flags(tl, s.on), now, tl.end)
        change = nxt_off if on else nxt_on
        rows.append(
            CrewRow(display_name(s.name, s.imported), sorted(s.skills), s.key == view.me_key,
                    on, change, on and change is None)
        )
    far = datetime.max.replace(tzinfo=now.tzinfo)
    rows.sort(key=lambda r: (r.change or far, r.name))
    return rows


def _short_when(t: datetime | None, tz: tzinfo, today: date, on: bool) -> str:
    if t is None:
        return "7d+" if on else "-"
    return _hhmm(t, tz, today)


def render_crew_png(inp: RenderInput, width: int = 960, max_rows: int = 8) -> bytes:
    from PIL import Image, ImageDraw

    s = width / 960
    px = lambda v: max(1, round(v * s))  # noqa: E731
    f_title, f_row, f_small = _font(px(27)), _font(px(27)), _font(px(20))

    tz = inp.tz
    today = inp.now.astimezone(tz).date()
    rows = crew_rows(inp.view, inp.now)
    columns = ([r for r in rows if r.on], [r for r in rows if not r.on])

    pad, gap = px(10), px(22)
    title_h, row_h = px(36), px(34)
    height = pad + title_h + max_rows * row_h + pad
    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)
    col_w = (width - 2 * pad - gap) / 2

    stamp, stamp_colour = freshness(inp)[0]
    for k, (title, chip, items) in enumerate(
        ((f"On ({len(columns[0])})", BOTH, columns[0]), (f"Off ({len(columns[1])})", MUTED, columns[1]))
    ):
        cx = pad + k * (col_w + gap)
        d.rounded_rectangle((cx, pad + px(7), cx + px(16), pad + px(23)), radius=px(3), fill=chip)
        d.text((cx + px(22), pad), title, font=f_title, fill=TEXT)
        if k == 1:
            sw = d.textlength(stamp, font=f_small)
            d.text((cx + col_w - sw, pad + px(5)), stamp, font=f_small, fill=stamp_colour)
        d.line((cx, pad + title_h - px(5), cx + col_w, pad + title_h - px(5)), fill=NOTHING, width=px(2))
        shown = items if len(items) <= max_rows else items[: max_rows - 1]
        for j, r in enumerate(shown):
            ry = pad + title_h + j * row_h
            when = _short_when(r.change, tz, today, r.on)
            soon = r.change is not None and r.change - inp.now <= timedelta(hours=1)
            ww = d.textlength(when, font=f_row)
            d.text((cx + col_w - ww, ry), when, font=f_row, fill=TEXT if soon else MUTED)
            name = _fit(d, r.name.replace(" (import)", "*"), f_row, col_w - ww - px(12))
            d.text((cx, ry), name, font=f_row,
                   fill=ME_ONLY if r.me else (TEXT if r.on else MUTED))
        if len(items) > max_rows:
            ry = pad + title_h + (max_rows - 1) * row_h
            d.text((cx, ry), f"+{len(items) - max_rows + 1} more", font=f_row, fill=MUTED)
    return _png(img)


# ---------------------------------------------------------------------------
# call-outs (1x1): the last few for the appliance, with counts


def render_callouts_png(inp: RenderInput, size: int = 400, max_rows: int = 5) -> bytes:
    from PIL import Image, ImageDraw

    s = size / 400
    px = lambda v: max(1, round(v * s))  # noqa: E731
    f_head, f_row, f_foot = _font(px(30)), _font(px(34)), _font(px(28))

    tz = inp.tz
    now_loc = inp.now.astimezone(tz)
    today = now_loc.date()
    items = [c for c in inp.callouts if c.appliance == inp.appliance and c.start <= inp.now]
    items = sorted(items, key=lambda c: c.start, reverse=True)[:max_rows]

    img = Image.new("RGB", (size, size), BG)
    d = ImageDraw.Draw(img)
    pad = px(14)

    stamp, stamp_colour = freshness(inp)[0]
    head_colour = WARN if stamp_colour == WARN else MUTED
    d.text((pad, pad), _fit(d, f"{inp.appliance} call-outs", f_head, size - 2 * pad), font=f_head,
           fill=head_colour)

    y, row_h = pad + px(44), px(50)
    if not items:
        d.text((pad, y), "None yet", font=f_row, fill=MUTED)
    for c in items:
        loc = c.start.astimezone(tz)
        if loc.date() == today:
            when = f"Today {loc:%H:%M}"
        elif loc.date() == today - timedelta(days=1):
            when = f"Yest {loc:%H:%M}"
        elif (today - loc.date()).days < 7:
            when = f"{loc:%a %H:%M}"
        else:
            when = f"{loc:%d %b}"
        live = c.end > inp.now
        minutes = int((min(c.end, inp.now) - c.start).total_seconds() // 60)
        dur = "now" if live else (f"{minutes // 60}h{minutes % 60:02d}" if minutes >= 60 else f"{minutes}m")
        colour = OUT if live else (ME_ONLY if c.me else MUTED)
        dw = d.textlength(dur, font=f_row)
        d.text((size - pad - dw, y), dur, font=f_row, fill=colour)
        d.text((pad, y), _fit(d, when, f_row, size - 2 * pad - dw - px(10)), font=f_row, fill=colour)
        y += row_h

    week = inp.counts.get("this_week", {})
    month = inp.counts.get("last_4_weeks", {})
    if week or month:
        foot = f"Wk {week.get('all', 0)} ({week.get('me', 0)}) · 4wk {month.get('all', 0)} ({month.get('me', 0)})"
        fy = size - pad - px(30)
        d.line((pad, fy - px(8), size - pad, fy - px(8)), fill=NOTHING, width=px(2))
        d.text((pad, fy), _fit(d, foot, f_foot, size - 2 * pad), font=f_foot, fill=MUTED)
    return _png(img)
