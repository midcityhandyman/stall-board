"""Two views of one scan: a plain text summary and a static HTML board."""

from __future__ import annotations

from html import escape

from .db import STATES
from .scan import FLAGS, Finding, ScanResult, age_hours, format_age

STATE_LABELS = {
    "queued": "Queued",
    "in_progress": "In progress",
    "blocked": "Blocked",
    "waiting_human": "Waiting on a human",
    "done": "Done",
}
FLAG_LABELS = {
    "waiting_human": "WAITING ON A HUMAN",
    "blocked": "BLOCKED",
    "idle": "IDLE",
}


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 3] + "..."


def render_text(result: ScanResult) -> str:
    counts = result.state_counts
    lines = [
        f"STALL BOARD  {result.now.strftime('%Y-%m-%d %H:%M')} UTC",
        f"{len(result.tasks)} tasks: "
        + ", ".join(f"{counts[s]} {s}" for s in STATES),
        f"Flagged: {len(result.findings)} "
        f"({result.alerts} alert, {result.warns} warn)",
    ]
    if not result.findings:
        lines += ["", "Nothing is stalled. Every open task has moved recently."]
    for flag in FLAGS:
        group = result.by_flag(flag)
        if not group:
            continue
        lines += ["", f"{FLAG_LABELS[flag]} ({len(group)})"]
        for f in group:
            lines.append(
                f"  [{f.severity.upper():5}] {f.task.id:<6} "
                f"{_clip(f.task.title, 46):<46} "
                f"{(f.task.owner or '(unowned)'):<16} {f.reason}"
            )
    owners = result.flagged_by_owner()
    if owners:
        lines += ["", "Flagged by owner: "
                  + ", ".join(f"{name} {n}" for name, n in owners.items())]
    open_count = len(result.tasks) - counts["done"]
    lines.append(f"Moving fine: {open_count - len(result.findings)} of {open_count} open tasks")
    return "\n".join(lines) + "\n"


CSS = """
:root { --bg:#f4f5f7; --card:#fff; --ink:#1c2330; --muted:#667085; --line:#d9dde4;
        --alert:#c0362c; --warn:#b7791f; --ok:#2f7d4f; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#14181f; --card:#1e242e; --ink:#e6e9ef; --muted:#98a2b3; --line:#323a47;
          --alert:#ef6b61; --warn:#e0a94a; --ok:#5fbf86; }
}
* { box-sizing: border-box; }
body { margin:0; padding:24px 16px; background:var(--bg); color:var(--ink);
       font:14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
h1 { margin:0 0 4px; font-size:22px; }
h2 { margin:0 0 10px; font-size:13px; text-transform:uppercase; letter-spacing:.06em;
     color:var(--muted); }
.meta { color:var(--muted); margin:0 0 16px; }
.stats { display:flex; flex-wrap:wrap; gap:8px; margin:0 0 20px; padding:0; list-style:none; }
.stats li { background:var(--card); border:1px solid var(--line); border-radius:8px;
            padding:8px 12px; }
.stats b { font-size:18px; display:block; }
.attention { background:var(--card); border:1px solid var(--line); border-radius:8px;
             padding:14px 16px; margin-bottom:20px; }
.attention ul { margin:0; padding-left:18px; }
.board { display:grid; gap:12px; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); }
.col { min-width:0; }
.card { background:var(--card); border:1px solid var(--line); border-left:4px solid var(--line);
        border-radius:8px; padding:10px 12px; margin-bottom:10px; overflow-wrap:anywhere; }
.card.alert { border-left-color:var(--alert); }
.card.warn { border-left-color:var(--warn); }
.card.ok { border-left-color:var(--ok); }
.card .id { color:var(--muted); font-size:12px; }
.card .title { font-weight:600; margin:2px 0 6px; }
.card .row { color:var(--muted); font-size:12px; }
.badge { display:inline-block; font-size:11px; font-weight:700; border-radius:4px;
         padding:1px 6px; margin-right:4px; color:#fff; }
.badge.alert { background:var(--alert); }
.badge.warn { background:var(--warn); }
.reason { margin-top:6px; font-size:12px; }
.empty { color:var(--muted); font-style:italic; }
"""


def _card(task, finding: Finding | None, now) -> str:
    if finding:
        css = finding.severity
    elif task.state == "done":
        css = ""
    else:
        css = "ok"
    parts = [
        f'<div class="card {css}" data-task="{escape(task.id)}">',
        f'<div class="id">{escape(task.id)}</div>',
        f'<div class="title">{escape(task.title)}</div>',
        f'<div class="row">Owner: {escape(task.owner or "(unowned)")}</div>',
        f'<div class="row">Last moved: {escape(format_age(age_hours(task, now)))} ago</div>',
    ]
    if task.note:
        parts.append(f'<div class="row">Note: {escape(task.note)}</div>')
    if finding:
        parts.append(
            f'<div class="reason"><span class="badge {finding.severity}">'
            f'{escape(finding.flag.replace("_", " "))}</span>{escape(finding.reason)}</div>'
        )
    parts.append("</div>")
    return "".join(parts)


def render_html(result: ScanResult, title: str = "Stall board") -> str:
    counts = result.state_counts
    stamp = result.now.strftime("%Y-%m-%d %H:%M UTC")
    stats = "".join(
        f"<li><b>{counts[s]}</b>{escape(STATE_LABELS[s])}</li>" for s in STATES
    )
    stats += f"<li><b>{result.alerts}</b>Alerts</li><li><b>{result.warns}</b>Warnings</li>"

    if result.findings:
        items = "".join(
            f'<li><span class="badge {f.severity}">{escape(f.severity)}</span>'
            f"<b>{escape(f.task.id)}</b> {escape(f.task.title)} "
            f"({escape(f.task.owner or '(unowned)')}): {escape(f.reason)}</li>"
            for f in result.findings
        )
        attention = f"<ul>{items}</ul>"
    else:
        attention = '<p class="empty">Nothing is stalled.</p>'

    columns = []
    for state in STATES:
        tasks = [t for t in result.tasks if t.state == state]
        tasks.sort(key=lambda t: (t.last_moved_at, t.id))
        cards = "".join(_card(t, result.finding_for(t.id), result.now) for t in tasks)
        if not cards:
            cards = '<p class="empty">Empty</p>'
        columns.append(
            f'<section class="col" data-state="{state}">'
            f"<h2>{escape(STATE_LABELS[state])} ({len(tasks)})</h2>{cards}</section>"
        )

    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title><style>{CSS}</style></head><body>\n"
        f"<h1>{escape(title)}</h1>\n"
        f'<p class="meta">Scanned {escape(stamp)}. {len(result.tasks)} tasks, '
        f"{len(result.findings)} flagged. Static snapshot: rerun the scan to refresh.</p>\n"
        f'<ul class="stats">{stats}</ul>\n'
        f'<section class="attention"><h2>Needs attention</h2>{attention}</section>\n'
        f'<main class="board">{"".join(columns)}</main>\n'
        "</body></html>\n"
    )
