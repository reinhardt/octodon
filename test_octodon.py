import os
import unittest
from datetime import date
from datetime import datetime
from octodon import Tracking
from octodon import clean_up_bookings
from octodon import format_spent_time
from octodon import read_from_file
from octodon import write_to_file
from pyactiveresource.connection import ResourceNotFound

CACHEFILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'octodon-projects.test.pickle')


class MockHarvest(object):

    def __init__(self):
        self.entries = []

    def get_day(self):
        return {
            u'day_entries': [],
            u'for_day': u'2012-01-01',
            u'projects': [
                {u'billable': True,
                 u'client': u'Cynaptic AG',
                 u'client_currency': u'Euro - EUR',
                 u'client_currency_symbol': u'\u20ac',
                 u'client_id': 3317082,
                 u'code': u'cynaptic_3000',
                 u'id': 7585112,
                 u'name': u'Cynaptic 3000',
                 u'tasks': [
                     {u'billable': False,
                      u'id': 3982276,
                      u'name': u'Admin/Orga'},
                     {u'billable': True,
                      u'id': 3982288,
                      u'name': u'Development'},
                 ]},
                {u'billable': True,
                 u'client': u'RRZZAA',
                 u'client_currency': u'Euro - EUR',
                 u'client_currency_symbol': u'\u20ac',
                 u'client_id': 3317083,
                 u'code': u'rrzzaa',
                 u'id': 7585113,
                 u'name': u'RRZZAA',
                 u'tasks': [
                     {u'billable': False,
                      u'id': 3982276,
                      u'name': u'Admin/Orga'},
                     {u'billable': True,
                      u'id': 3982288,
                      u'name': u'Development'},
                 ]},
            ],
        }

    def add(self, entry):
        self.entries.append(entry)


class MockIssue(object):
    @staticmethod
    def get(issue):
        issues = {
            '12345': {
                'project': MockRedmine.Projects['22'],
                'tracker': {'id': '3', 'name': 'Support'},
                'subject': u'Create user list',
                'custom_fields': {},
            },
            '12346': {
                'project': MockRedmine.Projects['23'],
                'tracker': {'id': '2', 'name': 'Feature'},
                'subject': u'External API improvement',
                'custom_fields': {},
            },
            '12347': {
                'project': {'id': '24', 'name': 'Frolick'},
                'tracker': {'id': '1', 'name': 'Support'},
                'subject': u'Strategy Meeting',
                'custom_fields': {},
            },
        }
        if issue not in issues:
            raise ResourceNotFound()
        return issues[issue]


class MockRedmine(object):
    Issue = MockIssue
    Projects = {
        '22': {'id': '22', 'name': 'Cynaptic', 'identifier': 'cynaptic_3000'},
        '23': {'id': '23', 'name': 'RRZZAA', 'identifier': 'rrzzaa'},
    }


class TestOctodon(unittest.TestCase):

    def _make_booking(self, issue_id, project='', description=''):
        booking = {
            'issue_id': issue_id,
            'spent_on': date(2012, 1, 1),
            'time': 345.,
            'description': description or u'Extended API',
            'activity': u'Development',
            'project': project,
            'comments': description or u'Extended API',
            'hours': 5.75,
            'category': 'Work',
            'tags': [],
        }
        return booking

    def test_book_harvest(self):
        harvest = MockHarvest()
        bookings = [
            {'project': u'cynaptic_3000',
             'activity': u'Development',
             'comments': u'Extended API',
             'time': 345.,
             'hours': 5.75,
             'spent_on': date(2012, 1, 1),
             'issue_id': '12345',
             },
        ]
        Tracking(
            redmine=MockRedmine(),
            harvest=harvest,
            project_history_file=CACHEFILE,
        ).book_harvest(bookings)
        self.assertEqual(len(harvest.entries), 1)
        self.assertEqual(harvest.entries[0]['task_id'], 3982288)
        self.assertEqual(harvest.entries[0]['project_id'], 7585112)

    def test_get_harvest_target(self):
        harvest = MockHarvest()
        project_mapping = {u'cynaptic_3000': 'Cynaptic 3000'}
        task_mapping = {u'meeting': u'Meeting'}
        tracking = Tracking(
            redmine=MockRedmine(),
            harvest=harvest,
            project_mapping=project_mapping,
            task_mapping=task_mapping,
            project_history_file=CACHEFILE,
        )

        #def mapping(harvest, project=None, tracker=None):
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

        project, task = tracking.get_harvest_target(self._make_booking('12345'))
        self.assertEqual(project, 'Cynaptic 3000')
        self.assertEqual(task, 'Development')
        project, task = tracking.get_harvest_target(self._make_booking('12346'))
        self.assertEqual(project, 'rrzzaa')
        self.assertEqual(task, 'Development')
        project, task = tracking.get_harvest_target(self._make_booking('12347', description=u'Strategy Meeting'))
        self.assertEqual(project, '')
        self.assertEqual(task, 'Meeting')
        project, task = tracking.get_harvest_target(self._make_booking('55555'))
        self.assertEqual(project, '')

    def test_remember_harvest_target(self):
        harvest = MockHarvest()
        bookings = [
            {'project': u'rrzzaa',
             'activity': u'Development',
             'comments': u'Fixed encoding',
             'time': 75.,
             'hours': 1.15,
             'spent_on': date(2012, 3, 4),
             'issue_id': '10763',
             },
        ]
        if os.path.exists(CACHEFILE):
            os.remove(CACHEFILE)
        tracking = Tracking(
            redmine=MockRedmine(),
            harvest=harvest,
            project_history_file=CACHEFILE,
        )
        tracking.book_harvest(bookings)

        tracking = Tracking(
            redmine=MockRedmine(),
            harvest=harvest,
            project_history_file=CACHEFILE,
        )
        project, task = tracking.get_harvest_target(
            self._make_booking('10763', description=u'Fixed encoding'))
        self.assertEqual(project, 'rrzzaa')
        os.remove(CACHEFILE)

    def test_format_spent_time(self):
        self.assertEqual(format_spent_time(300.), ' 5:00')
        self.assertEqual(format_spent_time(300.02), ' 5:01')
        self.assertEqual(format_spent_time(59.0002), ' 1:00')
        self.assertEqual(format_spent_time(59.99999), ' 1:00')
        self.assertEqual(format_spent_time(.0002), ' 0:01')
        self.assertEqual(format_spent_time(0.), ' 0:00')

    def test_file_io(self):
        bookings = [
            {'project': u'Cynaptic 3000',
             'activity': u'Development',
             'comments': u'Extended API',
             'description': u'Extended API',
             'time': 345.,
             'spent_on': date(2012, 1, 1).strftime('%Y-%m-%d'),
             'issue_id': '12345',
             },
        ]
        spent_on = datetime(2012, 1, 1)
        activities = [{'id': 1, 'name': u'Development'}]
        write_to_file(bookings, spent_on, activities, file_name='.test_octodon')
        self.assertEqual(
            read_from_file('.test_octodon', activities),
            (spent_on, bookings))

    def test_clean_up_bookings(self):
        bookings = [
            {'activity': 'Development',
             'category': u'Work',
             'comments': '',
             'description': u'book time',
             'issue_id': None,
             'project': '',
             'spent_on': date(2016, 5, 31),
             'tags': [],
             'time': 20.},
            {'activity': 'Development',
             'category': u'Work',
             'comments': '',
             'description': u'Gemeinsame Durchsuchbarkeit #13568',
             'issue_id': '13568',
             'project': u'T\xf6chter',
             'spent_on': date(2016, 5, 31),
             'tags': [],
             'time': 420.},
            {'activity': 'Development',
             'category': u'Day-to-day',
             'comments': '',
             'description': u'break',
             'issue_id': None,
             'project': '',
             'spent_on': date(2016, 5, 31),
             'tags': [],
             'time': 60.},
            {'activity': 'SCRUM Meetings',
             'category': u'Work',
             'comments': '',
             'description': u'daily scrum #13572',
             'issue_id': '13572',
             'project': u'Internals',
             'spent_on': date(2016, 5, 31),
             'tags': [],
             'time': 20.},
            {'activity': 'Development',
             'category': u'Work',
             'comments': '',
             'description': u'Suche liefert "Unzureichende Berechtigungen" #13678',
             'issue_id': '13678',
             'project': u'T\xf6chter',
             'spent_on': date(2016, 5, 31),
             'tags': [],
             'time': 85.},
        ]
        cleaned_bookings = clean_up_bookings(bookings)
        self.assertEqual(
            cleaned_bookings,
            [
                {'activity': 'Development',
                 'category': u'Work',
                 'comments': '',
                 'description': u'Gemeinsame Durchsuchbarkeit #13568',
                 'issue_id': '13568',
                 'project': u'T\xf6chter',
                 'spent_on': date(2016, 5, 31),
                 'tags': [],
                 'time': 436.},
                {'activity': 'Development',
                 'category': u'Day-to-day',
                 'comments': '',
                 'description': u'break',
                 'issue_id': None,
                 'project': '',
                 'spent_on': date(2016, 5, 31),
                 'tags': [],
                 'time': 60.},
                {'activity': 'SCRUM Meetings',
                 'category': u'Work',
                 'comments': '',
                 'description': u'daily scrum #13572',
                 'issue_id': '13572',
                 'project': u'Internals',
                 'spent_on': date(2016, 5, 31),
                 'tags': [],
                 'time': 20.761904761904762},
                {'activity': 'Development',
                 'category': u'Work',
                 'comments': '',
                 'description': u'Suche liefert "Unzureichende Berechtigungen" #13678',
                 'issue_id': '13678',
                 'project': u'T\xf6chter',
                 'spent_on': date(2016, 5, 31),
                 'tags': [],
                 'time': 88.238095238095238},
            ])


if __name__ == '__main__':
    unittest.main()
