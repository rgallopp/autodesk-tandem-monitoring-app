"""Human-facing labels and compact temporal charts; no API or write operations."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import html
import json
import math
import re

import altair as alt
import pandas as pd

DEFAULT_TIMEZONE = "America/New_York"


def local_time(value, zone=DEFAULT_TIMEZONE):
    return datetime.fromisoformat(value).astimezone(ZoneInfo(zone))


def clock_label(value, zone=DEFAULT_TIMEZONE):
    return local_time(value, zone).strftime("%I:%M %p").lstrip("0")


def lab_label(name):
    return re.sub(r"\s+(\d+)$", " "+chr(183)+r" \1", name)


def age_label(value, now):
    seconds = max(0, int((now - datetime.fromisoformat(value)).total_seconds()))
    if seconds < 60:
        return "Updated just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"Updated {minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    return f"Updated {hours} hour{'s' if hours != 1 else ''} ago"


def card_state(card, now):
    if card["measurement"] is None:
        return "No readings in this period", "Choose a longer history range.", "muted"
    if not 0 <= (now - datetime.fromisoformat(card["ingested_utc"])).total_seconds() <= 300:
        return "No recent reading", f"Last recorded: {card['measurement']:.1f} dB · {card['stored_status'] or 'Awaiting evaluation'}", "muted"
    if card["stored_status"] is None:
        return "Awaiting evaluation", "A reading is available; the stored status is empty.", "muted"
    if card["quality"] == "UNVERIFIED_STATUS":
        return "Status needs checking", "The reading and target do not match the stored status.", "muted"
    status = card["stored_status"]
    return status, "", "high" if status == "High" else "normal"


def card_html(card, now):
    state, note, tone = card_state(card, now)
    reading = "—" if card["measurement"] is None else f"{card['measurement']:.1f}"
    age = "No recorded time" if not card["ingested_utc"] else age_label(card["ingested_utc"], now)
    esc = html.escape
    return f'<div class="lab-card"><h3>{esc(lab_label(card["room"]))}</h3><div class="state {tone}">{esc(state)}</div><div class="reading">{reading}<span> dB</span></div><div class="target">Target {card["target"]:.1f} dB</div><div class="age">{esc(age)}</div><div class="note">{esc(note) if note else "&nbsp;"}</div></div>'


def details_rows(data, zone):
    return [{"Lab": lab_label(r["room"]),
             "Recorded at": local_time(r["ingested_utc"], zone).strftime("%b %d, %I:%M:%S %p").replace(" 0", " "),
             "Noise level (dB)": r["measurement"], "Current target (dB)": r["current_target"],
             "Compared with target": "Above target" if r["comparison"] == "Above current target" else "Within target",
             "Note": "Gap before this reading" if r["quality"] == "GAP_REVIEW" else "—"}
            for r in data["trends"]]


def chart_domain(data):
    values = [c["target"] for c in data["cards"]] + [r["measurement"] for r in data["trends"]]
    return [math.floor(min(values) - 5), math.ceil(max(values) + 5)]


def noise_chart(data, card, zone, domain):
    rows, segment = [], 0
    for r in data["trends"]:
        if r["room"] != card["room"]:
            continue
        if r["quality"] == "GAP_REVIEW":
            segment += 1
        rows.append({"Recorded at": local_time(r["ingested_utc"], zone),
                     "Noise level (dB)": r["measurement"], "segment": str(segment),
                     "Local time": local_time(r["ingested_utc"], zone).strftime("%b %d, %I:%M:%S %p %Z")})
    frame = pd.DataFrame(rows)
    if not rows:
        return None
    # Real timezone-aware instants drive positions. Explicit tick labels use the
    # configured IANA zone, independent of the browser's own timezone (including DST).
    start, end = min(r["Recorded at"] for r in rows), max(r["Recorded at"] for r in rows)
    lo, hi = start.timestamp() * 1000, end.timestamp() * 1000
    if lo == hi:
        lo, hi = lo - 60000, hi + 60000
    ticks = [round(lo + (hi - lo) * n / 3) for n in range(4)]
    labels = {str(t): datetime.fromtimestamp(t / 1000, timezone.utc).astimezone(ZoneInfo(zone)).strftime("%I:%M %p").lstrip("0") for t in ticks}
    tick_dates, seen_labels = [], set()
    for tick in ticks:
        if labels[str(tick)] in seen_labels:
            continue
        seen_labels.add(labels[str(tick)])
        d = datetime.fromtimestamp(tick / 1000, timezone.utc)
        tick_dates.append(alt.DateTime(utc=True, year=d.year, month=d.month, date=d.day,
                                      hours=d.hour, minutes=d.minute, seconds=d.second, milliseconds=d.microsecond // 1000))
    axis = alt.Axis(title=None, labelAngle=0, values=tick_dates,
                    labelExpr=json.dumps(labels) + "[+datum.value]", labelOverlap=True)
    base = alt.Chart(frame).encode(
        x=alt.X("Recorded at:T", axis=axis, scale=alt.Scale(domain=[datetime.fromtimestamp(lo / 1000, timezone.utc), datetime.fromtimestamp(hi / 1000, timezone.utc)])),
        y=alt.Y("Noise level (dB):Q", title="Noise level (dB)", scale=alt.Scale(domain=domain, zero=False)),
        tooltip=[alt.Tooltip("Local time:N", title="Recorded at"), alt.Tooltip("Noise level (dB):Q", format=".1f")])
    line = base.mark_line(color="#4386bf", strokeWidth=2).encode(detail="segment:N")
    points = base.mark_point(color="#4386bf", filled=True, size=55)
    target = alt.Chart(pd.DataFrame([{"target": card["target"], "label": f'Target {card["target"]:.1f} dB'}]))
    rule = target.mark_rule(strokeDash=[5, 4], color="#a87120").encode(y=alt.Y("target:Q"))
    # Anchor label at the left edge without clipping.
    label = target.mark_text(align="left", x=5, dy=-8, color="#b88b41").encode( y="target:Q", text="label:N")
    return (line + points + rule + label).properties(height=220).configure_view(stroke=None)
