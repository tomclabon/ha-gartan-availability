"""Synthetic Gartan-style HTML for tests (mirrors the structure described in
the design notes; swap in scrubbed real captures under tests/data/ when you have them)."""
from __future__ import annotations

N = 96


def _skills(skills):
    return "".join(f'<font color="#0000FF">{s}</font> ' for s in skills)


def person_row(idx, name, skills, cells, mine=False, imp=False):
    """cells: 'on' (white), 'A' (code 32), 'book' (blue dash), 'off' (grey O),
    or a callable i -> kind; a list/str of kinds per slot is also accepted."""
    prefix = "emp" if mine else "empRO"
    tds = [f'<td class="nameCol">{name}</td>']
    for i in range(N):
        kind = cells(i) if callable(cells) else cells
        if kind == "on":
            attrs = 'class="schTD"'
        elif kind == "A":
            attrs = 'class="schTD" data-codeId="32" data-alias="Available Crew"'
        elif kind == "C":
            attrs = 'class="schTD_DefaultBlackText" data-codeId="35" data-alias="Co-responder"'
        elif kind == "book":
            attrs = 'class="schTD_AutoContract"'
        elif kind == "B":
            attrs = 'class="schTD_AutoContract" data-codeId="31" data-Bid="9" data-alias="Booking"'
        elif kind == "weird":
            attrs = 'class="schTD" data-codeId="99" data-alias="Mystery"'
        else:
            attrs = 'class="schTD_off" data-codeId="1" data-alias="Off"'
        tds.append(f'<td id="{prefix}_{idx}-{i}" {attrs}>&nbsp;</td>')
    tds.append(f'<td class="skillCol">{_skills(skills)}</td>')
    extra = ' data-id="0"' if imp else ""
    return f'<tr class="employee" data-name="{name}"{extra}>{"".join(tds)}</tr>'


def app_row(label, status_fn, rowid=8):
    tds = [f"<td>{label}</td>"]
    for i in range(N):
        st = status_fn(i)
        hh, mm = divmod(i * 15, 60)
        h2, m2 = divmod(i * 15 + 15, 60)
        title = f"{label} ({hh:02d}{mm:02d} - {h2:02d}{m2:02d}) {st}"
        tds.append(f'<td id="app_{rowid}_{i}" title="{title}">&nbsp;</td>')
    return f'<tr class="appliance">{"".join(tds)}</tr>'


def table(people, p1_fn, extra_rows=""):
    divider = '<tr class="importDivider"><td>Imports</td></tr>'
    normal = [p for p in people if not p.get("imp")]
    imports = [p for p in people if p.get("imp")]
    rows = [person_row(i + 1, **{k: v for k, v in p.items()}) for i, p in enumerate(normal)]
    rows.append(divider)
    rows += [person_row(100 + i, **p) for i, p in enumerate(imports)]
    rows.append(app_row("KT52P1", p1_fn))
    rows.append(extra_rows)
    return "<table>" + "".join(rows) + "</table>"


def slot(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 4 + int(m) // 15


def window(a: str, b: str, kind, otherwise="off"):
    s, e = slot(a), slot(b)
    return lambda i: kind if s <= i < e else otherwise
