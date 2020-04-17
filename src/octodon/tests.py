import os
import unittest
from datetime import date
from datetime import datetime
from mock import patch
from octodon.clockwork import ClockWorkTimeLog
from octodon.exceptions import NotFound
from octodon.tracking import Tracking
from octodon.utils import clean_up_bookings
from octodon.utils import format_spent_time
from octodon.utils import read_from_file
from octodon.utils import write_to_file
from octodon.version_control import VCSLog
from pyactiveresource.connection import ResourceNotFound
from tempfile import mkdtemp
from tempfile import mkstemp

CACHEFILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "octodon-projects.test.pickle"
)


class MockHarvest(object):
    def __init__(self):
        self.entries = []

    def get_day(self):
        return {
            u"day_entries": [],
            u"for_day": u"2012-01-01",
            u"projects": [
                {
                    u"billable": True,
                    u"client": u"Cynaptic AG",
                    u"client_currency": u"Euro - EUR",
                    u"client_currency_symbol": u"\u20ac",
                    u"client_id": 3317082,
                    u"code": u"cynaptic_3000",
                    u"id": 7585112,
                    u"name": u"Cynaptic 3000",
                    u"tasks": [
                        {u"billable": False, u"id": 3982276, u"name": u"Admin/Orga"},
                        {u"billable": True, u"id": 3982288, u"name": u"Development"},
                    ],
                },
                {
                    u"billable": True,
                    u"client": u"RRZZAA",
                    u"client_currency": u"Euro - EUR",
                    u"client_currency_symbol": u"\u20ac",
                    u"client_id": 3317083,
                    u"code": u"rrzzaa",
                    u"id": 7585113,
                    u"name": u"RRZZAA",
                    u"tasks": [
                        {u"billable": False, u"id": 3982276, u"name": u"Admin/Orga"},
                        {u"billable": True, u"id": 3982288, u"name": u"Development"},
                    ],
                },
            ],
        }

    def add(self, entry):
        self.entries.append(entry)


class MockRedmine(object):
    Projects = {
        "22": {"id": "22", "name": "Cynaptic", "identifier": "cynaptic_3000"},
        "23": {"id": "23", "name": "RRZZAA", "identifier": "rrzzaa"},
    }

    def get_issue(self, issue):
        issues = {
            "12345": {
                "project": MockRedmine.Projects["22"],
                "tracker": {"id": "3", "name": "Support"},
                "subject": u"Create user list",
                "custom_fields": {},
            },
            "12346": {
                "project": MockRedmine.Projects["23"],
                "tracker": {"id": "2", "name": "Feature"},
                "subject": u"External API improvement",
                "custom_fields": {},
            },
            "12347": {
                "project": {"id": "24", "name": "Frolick"},
                "tracker": {"id": "1", "name": "Support"},
                "subject": u"Strategy Meeting",
                "custom_fields": {},
            },
        }
        if issue not in issues:
            raise NotFound()
        return issues[issue]


class TestOctodon(unittest.TestCase):
    def setUp(self):
        if os.path.exists(CACHEFILE):
            os.remove(CACHEFILE)

    def _make_booking(self, issue_id, project="", description=""):
        booking = {
            "issue_id": issue_id,
            "spent_on": date(2012, 1, 1),
            "time": 345.0,
            "description": description or u"Extended API",
            "activity": u"Development",
            "project": project,
            "comments": description or u"Extended API",
            "hours": 5.75,
            "category": "Work",
            "tags": [],
        }
        return booking

    def test_book_harvest(self):
        harvest = MockHarvest()
        bookings = [
            {
                "project": u"cynaptic_3000",
                "activity": u"Development",
                "comments": u"Extended API",
                "time": 345.0,
                "hours": 5.75,
                "spent_on": date(2012, 1, 1),
                "issue_id": "12345",
            }
        ]
        Tracking(
            redmine=MockRedmine(), harvest=harvest, project_history_file=CACHEFILE
        ).book_harvest(bookings)
        self.assertEqual(len(harvest.entries), 1)
        self.assertEqual(harvest.entries[0]["task_id"], 3982288)
        self.assertEqual(harvest.entries[0]["project_id"], 7585112)

    def test_get_harvest_target(self):
        harvest = MockHarvest()
        project_mapping = {u"cynaptic_3000": "Cynaptic 3000"}
        task_mapping = {u"meeting": u"Meeting"}
        tracking = Tracking(
            redmine=MockRedmine(),
            harvest=harvest,
            project_mapping=project_mapping,
            task_mapping=task_mapping,
            project_history_file=CACHEFILE,
            default_task="Development",
        )

        # def mapping(harvest, project=None, tracker=None):
        #    projects = harvest.get_day()['projects']
        #    projects_lookup = dict(
        #        [(proj[u'name'], proj) for proj in projects])

        #    task = tracking.harvest_task_map[tracker]

        #    harvest_project = ''
        #    if project in projects_lookup:
        #        harvest_project = project
        #    elif project == 'Cynaptic':
        #        harvest_project = 'Cynaptic 3000'
        #    return (harvest_project, task)

        project, task = tracking.get_harvest_target(self._make_booking("12345"))
        self.assertEqual(project, "Cynaptic 3000")
        self.assertEqual(task, "Development")
        project, task = tracking.get_harvest_target(self._make_booking("12346"))
        self.assertEqual(project, "rrzzaa")
        self.assertEqual(task, "Development")
        project, task = tracking.get_harvest_target(
            self._make_booking("12347", description=u"Strategy Meeting")
        )
        self.assertEqual(project, "")
        self.assertEqual(task, "Meeting")
        project, task = tracking.get_harvest_target(self._make_booking("55555"))
        self.assertEqual(project, "")

    def test_remember_harvest_target(self):
        harvest = MockHarvest()
        bookings = [
            {
                "project": u"rrzzaa",
                "activity": u"Development",
                "comments": u"Fixed encoding",
                "time": 75.0,
                "hours": 1.15,
                "spent_on": date(2012, 3, 4),
                "issue_id": "10763",
            }
        ]
        if os.path.exists(CACHEFILE):
            os.remove(CACHEFILE)
        tracking = Tracking(
            redmine=MockRedmine(), harvest=harvest, project_history_file=CACHEFILE
        )
        tracking.book_harvest(bookings)

        tracking = Tracking(
            redmine=MockRedmine(), harvest=harvest, project_history_file=CACHEFILE
        )
        project, task = tracking.get_harvest_target(
            self._make_booking("10763", description=u"Fixed encoding")
        )
        self.assertEqual(project, "rrzzaa")
        os.remove(CACHEFILE)

    def test_format_spent_time(self):
        self.assertEqual(format_spent_time(300.0), " 5:00")
        self.assertEqual(format_spent_time(300.02), " 5:01")
        self.assertEqual(format_spent_time(59.0002), " 1:00")
        self.assertEqual(format_spent_time(59.99999), " 1:00")
        self.assertEqual(format_spent_time(0.0002), " 0:01")
        self.assertEqual(format_spent_time(0.0), " 0:00")

    def test_file_io(self):
        bookings = [
            {
                "project": u"Cynaptic 3000",
                "activity": u"Development",
                "comments": u"Extended API",
                "description": u"Extended API",
                "time": 345.0,
                "spent_on": date(2012, 1, 1).strftime("%Y-%m-%d"),
                "issue_id": "12345",
            }
        ]
        spent_on = datetime(2012, 1, 1)
        activities = [{"id": 1, "name": u"Development"}]
        write_to_file(bookings, spent_on, activities, file_name=".test_octodon")
        self.assertEqual(
            read_from_file(".test_octodon", activities), (spent_on, bookings)
        )

    def test_clean_up_bookings(self):
        bookings = [
            {
                "activity": "Development",
                "category": u"Work",
                "comments": "",
                "description": u"book time",
                "issue_id": None,
                "project": "",
                "spent_on": date(2016, 5, 31),
                "tags": [],
                "time": 20.0,
            },
            {
                "activity": "Development",
                "category": u"Work",
                "comments": "",
                "description": u"Gemeinsame Durchsuchbarkeit #toechter",
                "issue_id": None,
                "project": u"T\xf6chter",
                "spent_on": date(2016, 5, 31),
                "tags": ["toechter"],
                "time": 420.0,
            },
            {
                "activity": "Development",
                "category": u"Day-to-day",
                "comments": "",
                "description": u"break",
                "issue_id": None,
                "project": "",
                "spent_on": date(2016, 5, 31),
                "tags": [],
                "time": 60.0,
            },
            {
                "activity": "SCRUM Meetings",
                "category": u"Work",
                "comments": "",
                "description": u"daily scrum #13572",
                "issue_id": "13572",
                "project": u"Internals",
                "spent_on": date(2016, 5, 31),
                "tags": [],
                "time": 20.0,
            },
            {
                "activity": "Development",
                "category": u"Work",
                "comments": "",
                "description": u'Suche liefert "Unzureichende Berechtigungen" #13678',
                "issue_id": "13678",
                "project": u"T\xf6chter",
                "spent_on": date(2016, 5, 31),
                "tags": [],
                "time": 85.0,
            },
        ]
        cleaned_bookings = clean_up_bookings(bookings)
        self.maxDiff = None
        self.assertEqual(
            cleaned_bookings,
            [
                {
                    "activity": "Development",
                    "category": u"Work",
                    "comments": "",
                    "description": u"Gemeinsame Durchsuchbarkeit #toechter",
                    "issue_id": None,
                    "project": u"T\xf6chter",
                    "spent_on": date(2016, 5, 31),
                    "tags": ["toechter"],
                    "time": 436.0,
                },
                {
                    "activity": "Development",
                    "category": u"Day-to-day",
                    "comments": "",
                    "description": u"break",
                    "issue_id": None,
                    "project": "",
                    "spent_on": date(2016, 5, 31),
                    "tags": [],
                    "time": 60.0,
                },
                {
                    "activity": "SCRUM Meetings",
                    "category": u"Work",
                    "comments": "",
                    "description": u"daily scrum #13572",
                    "issue_id": "13572",
                    "project": u"Internals",
                    "spent_on": date(2016, 5, 31),
                    "tags": [],
                    "time": 20.761904761904762,
                },
                {
                    "activity": "Development",
                    "category": u"Work",
                    "comments": "",
                    "description": u'Suche liefert "Unzureichende Berechtigungen" #13678',
                    "issue_id": "13678",
                    "project": u"T\xf6chter",
                    "spent_on": date(2016, 5, 31),
                    "tags": [],
                    "time": 88.238095238095238,
                },
            ],
        )


class TestVCSLog(unittest.TestCase):
    def test_one_ticket(self):
        vcslog = VCSLog()
        log = """
commit 4aa68f1777a82605e8bd7acdb28342bfa23daea9
Author: Manuel Reinhardt <reinhardt@syslab.com>
Date:   Thu Apr 15 15:58:22 2020 +0200
 Fix permissions

commit d5031fdb0025ce79d8336c20df4be960417cdc2f
Author: Manuel Reinhardt <reinhardt@syslab.com>
Date:   Thu Apr 15 16:14:48 2020 +0200
 Extended creation script. Refs DMY-312
        """
        self.assertEqual(
            vcslog.extract_loginfo(log), {"DMY-312": ["Extended creation script"]}
        )

    @unittest.skip("Implement me!")
    def test_two_tickets(self):
        vcslog = VCSLog()
        log = """
commit 4aa68f1777a82605e8bd7acdb28342bfa23daea9
Author: Manuel Reinhardt <reinhardt@syslab.com>
Date:   Thu Apr 15 15:58:22 2020 +0200
 Fix permissions

commit d5031fdb0025ce79d8336c20df4be960417cdc2f
Author: Manuel Reinhardt <reinhardt@syslab.com>
Date:   Thu Apr 15 16:14:48 2020 +0200
 Extended creation script. Refs DMY-312 DMY-314
        """
        self.assertEqual(
            vcslog.extract_loginfo(log),
            {
                "DMY-312": ["Extended creation script"],
                "DMY-314": ["Extended creation script"],
            },
        )


class TestClockWork(unittest.TestCase):
    def test_single_entry(self):
        clockwork = ClockWorkTimeLog()
        timesheet = """0614 Improve usability CGUI-417
0700
"""
        self.assertEqual(
            clockwork.get_facts(timesheet),
            [
                {
                    "description": "Improve usability CGUI-417",
                    "issue_id": "CGUI-417",
                    "spent_on": None,
                    "time": 46.0,
                }
            ],
        )

    def test_single_entry_with_date(self):
        clockwork = ClockWorkTimeLog()
        timesheet = """2019-11-14:
0614 Improve usability CGUI-417
0700
"""
        self.assertEqual(
            clockwork.get_facts(timesheet),
            [
                {
                    "description": "Improve usability CGUI-417",
                    "issue_id": "CGUI-417",
                    "spent_on": datetime(2019, 11, 14),
                    "time": 46.0,
                }
            ],
        )

    def test_break_between_entries(self):
        clockwork = ClockWorkTimeLog()
        timesheet = """2019-11-14:
0614 Improve usability CGUI-417
0700
0714 Improve usability CGUI-417
0820
"""
        self.assertEqual(
            clockwork.get_facts(timesheet),
            [
                {
                    "description": "Improve usability CGUI-417",
                    "issue_id": "CGUI-417",
                    "spent_on": datetime(2019, 11, 14),
                    "time": 46.0,
                },
                {
                    "description": "Improve usability CGUI-417",
                    "issue_id": "CGUI-417",
                    "spent_on": datetime(2019, 11, 14),
                    "time": 66.0,
                },
            ],
        )

    def test_currently_running_task(self):
        clockwork = ClockWorkTimeLog()
        timesheet = """2019-11-14:
0735 Improve usability CGUI-417
0815 Manual tests CGUI-422
"""

        with patch("octodon.clockwork.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2019, 11, 14, 9, 0)
            mock_datetime.strptime.side_effect = lambda *args, **kw: datetime.strptime(
                *args, **kw
            )
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

            facts = clockwork.get_facts(timesheet)

        self.assertEqual(
            facts,
            [
                {
                    "description": "Improve usability CGUI-417",
                    "issue_id": "CGUI-417",
                    "spent_on": datetime(2019, 11, 14),
                    "time": 40.0,
                },
                {
                    "description": "Manual tests CGUI-422",
                    "issue_id": "CGUI-422",
                    "spent_on": datetime(2019, 11, 14),
                    "time": 45.0,
                },
            ],
        )

    def test_currently_running_task_next_day_reverse_order(self):
        clockwork = ClockWorkTimeLog()
        timesheet = """2019-11-14:
0815 Manual tests CGUI-422

2019-11-13:
0735 Improve usability CGUI-417
1735
"""

        with patch("octodon.clockwork.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2019, 11, 14, 9, 0)
            mock_datetime.strptime.side_effect = lambda *args, **kw: datetime.strptime(
                *args, **kw
            )
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

            facts = clockwork.get_facts(timesheet)

        self.assertEqual(
            facts,
            [
                {
                    "description": "Manual tests CGUI-422",
                    "issue_id": "CGUI-422",
                    "spent_on": datetime(2019, 11, 14),
                    "time": 45.0,
                },
                {
                    "description": "Improve usability CGUI-417",
                    "issue_id": "CGUI-417",
                    "spent_on": datetime(2019, 11, 13),
                    "time": 600.0,
                },
            ],
        )

    def test_unterminated_task(self):
        clockwork = ClockWorkTimeLog()
        timesheet = """2019-11-13:
0815 Manual tests CGUI-422

2019-11-14:
0715 Improve usability CGUI-417
0915
"""

        with patch("octodon.clockwork.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2019, 11, 14, 9, 40)
            mock_datetime.strptime.side_effect = lambda *args, **kw: datetime.strptime(
                *args, **kw
            )
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

            facts = clockwork.get_facts(timesheet)

        self.assertEqual(
            facts,
            [
                {
                    "description": "Manual tests CGUI-422",
                    "issue_id": "CGUI-422",
                    "spent_on": datetime(2019, 11, 13),
                    "time": 15.0 * 60.0 + 45.0,
                },
                {
                    "description": "Improve usability CGUI-417",
                    "issue_id": "CGUI-417",
                    "spent_on": datetime(2019, 11, 14),
                    "time": 120.0,
                },
            ],
        )

    def test_unterminated_task_reverse_order(self):
        clockwork = ClockWorkTimeLog()
        timesheet = """2019-11-14:
0715 Improve usability CGUI-417
0915

2019-11-13:
0815 Manual tests CGUI-422
"""

        with patch("octodon.clockwork.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2019, 11, 14, 9, 40)
            mock_datetime.strptime.side_effect = lambda *args, **kw: datetime.strptime(
                *args, **kw
            )
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

            facts = clockwork.get_facts(timesheet)

        self.assertEqual(
            facts,
            [
                {
                    "description": "Improve usability CGUI-417",
                    "issue_id": "CGUI-417",
                    "spent_on": datetime(2019, 11, 14),
                    "time": 120.0,
                },
                {
                    "description": "Manual tests CGUI-422",
                    "issue_id": "CGUI-422",
                    "spent_on": datetime(2019, 11, 13),
                    "time": 15.0 * 60.0 + 45.0,
                },
            ],
        )

    def test_get_raw_log_single_file(self):
        tmp_fd, tmp_path = mkstemp(suffix=".tmp")
        tmp_file = os.fdopen(tmp_fd, "w")
        log_data = """2019-11-15:
0850 Framework Meeting PLN-159
0930
"""
        tmp_file.write(log_data)
        tmp_file.close()
        clockwork = ClockWorkTimeLog(log_path=tmp_path)
        self.assertEqual("".join(clockwork.get_raw_log()), log_data)

    def test_get_raw_log_directory(self):
        tmp_path = mkdtemp()
        tmp_file_1 = open(os.path.join(tmp_path, "log1.txt"), "w")
        tmp_file_2 = open(os.path.join(tmp_path, "log2.txt"), "w")
        log_data_1 = """2019-11-15:
0850 Framework Meeting PLN-159
0930
"""
        log_data_2 = """2019-11-16:
0800 Fix login
0845
"""
        tmp_file_1.write(log_data_1)
        tmp_file_2.write(log_data_2)
        tmp_file_1.close()
        tmp_file_2.close()
        clockwork = ClockWorkTimeLog(log_path=tmp_path)
        raw_log = "".join(clockwork.get_raw_log())
        if raw_log.startswith(log_data_1):
            self.assertEqual(raw_log, "".join((log_data_1, log_data_2)))
        else:
            self.assertEqual(raw_log, "".join((log_data_2, log_data_1)))

    def test_get_raw_log_glob(self):
        tmp_path = mkdtemp()
        tmp_file_1 = open(os.path.join(tmp_path, "log1.txt"), "w")
        tmp_file_2 = open(os.path.join(tmp_path, "log2.org"), "w")
        log_data_1 = """2019-11-15:
0850 Framework Meeting PLN-159
0930
"""
        log_data_2 = """2019-11-16:
0800 Fix login
0845
"""
        tmp_file_1.write(log_data_1)
        tmp_file_2.write(log_data_2)
        tmp_file_1.close()
        tmp_file_2.close()
        clockwork = ClockWorkTimeLog(log_path="{}/*.txt".format(tmp_path))
        raw_log = "".join(clockwork.get_raw_log())
        self.assertEqual(raw_log, log_data_1)

    def test_get_timeinfo(self):
        facts = [
            {
                "description": "Improve usability CGUI-417 #cgui-support",
                "issue_id": "CGUI-417",
                "spent_on": datetime(2019, 11, 14),
                "time": 32.0,
            },
            {
                "description": "Improve usability CGUI-417 #cgui-support",
                "issue_id": "CGUI-417",
                "spent_on": datetime(2019, 11, 15),
                "time": 45.0,
            },
            {
                "description": "Improve usability CGUI-417 #cgui-support",
                "issue_id": "CGUI-417",
                "spent_on": datetime(2019, 11, 15),
                "time": 23.0,
            },
        ]

        def mock_get_facts(timesheet):
            return facts

        def mock_get_raw_log():
            return ""

        clockwork = ClockWorkTimeLog()
        clockwork.get_facts = mock_get_facts
        clockwork.get_raw_log = mock_get_raw_log
        self.assertEqual(
            clockwork.get_timeinfo(datetime(2019, 11, 15)),
            [
                {
                    "description": "Improve usability CGUI-417 #cgui-support",
                    "issue_id": "CGUI-417",
                    "spent_on": datetime(2019, 11, 15),
                    "time": 68.0,
                    "activity": "none",
                    "comments": "",
                    "category": "Work",
                    "tags": ["cgui-support"],
                    "project": "",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
