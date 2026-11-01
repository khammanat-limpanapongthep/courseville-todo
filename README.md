# courseville-todo

Copies myCourseVille assignments into Apple Reminders as to-dos, and keeps them
in step when a deadline moves.

An hourly background job (launchd) downloads the myCourseVille iCal feed and adds
each future "Assignment due" event to a Reminders list (default `TODO`) as
`[Course] Assignment`, due at the real deadline, with the course code in the
notes. Reminders syncs
them to iPhone through iCloud.

- Only future assignments are added; meetings and classes are ignored.
- Each added assignment is remembered with its reminder in `state.json`, so:
  - completed or deleted reminders never come back and nothing is duplicated;
  - a moved deadline or renamed assignment updates its reminder (unless you
    already completed or deleted it).
- Runs only while the Mac is awake; it catches up on the next run after waking.

## Files

macOS blocks launchd jobs from reading `~/Documents`, so the job runs from
`~/Library/Application Support/courseville-todo/`:

| File | What |
|---|---|
| `sync.py` | copy of the script, refreshed by `./install.sh` |
| `config.json` | your private iCal URL (never committed), list name, and `courses`: course code to the name shown in `[...]` |
| `state.json` | which assignments were added, and as which reminder |
| `logs/sync.log` | output of every run |

## Setup

1. Copy `config.example.json` to
   `~/Library/Application Support/courseville-todo/config.json` and paste your
   iCal URL (myCourseVille > Calendar > iCal link).
2. `/usr/bin/python3 sync.py --dry-run` to preview.
3. `/usr/bin/python3 sync.py` once by hand and click **Allow** when macOS asks
   for Reminders access.
4. `./install.sh` to run it every hour. Rerun it after editing `sync.py`.
   `./uninstall.sh` removes the job (reminders are kept).

The feed only carries course codes, so names come from `courses` in
`config.json`. Unmapped codes show as the code, e.g. `[2184301] HW10`; adding
a name renames existing reminders on the next run.

Tests: `/usr/bin/python3 -m unittest discover tests`.
