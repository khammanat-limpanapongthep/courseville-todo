import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sync import parse_events, unfold, upcoming_assignments  # noqa: E402

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
    def test_only_future_assignments_soonest_first_due_at_end_time(self):
        result = upcoming_assignments(parse_events(FEED), NOW)
        self.assertEqual([a["title"] for a in result], ["HW10", "Report #8 CSS & HTML"])
        self.assertEqual(result[0]["due"], datetime(2026, 11, 3, 12, 0, tzinfo=BKK))


if __name__ == "__main__":
    unittest.main()
