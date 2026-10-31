# courseville-todo

Copies upcoming myCourseVille assignments into Apple Reminders as to-dos.

An hourly background job (launchd) downloads the myCourseVille iCal feed and adds
each future "Assignment due" event to a Reminders list (default `CourseVille`),
due at the real deadline. Reminders syncs them to iPhone through iCloud.

- Only future assignments are added; meetings and classes are ignored.
- Added event UIDs are kept in `state.json`, so completed or deleted reminders
  never come back and nothing is duplicated.
- Changes to an assignment after it was added (new deadline, renamed) are not
  synced.
- Runs only while the Mac is awake; it catches up on the next run.

## Setup

1. `cp config.example.json config.json` and paste your iCal URL
   (myCourseVille > Calendar > export / iCal link). `config.json` is gitignored.
2. `/usr/bin/python3 sync.py --dry-run` to preview.
3. `/usr/bin/python3 sync.py` once by hand and click **Allow** when macOS asks
   for Reminders access.
4. `./install.sh` to run it every hour. `./uninstall.sh` removes the job.

Log: `logs/sync.log`. Tests: `/usr/bin/python3 -m unittest discover tests`.
