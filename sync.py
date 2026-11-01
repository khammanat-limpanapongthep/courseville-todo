#!/usr/bin/python3
"""Copy upcoming myCourseVille assignments into Apple Reminders.

Downloads the myCourseVille iCal feed, picks the "Assignment due" events
that are still in the future, and adds each one as a reminder due at the
real deadline. Each added event is remembered in state.json together with
its reminder, which means:

- a reminder you complete or delete is never re-created;
- if the teacher moves the deadline or renames the assignment, the reminder
  is updated to match (unless you already completed or deleted it).

Usage:
    /usr/bin/python3 sync.py            # add / update reminders
    /usr/bin/python3 sync.py --dry-run  # only print what would change
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# Outside ~/Documents on purpose: macOS blocks background (launchd) jobs from
# reading Documents, so install.sh copies this script here and runs it from here.
DATA_DIR = Path.home() / "Library" / "Application Support" / "courseville-todo"
CONFIG_PATH = DATA_DIR / "config.json"
STATE_PATH = DATA_DIR / "state.json"

ASSIGNMENT_PREFIX = "Assignment due:"
# The description ends with e.g. "This is an assignment from 2190443.i (2026/1)."
COURSE_PATTERN = re.compile(r"assignment from (.+?)\.?\s*$", re.IGNORECASE)
DEFAULT_TIMEZONE = "Asia/Bangkok"

# Arguments are passed through argv rather than spliced into the script, so
# quotes or backslashes in an assignment title cannot break the AppleScript.
#   add    <list> <title> <notes> <y> <m> <d> <h> <min>  -> prints reminder id
#   update <list> <id> <title> <notes> <y> <m> <d> <h> <min> -> prints updated|completed|missing
REMINDER_SCRIPT = """
on makeDate(argv, i)
    set d to current date
    set day of d to 1
    set year of d to (item i of argv) as integer
    set month of d to (item (i + 1) of argv) as integer
    set day of d to (item (i + 2) of argv) as integer
    set hours of d to (item (i + 3) of argv) as integer
    set minutes of d to (item (i + 4) of argv) as integer
    set seconds of d to 0
    return d
end makeDate

on run argv
    set mode to item 1 of argv
    set listName to item 2 of argv
    tell application "Reminders"
        if not (exists list listName) then make new list with properties {name:listName}
        if mode is "add" then
            set d to my makeDate(argv, 5)
            tell list listName to set r to make new reminder with properties {name:(item 3 of argv), body:(item 4 of argv), due date:d}
            return id of r
        end if
        set d to my makeDate(argv, 6)
        try
            set r to first reminder of list listName whose id is (item 3 of argv)
        on error
            return "missing"
        end try
        if completed of r then return "completed"
        set name of r to (item 4 of argv)
        set body of r to (item 5 of argv)
        set due date of r to d
        return "updated"
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


def course_of(description: str) -> str | None:
    """Course section from the description, e.g. "2184301.i (2026/1)"."""
    match = COURSE_PATTERN.search(description)
    return match.group(1) if match else None


def assignments(events: list[dict], courses: dict[str, str] | None = None) -> list[dict]:
    """All "Assignment due" events, soonest first, titled "[Course] Name".

    The feed only carries course codes, so `courses` maps a code ("2184301")
    to the name to show; unmapped codes are shown as the code itself.

    myCourseVille starts each event one hour before the deadline and ends it
    at the deadline, so DTEND is the real due time.
    """
    courses = courses or {}
    result = []
    for event in events:
        summary = event.get("summary", "")
        due = event.get("dtend") or event.get("dtstart")
        if not summary.startswith(ASSIGNMENT_PREFIX) or "uid" not in event or due is None:
            continue
        name = summary[len(ASSIGNMENT_PREFIX):].strip()
        course = course_of(event.get("description", ""))
        code = course.split(".")[0] if course else None
        result.append({
            "uid": event["uid"],
            "title": f"[{courses.get(code, code)}] {name}" if code else name,
            "due": due,
            "notes": f"Course {course}" if course else event.get("description", ""),
        })
    result.sort(key=lambda a: a["due"])
    return result


def plan(feed: list[dict], state: dict, now: datetime) -> tuple[list[dict], list[dict]]:
    """Split feed assignments into (to_add, to_update).

    New assignments are added only if still upcoming. Known ones are updated
    when their deadline, title or notes differ from what was last synced,
    whether or not they are still upcoming.
    """
    to_add, to_update = [], []
    for a in feed:
        known = state.get(a["uid"])
        if known is None:
            if a["due"] >= now:
                to_add.append(a)
        elif (known["due"], known["title"], known.get("notes")) != (
            a["due"].isoformat(), a["title"], a["notes"]
        ):
            to_update.append(a)
    return to_add, to_update


# --- Side effects -----------------------------------------------------------

def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps({"assignments": state}, indent=2, sort_keys=True) + "\n")


def fetch_feed(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "courseville-todo"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def run_reminder_script(*args: str) -> str:
    result = subprocess.run(
        ["osascript", "-", *args],
        input=REMINDER_SCRIPT, text=True, check=True, capture_output=True,
    )
    return result.stdout.strip()


def due_parts(due: datetime) -> list[str]:
    local = due.astimezone()  # Reminders wants the Mac's local time
    return [str(local.year), str(local.month), str(local.day), str(local.hour), str(local.minute)]


def add_reminder(list_name: str, a: dict) -> str:
    return run_reminder_script("add", list_name, a["title"], a["notes"], *due_parts(a["due"]))


def update_reminder(list_name: str, reminder_id: str, a: dict) -> str:
    return run_reminder_script(
        "update", list_name, reminder_id, a["title"], a["notes"], *due_parts(a["due"])
    )


def remember(state: dict, a: dict, reminder_id: str) -> None:
    state[a["uid"]] = {
        "reminder_id": reminder_id,
        "title": a["title"],
        "due": a["due"].isoformat(),
        "notes": a["notes"],
    }
    save_state(state)  # save after each change so a later failure never duplicates


def label(a: dict) -> str:
    return f"{a['title']} (due {a['due'].astimezone():%a %d %b %H:%M})"


def log(message: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    config = load_json(CONFIG_PATH, None)
    if not config or not config.get("ical_url"):
        log(f"Missing {CONFIG_PATH}; copy config.example.json there and add your iCal URL.")
        return 1
    list_name = config.get("list_name", "TODO")

    feed = assignments(parse_events(fetch_feed(config["ical_url"])), config.get("courses"))
    state = load_json(STATE_PATH, {"assignments": {}})["assignments"]
    to_add, to_update = plan(feed, state, datetime.now(timezone.utc))

    try:
        for a in to_add:
            if dry_run:
                log(f"Would add: {label(a)}")
                continue
            remember(state, a, add_reminder(list_name, a))
            log(f"Added: {label(a)}")

        for a in to_update:
            if dry_run:
                log(f"Would update: {label(a)}")
                continue
            reminder_id = state[a["uid"]]["reminder_id"]
            outcome = update_reminder(list_name, reminder_id, a)
            # Remember the new version either way, so a completed or deleted
            # reminder is not retried every hour.
            remember(state, a, reminder_id)
            log(f"{outcome.capitalize()}: {label(a)}" if outcome == "updated"
                else f"Skipped ({outcome} in Reminders): {label(a)}")
    except subprocess.CalledProcessError as error:
        log(f"Reminders error: {error.stderr.strip()}")
        return 1

    log(f"Done. {len(feed)} assignments in feed, {len(to_add)} new, {len(to_update)} changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
