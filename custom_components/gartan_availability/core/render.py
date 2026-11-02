"""Draw the week as a PNG (appliance + your availability). Needs Pillow only.

Layout: a header (legend, then "Updated HH:MM", or the last data time in red if
today's fetch is failing), an hour axis, then one row per local day. Each row has
the day label with "Updated HH:MM" underneath, and one bar spanning 00:00-24:00
coloured by the combination of appliance and you, with a white mark every hour.
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


def _font(size: int):
    from PIL import ImageFont

    try:
        return ImageFont.load_default(size=size)  # scalable, bundled with Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


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


def _stamp(at: datetime, tz: tzinfo, today: date) -> str:
    loc = at.astimezone(tz)
    return f"Updated {loc:%H:%M}" if loc.date() == today else f"Updated {loc:%a %H:%M}"


def render_week_png(inp: RenderInput, width: int = 960) -> bytes:
    from PIL import Image, ImageDraw

    scale = width / 960
    px = lambda v: max(1, round(v * scale))  # noqa: E731
    f_head, f_body, f_small, f_tiny = _font(px(26)), _font(px(24)), _font(px(19)), _font(px(12))

    pad, label_w = px(16), px(110)
    header_h, axis_h, row_h, bar_h = px(48), px(24), px(52), px(36)
    height = pad + header_h + axis_h + inp.days * row_h + pad
    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)

    view, tz = inp.view, inp.tz
    app = view.appliances.get(inp.appliance)
    me = view.timeline.series.get(view.me_key) if view.me_key else None
    now_loc = inp.now.astimezone(tz)
    first = now_loc.date()

    # --- header: legend left, one timestamp right
    x, y = pad + label_w, pad  # legend starts where the bars start
    legend = ((APP_ONLY, inp.appliance), (ME_ONLY, "You"), (BOTH, "Both"), (OUT, "Out"))
    for colour, label in legend:
        d.rounded_rectangle((x, y + px(6), x + px(22), y + px(28)), radius=px(4), fill=colour)
        x += px(30)
        d.text((x, y + px(2)), label, font=f_head, fill=TEXT)
        x += d.textlength(label, font=f_head) + px(22)
    today_fetch = inp.fetched.get(first)
    if today_fetch is None:
        right, colour = "No data", WARN
    elif inp.now - today_fetch > inp.today_stale_after:
        right, colour = "Data " + _stamp(today_fetch, tz, first)[len("Updated "):], WARN
    else:
        right, colour = f"Updated {now_loc:%H:%M}", MUTED
    tw = d.textlength(right, font=f_head)
    d.text((width - pad - tw, y + px(2)), right, font=f_head, fill=colour)

    # --- hour axis (milestones only)
    x0, x1 = pad + label_w, width - pad
    span = x1 - x0
    hx = lambda h: x0 + span * h / 24  # noqa: E731
    ay = pad + header_h
    for h in (0, 6, 12, 18, 24):
        lbl = f"{h:02d}"
        lw = d.textlength(lbl, font=f_small)
        d.text((min(max(hx(h) - lw / 2, x0), x1 - lw), ay), lbl, font=f_small, fill=MUTED)

    # --- one combined bar per day
    slots = _day_slots(view, tz, first, inp.days)
    top = ay + axis_h
    for r in range(inp.days):
        day = first + timedelta(days=r)
        ry = top + r * row_h
        d.text((pad, ry - px(1)), "Today" if r == 0 else f"{day:%a %d}", font=f_body,
               fill=TEXT if r == 0 else MUTED)
        got = inp.fetched.get(day)
        if got is None:
            stamp, stamp_colour = "No data", WARN
        else:
            limit = inp.today_stale_after if r == 0 else inp.day_stale_after
            stamp = _stamp(got, tz, first)
            stamp_colour = WARN if inp.now - got > limit else MUTED
        d.text((pad, ry + px(25)), stamp, font=f_tiny, fill=stamp_colour)

        by = ry
        d.rectangle((x0, by, x1, by + bar_h), fill=NOTHING if day in slots else NO_DATA)
        for start_h, end_h, i in slots.get(day, []):
            colour = slot_colour(
                app.effective[i] if app else None, bool(me is not None and me.on[i])
            )
            if colour != NOTHING:
                d.rectangle((hx(start_h), by, hx(end_h), by + bar_h), fill=colour)
        for h in range(1, 24):
            d.line((hx(h), by, hx(h), by + bar_h), fill=HOUR_TICK, width=1)
        if r == 0:  # dim the past, draw "now"
            nh = now_loc.hour + now_loc.minute / 60
            w = max(1, int(hx(nh) - x0))
            overlay = Image.new("RGBA", (w, bar_h + 1), BG + (150,))
            img.paste(overlay, (x0, by), overlay)
            d.line((hx(nh), by - px(5), hx(nh), by + bar_h + px(5)), fill=NOW, width=px(3))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# who is on / off now


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
    end = tl.end
    for s in tl.series.values():
        on = s.on[i]
        nxt_on, nxt_off, _ = next_on_off(runs_from_flags(tl, s.on), now, end)
        change = nxt_off if on else nxt_on
        rows.append(
            CrewRow(
                name=display_name(s.name, s.imported),
                skills=sorted(s.skills),
                me=s.key == view.me_key,
                on=on,
                change=change,
                beyond=on and change is None,  # on until past the known week
            )
        )
    far = datetime.max.replace(tzinfo=now.tzinfo)
    rows.sort(key=lambda r: (r.change or far, r.name))
    return rows


def _when(t: datetime | None, tz: tzinfo, today: date, on: bool) -> str:
    if t is None:
        return "beyond week" if on else "not this week"
    loc = t.astimezone(tz)
    prefix = "until " if on else "from "
    return prefix + (f"{loc:%H:%M}" if loc.date() == today else f"{loc:%a %H:%M}")


def _header_stamp(inp: RenderInput, today: date):
    fetched = inp.fetched.get(today)
    now_loc = inp.now.astimezone(inp.tz)
    if fetched is None:
        return "No data", WARN
    if inp.now - fetched > inp.today_stale_after:
        return "Data " + _stamp(fetched, inp.tz, today)[len("Updated "):], WARN
    return f"Updated {now_loc:%H:%M}", MUTED


def render_crew_png(inp: RenderInput, width: int = 960) -> bytes:
    from PIL import Image, ImageDraw

    scale = width / 960
    px = lambda v: max(1, round(v * scale))  # noqa: E731
    f_head, f_name, f_time, f_skill = _font(px(26)), _font(px(24)), _font(px(22)), _font(px(15))

    tz = inp.tz
    now_loc = inp.now.astimezone(tz)
    today = now_loc.date()
    rows = crew_rows(inp.view, inp.now)
    on_rows = [r for r in rows if r.on]
    off_rows = [r for r in rows if not r.on]

    pad, col_gap = px(16), px(24)
    title_h, row_h = px(40), px(38)
    n = max(len(on_rows), len(off_rows), 1)
    height = pad + title_h + n * row_h + pad
    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)

    # stamp: right-aligned on the title line, above the Off column
    right, colour = _header_stamp(inp, today)
    tw = d.textlength(right, font=f_time)
    d.text((width - pad - tw, pad + px(4)), right, font=f_time, fill=colour)

    col_w = (width - 2 * pad - col_gap) / 2
    columns = (
        (pad, f"On now ({len(on_rows)})", BOTH, on_rows),
        (pad + col_w + col_gap, f"Off now ({len(off_rows)})", MUTED, off_rows),
    )
    ty = pad
    for cx, title, title_colour, items in columns:
        d.rounded_rectangle((cx, ty + px(8), cx + px(18), ty + px(26)), radius=px(4), fill=title_colour)
        d.text((cx + px(26), ty + px(2)), title, font=f_head, fill=TEXT)
        d.line((cx, ty + title_h - px(6), cx + col_w, ty + title_h - px(6)), fill=NOTHING, width=px(2))
        for k, r in enumerate(items):
            ry = ty + title_h + k * row_h
            when = _when(r.change, tz, today, r.on)
            ww = d.textlength(when, font=f_time)
            soon = r.change is not None and r.change - inp.now <= timedelta(hours=1)
            d.text((cx + col_w - ww, ry + px(6)), when, font=f_time, fill=TEXT if soon else MUTED)
            name_colour = ME_ONLY if r.me else (TEXT if r.on else MUTED)
            d.text((cx, ry + px(4)), r.name, font=f_name, fill=name_colour)
            nx = cx + d.textlength(r.name, font=f_name) + px(10)
            skills = " ".join(r.skills)
            room = cx + col_w - ww - px(12) - nx
            if skills and room > px(30):
                while skills and d.textlength(skills, font=f_skill) > room:
                    skills = skills[: skills.rfind(" ")] if " " in skills else ""
                d.text((nx, ry + px(12)), skills, font=f_skill, fill=MUTED)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
