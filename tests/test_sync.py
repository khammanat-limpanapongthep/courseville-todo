import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sync import assignments, parse_events, plan, unfold  # noqa: E402

BKK = ZoneInfo("Asia/Bangkok")

FEED = """BEGIN:VCALENDAR\r
X-WR-TIMEZONE:Asia/Bangkok\r
BEGIN:VEVENT\r
SUMMARY:Assignment due: Report #8 CSS &amp; HTML\r
DTSTART:20261105T225900\r
DTEND:20261105T235900\r
UID:a-1@mycourseville.com\r
DESCRIPTION:One hour before the due time of Report #8. This is an assig\r
 nment from 2182212.i.01 (2025/1).\r
BEGIN:VALARM\r
TRIGGER:-P1D\r
DESCRIPTION:alarm text that must not overwrite the event\r
END:VALARM\r
END:VEVENT\r
BEGIN:VEVENT\r
SUMMARY:Online Meeting: Lecture\r
DTSTART:20261106T090000\r
DTEND:20261106T120000\r
UID:m-1@mycourseville.com\r
END:VEVENT\r
BEGIN:VEVENT\r
SUMMARY:Assignment due: Old HW\r
DTSTART:20251001T225900\r
DTEND:20251001T235900\r
UID:a-0@mycourseville.com\r
END:VEVENT\r
BEGIN:VEVENT\r
SUMMARY:Assignment due: HW10\r
DTSTART:20261103T110000\r
DTEND:20261103T120000\r
UID:a-2@mycourseville.com\r
END:VEVENT\r
END:VCALENDAR\r
"""

NOW = datetime(2026, 10, 31, 23, 0, tzinfo=BKK)


class ParseTests(unittest.TestCase):
    def test_unfold_joins_continuation_lines(self):
        self.assertEqual(unfold("A:one\r\n two\r\nB:x"), ["A:onetwo", "B:x"])

    def test_parses_fields_and_ignores_alarm_fields(self):
        event = parse_events(FEED)[0]
        self.assertEqual(event["uid"], "a-1@mycourseville.com")
        self.assertEqual(event["summary"], "Assignment due: Report #8 CSS & HTML")
        self.assertIn("assignment from 2182212.i.01", event["description"])
        self.assertEqual(event["dtend"], datetime(2026, 11, 5, 23, 59, tzinfo=BKK))

    def test_utc_times(self):
        feed = "BEGIN:VEVENT\nUID:x\nDTEND:20261105T120000Z\nEND:VEVENT\n"
        self.assertEqual(
            parse_events(feed)[0]["dtend"],
            datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc),
        )


class SelectionTests(unittest.TestCase):
    def test_assignments_only_soonest_first_due_at_end_time(self):
        result = assignments(parse_events(FEED))
        self.assertEqual(
            [a["title"] for a in result], ["Old HW", "HW10", "[2182212] Report #8 CSS & HTML"]
        )
        self.assertEqual(result[1]["due"], datetime(2026, 11, 3, 12, 0, tzinfo=BKK))

    def test_notes_start_with_the_real_deadline(self):
        hw10 = assignments(parse_events(FEED))[1]
        local = datetime(2026, 11, 3, 12, 0, tzinfo=BKK).astimezone()  # notes use the Mac's timezone
        self.assertEqual(hw10["notes"].splitlines()[0], f"Deadline: {local:%a %d %b %H:%M}")

    def test_notes_show_only_the_course(self):
        result = assignments(parse_events(FEED))
        self.assertEqual(result[2]["notes"].splitlines()[1], "Course 2182212.i.01 (2025/1)")
        self.assertEqual(result[0]["notes"].splitlines()[1:], [])  # no description in the feed

    def test_alert_is_hours_before_deadline(self):
        hw10 = assignments(parse_events(FEED))[1]
        self.assertEqual(hw10["alert"], datetime(2026, 11, 3, 9, 0, tzinfo=BKK))
        hw10 = assignments(parse_events(FEED), remind_hours_before=24)[1]
        self.assertEqual(hw10["alert"], datetime(2026, 11, 2, 12, 0, tzinfo=BKK))

    def test_title_uses_course_name_when_mapped(self):
        result = assignments(parse_events(FEED), {"2182212": "Web Programming"})
        self.assertEqual(result[2]["title"], "[Web Programming] Report #8 CSS & HTML")

    def test_new_course_name_renames_known_reminder(self):
        state = {a["uid"]: {"reminder_id": "r", "title": a["title"], "due": a["due"].isoformat(),
                            "alert": a["alert"].isoformat(), "notes": a["notes"]}
                 for a in assignments(parse_events(FEED))}
        renamed = assignments(parse_events(FEED), {"2182212": "Web Programming"})
        self.assertEqual([a["title"] for a in plan(renamed, state, NOW)[1]],
                         ["[Web Programming] Report #8 CSS & HTML"])


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.feed = assignments(parse_events(FEED))
        self.by_uid = {a["uid"]: a for a in self.feed}

    def synced(self, uid, **overrides):
        a = self.by_uid[uid]
        entry = {"reminder_id": "r-" + uid, "title": a["title"], "due": a["due"].isoformat(),
                 "alert": a["alert"].isoformat(), "notes": a["notes"]}
        entry.update(overrides)
        return entry

    def test_first_run_adds_only_upcoming(self):
        to_add, to_update = plan(self.feed, {}, NOW)
        self.assertEqual([a["title"] for a in to_add], ["HW10", "[2182212] Report #8 CSS & HTML"])
        self.assertEqual(to_update, [])

    def test_nothing_to_do_when_in_sync(self):
        state = {uid: self.synced(uid) for uid in self.by_uid}
        self.assertEqual(plan(self.feed, state, NOW), ([], []))

    def test_moved_deadline_is_updated(self):
        state = {uid: self.synced(uid) for uid in self.by_uid}
        state["a-2@mycourseville.com"]["due"] = "2026-11-01T12:00:00+07:00"
        to_add, to_update = plan(self.feed, state, NOW)
        self.assertEqual(to_add, [])
        self.assertEqual([a["title"] for a in to_update], ["HW10"])

    def test_changed_alert_setting_is_updated(self):
        state = {uid: self.synced(uid) for uid in self.by_uid}
        feed = assignments(parse_events(FEED), remind_hours_before=1)
        self.assertEqual(len(plan(feed, state, NOW)[1]), 3)

    def test_renamed_assignment_is_updated(self):
        state = {uid: self.synced(uid) for uid in self.by_uid}
        state["a-1@mycourseville.com"]["title"] = "Report 8"
        self.assertEqual([a["uid"] for a in plan(self.feed, state, NOW)[1]],
                         ["a-1@mycourseville.com"])

    def test_past_assignment_extended_into_future_is_added(self):
        feed = [dict(a) for a in self.feed]
        feed[0]["due"] = datetime(2026, 11, 20, 23, 59, tzinfo=BKK)
        self.assertIn("Old HW", [a["title"] for a in plan(feed, {}, NOW)[0]])


if __name__ == "__main__":
    unittest.main()
