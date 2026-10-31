#!/usr/bin/python3
"""Copy upcoming myCourseVille assignments into Apple Reminders.

Downloads the myCourseVille iCal feed, picks the "Assignment due" events
that are still in the future, and adds each one as a reminder due at the
real deadline. Every added event UID is remembered in state.json, so a
reminder you complete or delete is never re-created.

Usage:
    /usr/bin/python3 sync.py            # add new assignments to Reminders
    /usr/bin/python3 sync.py --dry-run  # only print what would be added
"""

from __future__ import annotations

import html
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"

ASSIGNMENT_PREFIX = "Assignment due:"
DEFAULT_TIMEZONE = "Asia/Bangkok"

# Arguments are passed through argv rather than spliced into the script, so
# quotes or backslashes in an assignment title cannot break the AppleScript.
ADD_REMINDER_SCRIPT = """
on run argv
    set listName to item 1 of argv
    set theName to item 2 of argv
    set theBody to item 3 of argv
    set d to current date
    set day of d to 1
    set year of d to (item 4 of argv) as integer
    set month of d to (item 5 of argv) as integer
    set day of d to (item 6 of argv) as integer
    set hours of d to (item 7 of argv) as integer
    set minutes of d to (item 8 of argv) as integer
    set seconds of d to 0
    tell application "Reminders"
        if not (exists list listName) then make new list with properties {name:listName}
        tell list listName to make new reminder with properties {name:theName, body:theBody, due date:d}
    end tell
end run
"""


# --- iCal parsing -----------------------------------------------------------

def unfold(text: str) -> list[str]:
    """Join folded iCal lines (continuations start with a space or tab)."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def unescape_text(value: str) -> str:
    value = (
        value.replace("\\n", "\n").replace("\\N", "\n")
        .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
    )
    # myCourseVille also HTML-escapes its text (e.g. "&amp;").
    return html.unescape(value)


def parse_datetime(params: str, value: str, default_tz: ZoneInfo) -> datetime:
    """Parse an iCal date or date-time into an aware datetime."""
    if "VALUE=DATE" in params and "VALUE=DATE-TIME" not in params:
        # All-day: treat the end of that day as the deadline.
        day = datetime.strptime(value, "%Y%m%d")
        return day.replace(hour=23, minute=59, tzinfo=default_tz)
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    tz = default_tz
    for param in params.split(";"):
        if param.startswith("TZID="):
            tz = ZoneInfo(param[len("TZID="):])
    return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=tz)


def parse_events(text: str) -> list[dict]:
    lines = unfold(text)
    tz_name = DEFAULT_TIMEZONE
    for line in lines:
        if line.startswith("X-WR-TIMEZONE:"):
            tz_name = line.split(":", 1)[1].strip()
    default_tz = ZoneInfo(tz_name)

    events: list[dict] = []
    current: dict | None = None
    depth = 0  # nesting inside the VEVENT (VALARM blocks have their own fields)
    for line in lines:
        if line == "BEGIN:VEVENT":
            current, depth = {}, 0
            continue
        if current is None:
            continue
        if line == "END:VEVENT":
            events.append(current)
            current = None
            continue
        if line.startswith("BEGIN:"):
            depth += 1
            continue
        if line.startswith("END:"):
            depth -= 1
            continue
        if depth or ":" not in line:
            continue

        key, value = line.split(":", 1)
        name, _, params = key.partition(";")
        if name == "UID":
            current["uid"] = value.strip()
        elif name == "SUMMARY":
            current["summary"] = unescape_text(value).strip()
        elif name == "DESCRIPTION":
            current["description"] = unescape_text(value).strip()
        elif name in ("DTSTART", "DTEND"):
            current[name.lower()] = parse_datetime(params, value.strip(), default_tz)
    return events


def upcoming_assignments(events: list[dict], now: datetime) -> list[dict]:
    """Future "Assignment due" events, soonest first, with a clean title.

    myCourseVille starts each event one hour before the deadline and ends it
    at the deadline, so DTEND is the real due time.
    """
    result = []
    for event in events:
        summary = event.get("summary", "")
        if not summary.startswith(ASSIGNMENT_PREFIX) or "uid" not in event:
            continue
        due = event.get("dtend") or event.get("dtstart")
        if due is None or due < now:
            continue
        result.append({
            "uid": event["uid"],
            "title": summary[len(ASSIGNMENT_PREFIX):].strip(),
            "due": due,
            "notes": event.get("description", ""),
        })
    result.sort(key=lambda a: a["due"])
    return result


# --- Side effects -----------------------------------------------------------

def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def save_state(added: set[str]) -> None:
    STATE_PATH.write_text(json.dumps({"added": sorted(added)}, indent=2) + "\n")


def fetch_feed(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "courseville-todo"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def add_reminder(list_name: str, assignment: dict) -> None:
    due = assignment["due"].astimezone()  # Reminders wants the Mac's local time
    subprocess.run(
        ["osascript", "-", list_name, assignment["title"], assignment["notes"],
         str(due.year), str(due.month), str(due.day), str(due.hour), str(due.minute)],
        input=ADD_REMINDER_SCRIPT, text=True, check=True, capture_output=True,
    )


def log(message: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    config = load_json(CONFIG_PATH, None)
    if not config or not config.get("ical_url"):
        log(f"Missing {CONFIG_PATH.name}; copy config.example.json and add your iCal URL.")
        return 1
    list_name = config.get("list_name", "CourseVille")

    events = parse_events(fetch_feed(config["ical_url"]))
    now = datetime.now(timezone.utc)
    added = set(load_json(STATE_PATH, {"added": []})["added"])
    new = [a for a in upcoming_assignments(events, now) if a["uid"] not in added]

    for assignment in new:
        label = f"{assignment['title']} (due {assignment['due'].astimezone():%a %d %b %H:%M})"
        if dry_run:
            log(f"Would add: {label}")
            continue
        try:
            add_reminder(list_name, assignment)
        except subprocess.CalledProcessError as error:
            log(f"Failed to add {label}: {error.stderr.strip()}")
            return 1
        added.add(assignment["uid"])
        save_state(added)  # save after each one so a later failure never duplicates
        log(f"Added: {label}")

    log(f"Done. {len(events)} events in feed, {len(new)} new assignment(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
