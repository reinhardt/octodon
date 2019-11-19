#!/usr/bin/env python
from cmd import Cmd
from datetime import datetime, timedelta
from ConfigParser import SafeConfigParser
import argparse
import subprocess
from tempfile import NamedTemporaryFile
import re
import sys
import os
import pickle
import socket
import math
from glob import glob
from jira import JIRA
from jira import JIRAError
from pyactiveresource.activeresource import ActiveResource
from pyactiveresource.connection import ResourceNotFound
from pyactiveresource import connection

ticket_pattern = re.compile('#([A-Z0-9-]+)')
ticket_pattern_redmine = re.compile('#?([0-9]+)')
ticket_pattern_jira = re.compile('#?([A-Z0-9]+-[0-9]+)')
ref_pattern = re.compile('(?:    )?(.*)#([A-Z0-9-]+)')
ref_keyword_pattern = re.compile('([Rr]efs |[Ff]ixes )$')


def get_default_activity(activities):
    default_activity = [act for act in activities
                        if act.get('is_default', False)]
    fallback = {'id': None}
    return default_activity and default_activity[0] or fallback


def get_ticket_no(strings):
    tickets = [ticket_pattern.search(s).group(1) for s in strings
               if ticket_pattern.search(s)]
    return len(tickets) and tickets[0] or None


class HamsterTimeLog(object):
    def get_timeinfo(self, date=datetime.now(), loginfo={}, activities=[]):
        default_activity = get_default_activity(activities)
        from hamster.client import Storage
        sto = Storage()
        facts = sto.get_facts(date)
        bookings = []
        for fact in facts:
            #delta = (fact.end_time or datetime.now()) - fact.start_time
            #hours = round(fact.delta.seconds / 3600. * 4 + .25) / 4.
            minutes = fact.delta.seconds / 60.
            #hours = minutes / 60.
            existing = filter(lambda b: b['description'] == fact.activity
                              and b['spent_on'] == fact.date, bookings)
            if existing:
                existing[0]['time'] += minutes
                continue
            ticket = get_ticket_no(
                ['#' + tag for tag in fact.tags] + [fact.activity] +
                [fact.description or ''])
            bookings.append({'issue_id': ticket,
                             'spent_on': fact.date,
                             'time': minutes,
                             'description': fact.activity,
                             'activity': default_activity.get('name', 'none'),
                             'comments': '. '.join(loginfo.get(ticket, [])),
                             'category': fact.category,
                             'tags': fact.tags,
                             'project': ''})
        return bookings


class OrgModeTimeLog(object):
    def __init__(self, filename):
        self.filename = filename

    def get_timeinfo(self, date=datetime.now(), loginfo={}, activities=[]):
        _, bookings = read_from_file(self.filename, activities)
        for booking in bookings:
            ticket = get_ticket_no([booking['description']])
            booking['issue_id'] = ticket
            booking['comments'] = '; '.join(loginfo.get(ticket, []))
            booking['project'] = ''
        return bookings


class ClockWorkTimeLog(object):
    date_pattern = re.compile("^([0-9]{4})-([0-9]{2})-([0-9]{2}):?")
    time_pattern = re.compile("^([0-9]{2}:?[0-9]{2}) ?(.*)")

    def __init__(self, log_path='time_log.txt'):
        self.log_path = log_path

    def get_timeinfo(self, date=datetime.now(), loginfo={}, activities=[]):
        timesheet = self.get_raw_log()
        bookings = []
        for fact in self.get_facts(timesheet):
            existing = filter(
                lambda b: (b['description'] == fact["description"]
                           and b['spent_on'] == fact["spent_on"]),
                bookings,
            )
            if existing:
                existing[0]['time'] += fact["time"]
                continue

            if fact["spent_on"] == date:
                fact.update(
                    {
                        "activity": "none",
                        "comments": "",
                        "category": "Work",
                        "tags": [],
                        "project": "",
                    }
                )
                bookings.append(fact)
        return bookings

    def get_raw_log(self, log_path=None):
        if log_path is None:
            log_path = self.log_path
        if os.path.isfile(log_path):
            log_file = open(log_path, 'r')
            for line in log_file:
                yield line
            log_file.close()
        elif os.path.isdir(log_path):
            for file_path in os.listdir(log_path):
                log_file = open(os.path.join(log_path, file_path), 'r')
                for line in log_file:
                    yield line
                log_file.close()
        else:
            paths = glob(self.log_path)
            for log_path in paths:
                for line in self.get_raw_log(log_path):
                    yield line

    def finalize_task(self, current_task, end_time=None):
        if end_time is None:
            # Missing task end - assuming now if current date or end of day if past date
            now = datetime.now()
            if now.date() == self.current_date.date():
                end_time = now
            else:
                end_of_day = self.current_date.replace(
                    day=self.current_date.day + 1,
                    hour=0,
                    minute=0,
                )
                end_time = end_of_day
        time_spent = end_time - current_task["clock"]
        fact = {
            "description": current_task["description"],
            "issue_id": current_task["issue_id"],
            "spent_on": self.current_date,
            "time": time_spent.seconds / 60.0,
        }
        return fact

    def get_facts(self, timesheet):
        facts = []
        current_task = None
        self.current_date = None
        if isinstance(timesheet, str):
            timesheet = timesheet.split("\n")
        for line in timesheet:
            date_match = self.date_pattern.match(line)
            time_match = self.time_pattern.match(line)
            if date_match:
                if current_task and current_task["description"]:
                    facts.append(self.finalize_task(current_task))
                    current_task = None

                self.current_date = datetime(
                    int(date_match.group(1)),
                    int(date_match.group(2)),
                    int(date_match.group(3)),
                )
            elif time_match:
                next_task = {}
                next_task["clock"] = datetime.strptime(
                    time_match.group(1).replace(":", ""), "%H%M"
                )
                next_task["description"] = time_match.group(2).strip()
                issue_match = ticket_pattern_jira.search(next_task["description"])
                next_task["issue_id"] = None
                if issue_match:
                    next_task["issue_id"] = issue_match.group(1)
                if current_task and current_task["description"]:
                    if next_task["clock"] < current_task["clock"]:
                        next_task["clock"] = next_task["clock"].replace(
                            day=next_task["clock"].day + 1
                        )
                    facts.append(
                        self.finalize_task(current_task, end_time=next_task["clock"]),
                    )
                current_task = next_task
        if current_task and current_task["description"]:
            facts.append(self.finalize_task(current_task))
        return facts


class VCSLog(object):

    def __init__(self, exe=None):
        self.exe = exe

    def extract_loginfo(self, log, mergewith={}):
        matches = ref_pattern.finditer(log) or []
        logdict = mergewith
        for match in matches:
            comment = ref_keyword_pattern.sub('', match.group(1))
            comment = comment.strip(' ,').strip(' .')
            logdict.setdefault(match.group(2), []).append(comment)
        return logdict


    def _get_loginfo(self, command, args, repos=[], mergewith={}):
        logdict = mergewith
        for repo in repos:
            if not os.path.exists(repo):
                print("Warning: Repository path not found: {0}".format(repo))
                continue
            os.chdir(repo)
            try:
                out = subprocess.check_output(' '.join(command + args), shell=True)
            except subprocess.CalledProcessError as cpe:
                print('%s returned %d: %s' % (command, cpe.returncode, cpe.output))
                continue
            log = '\n'.join([re.sub(
                '^([A-Za-z]*:\s*.*\n)*', '', entry).replace(
                    '\n    ', ' ').strip()
                for entry in re.split('^commit [a-z0-9]*\n', out)
                if entry])
            logdict = self.extract_loginfo(log, logdict)
        return logdict


    def get_loginfo(self, date=datetime.now(), author=None, repos=[], mergewith={}):
        raise NotImplemented


class SvnLog(VCSLog):

    def __init__(self, exe='/usr/bin/svn'):
        self.exe = exe

    def get_loginfo(self, date=datetime.now(), author=None, repos=[], mergewith={}):
        command = [self.exe, 'log']
        args = ['-r "{%s}:{%s}"' % (date, date + timedelta(1))]
        if author:
            args.append('--search="%s"' % author)
        return self._get_loginfo(
            command=command, args=args, repos=repos, mergewith=mergewith)


class GitLog(VCSLog):

    def __init__(self, exe='/usr/bin/git'):
        self.exe = exe

    def get_loginfo(self, date=datetime.now(), author=None, repos=[], mergewith={}):
        command = [self.exe, '--no-pager', '-c', 'color.diff=false', 'log', '--branches', '--reverse']
        args = ['--since="{%s}"' % date, '--until="{%s}"' % (date + timedelta(1))]
        if author:
            args.append('--author="%s"' % author)
        return self._get_loginfo(
            command=command, args=args, repos=repos, mergewith=mergewith)

def format_spent_time(time):
    rounded_time = math.ceil(time)
    hours = int(rounded_time / 60.)
    mins = math.ceil(rounded_time - (hours * 60.))
    #hours = round(time) / 60
    #mins = round(time) - (hours * 60)
    return '%2d:%02d' % (hours, mins)


def pad(string, length):
    return string + ' ' * (length - len(string.decode('utf-8')))


def make_row(entry, activities):
    act_name = entry['activity']
    return ['1',
            entry['description'].encode('utf-8'),
            format_spent_time(entry['time']),
            act_name.encode('utf-8'),
            entry['issue_id'] or '',
            entry['project'].encode('utf-8'),
            entry['comments'].encode('utf-8'),
            ]


def make_table(rows):
    rows = [['L', 'Headline', 'Time', 'Activity', 'iss', 'Project', 'Comments']] + rows
    columns = zip(*rows)
    max_lens = [max([len(entry.decode('utf-8')) for entry in column]) for column in columns]
    out_strs = []
    divider = '+%s+' % '+'.join(
        ['-' * (max_len + 2) for max_len in max_lens]
    )
    for row in rows:
        vals = []
        for i in range(len(row)):
            vals.append(' %s ' % pad(row[i].replace('|', ' '), max_lens[i]))
        row_str = '|%s|' % '|'.join(vals)
        out_strs.append(divider)
        out_strs.append(row_str)

    out_strs.append(divider)
    return '\n'.join(out_strs)


def get_time_sum(bookings):
    if len(bookings) == 0:
        return 0.
    return reduce(lambda x, y: x+y, map(lambda x: x['time'], bookings))


def write_to_file(bookings, spent_on, activities, file_name=None):
    if file_name is not None:
        tmpfile = open(file_name, 'w')
    else:
        tmpfile = NamedTemporaryFile(mode='w')
    summary_time = min(
        datetime.now(),
        (spent_on + timedelta(1) - timedelta(0, 1)))
    tmpfile.write('#+BEGIN: clocktable :maxlevel 2 :scope file\n')
    tmpfile.write('Clock summary at [' +
                  summary_time.strftime('%Y-%m-%d %a %H:%M') + u']\n')
    tmpfile.write('\n')

    rows = []

    sum = get_time_sum(bookings)
    rows.append([' ', '*Total time*', '*%s*' % format_spent_time(sum), ' ',
                 ' ', ' ', ' '])
    rows += [make_row(entry, activities) for entry in bookings]
    tmpfile.write(make_table(rows))

    tmpfile.write('\n')
    tmpfile.write('\n')
    tmpfile.write('Available activities: %s\n' % ', '.join(
        [act['name'] for act in activities]))
    tmpfile.flush()
    new_file_name = tmpfile.name
    tmpfile.close()
    return new_file_name


def read_from_file(filename, activities):
    tmpfile = open(filename, 'r')
    data = tmpfile.readlines()
    tmpfile.close()
    bookings = []
    spentdate = None
    default_activity = get_default_activity(activities)
    default_act_name = default_activity.get('name', '[noname]')
    default_columns = [1, '', '0:0', default_act_name, -1, '', '']

    for line in data:
        if line.startswith('Clock summary at ['):
            splitdate = line[18:-2].split(' ')[0].split('-')
            spentdate = datetime(int(splitdate[0]),
                                 int(splitdate[1]),
                                 int(splitdate[2]))
            continue
        if not line.startswith('|') or re.match('^[+-|]*\n', line):
            continue
        columns = [val.strip() for val in re.findall(' *([^|\n]+) *', line)]
        if columns[0] in ['L', '']:
            continue
        columns = columns + default_columns[len(columns):]
        hours, minutes = columns[2].split(':')
        spenttime = int(hours) * 60 + int(minutes)
        bookings.append({'issue_id': columns[4],
                         'spent_on': spentdate.strftime('%Y-%m-%d'),
                         'time': float(spenttime),
                         'comments': columns[6].decode('utf-8'),
                         'project': columns[5].decode('utf-8'),
                         'description': columns[1].decode('utf-8'),
                         'activity': columns[3].decode('utf-8'),
                         })
    return spentdate, bookings


def clean_up_bookings(bookings):
    removed_time = 0.0
    ignored_time = 0.0
    removed_bookings = []
    for booking in bookings[:]:
        if booking['issue_id'] is None:
            if booking['category'] == u'Work':
                removed_time += booking['time']
                removed_bookings.append(booking)
                bookings.remove(booking)
            else:
                ignored_time += booking['time']

    if not bookings:
        return removed_bookings

    sum_time = get_time_sum(bookings) - ignored_time

    if ignored_time > 3. * 60.:
        print('*** Warning: Ignored time is {0} {1}'.format(
            ignored_time, format_spent_time(ignored_time)))
    if sum_time and (removed_time / sum_time) > .1:
        print('*** Warning: Removed time is {0} ({1}) ({2:.2f}%)'.format(
            removed_time,
            format_spent_time(removed_time),
            removed_time / (removed_time + sum_time) * 100))
        for booking in sorted(removed_bookings, key=lambda b: b['time'], reverse=True):
            print('    Removed {0} ({1:.0f})'.format(
                booking['description'], booking['time']))

    for booking in bookings:
        if booking['category'] == u'Work':
            booking['time'] += removed_time * booking['time'] / sum_time
    return bookings


class Redmine(object):
    def __init__(self, url, user, password):
        class RedmineResource(ActiveResource):
            _site = url
            _user = user
            _password = password

        class TimeEntry(RedmineResource):
            pass

        class Enumerations(RedmineResource):
            pass

        class Issue(RedmineResource):
            pass

        class Projects(RedmineResource):
            pass

        self.TimeEntry = TimeEntry
        self.Enumerations = Enumerations
        self.Issue = Issue
        self.Projects = Projects

        try:
            self.activities = self.Enumerations.get('time_entry_activities')
        except connection.Error:
            print('Could not get redmine activities: Connection error')
            self.activities = []

    def book_redmine(self, bookings):
        default_activity = get_default_activity(self.activities)
        for entry in bookings:
            if not ticket_pattern_redmine.match(entry['issue_id']):
                continue
            if entry['issue_id'] is None:
                print("No valid issue id, skipping entry (%s)" %
                    entry['description'])
                continue
            rm_entry = entry.copy()

            activities_dict = dict([(act['name'], act) for act in self.activities])
            act = activities_dict.get(entry['activity'])
            rm_entry['activity_id'] = act and act['id'] or default_activity['id']
            rm_entry['hours'] = rm_entry['time'] / 60.
            del rm_entry['time']

            if 'description' in rm_entry:
                del rm_entry['description']
            if 'activity' in rm_entry:
                del rm_entry['activity']

            rm_time_entry = self.TimeEntry(rm_entry)
            success = rm_time_entry.save()
            if not success:
                for field, msgs in rm_time_entry.errors.errors.items():
                    print(u'{0}: {1} ({2})'.format(
                        field, u','.join(msgs), rm_entry['comments']))


class Jira(object):
    def __init__(self, url, user, password):
        self.jira = JIRA(url, auth=(user, password))

    def book_jira(self, bookings):
        for entry in bookings:
            if not ticket_pattern_jira.match(entry['issue_id']):
                continue
            rm_entry = entry.copy()

            rm_entry['hours'] = rm_entry['time'] / 60.
            del rm_entry['time']

            if 'description' in rm_entry:
                del rm_entry['description']
            if 'activity' in rm_entry:
                del rm_entry['activity']

            try:
                self.jira.add_worklog(
                    issue=entry['issue_id'],
                    timeSpent=entry['time'],
                    started=datetime.strptime(entry['spent_on'], '%Y-%m-%d'),
                    comment=entry['comments'],
                )
            except JIRAError as je:
                print(u'{0}: {1} ({2})'.format(
                    je.status_code, je.text, rm_entry['comments']))


class Tracking(object):

    def __init__(self, redmine=None, jira=None, harvest=None, project_mapping={}, task_mapping={}, project_history_file=None):
        self.redmine = redmine
        self.jira = jira
        self.harvest = harvest
        self.project_mapping = project_mapping
        self.task_mapping = task_mapping
        self._projects = []
        self._issue_to_project = {}
        if project_history_file is None:
            self.project_history_file = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'octodon-projects.pickle')
        else:
            self.project_history_file = project_history_file


    @property
    def projects(self):
        if not self._projects:
            harvest_data = {}
            try:
                harvest_data = self.harvest.get_day()
                self._projects = harvest_data['projects']
            except Exception as e:
                print('Could not get harvest projects: {0}: {1}'.format(
                    e.__class__.__name__, e))
                if u'message' in harvest_data:
                    print(harvest_data[u'message'])
                self._projects = []
        return self._projects

    def book_harvest(self, bookings):
        if not self.harvest:
            return
        projects_lookup = dict(
            [(project[u'code'], project) for project in self.projects])
        for entry in bookings:
            project = projects_lookup[entry['project']]
            project_id = project and project[u'id'] or -1
            tasks_lookup = dict(
                [(task[u'name'], task) for task in project[u'tasks']])
            task = tasks_lookup.get(entry['activity'])
            task_id = task and task[u'id'] or -1

            issue_title = ''
            if entry['issue_id'] is not None:
                if ticket_pattern_jira.match(entry['issue_id']) and self.jira:
                    try:
                        issue = self.jira.jira.issue(entry['issue_id'])
                        issue_title = issue.fields.summary
                    except JIRAError as je:
                        print(u'Could not find issue {0}: {1} - {2}'.format(
                            str(entry['issue_id']), je.status_code, je.text, ))
                if not issue_title and self.redmine:
                    try:
                        issue = self.redmine.Issue.get(int(entry['issue_id']))
                        issue_title = issue['subject']
                    except (ResourceNotFound, connection.Error):
                        print('Could not find issue ' + str(entry['issue_id']))

            self.harvest.add(
                {'notes': '[#{1}] {2}: {0}'.format(
                    entry['comments'].encode('utf-8'),
                    str(entry['issue_id']).encode('utf-8'),
                    issue_title.encode('utf-8')),
                 'project_id': project_id,
                 'hours': str(entry['time'] / 60.),
                 'task_id': task_id,
                 'spent_at': entry['spent_on'],
                 })
            self.remember_project(entry['issue_id'], project['code'])

    def _load_project_history(self):
        if not os.path.exists(self.project_history_file):
            self._issue_to_project = {}
        else:
            with open(self.project_history_file, 'rb') as cache:
                self._issue_to_project = pickle.load(cache)

    def remember_project(self, issue_id, project_code):
        self._load_project_history()
        self._issue_to_project[issue_id] = project_code
        with open(self.project_history_file, 'wb') as cache:
            pickle.dump(self._issue_to_project, cache)

    def recall_project(self, issue_id, default=None):
        self._load_project_history()
        return self._issue_to_project.get(issue_id, default)

    def redmine_harvest_mapping(self, harvest_projects, project=None,
                                tracker=None, contracts=[], description=''):
        task = 'Development'
        for key, value in self.task_mapping.items():
            if key in description.lower():
                task = value
                break

        harvest_project = ''
        if project in self.project_mapping:
            harvest_project = self.project_mapping[project]
        elif project in harvest_projects:
            harvest_project = project
        elif project:
            part_matches = [
                proj for proj in harvest_projects
                if project.lower().startswith(proj.lower())
                or proj.lower().startswith(project.lower())]
            if part_matches:
                harvest_project = part_matches[0]
        if not harvest_project:
            for contract in contracts:
                if contract in harvest_projects:
                    harvest_project = contract
                    break
                part_matches = [
                    proj for proj in harvest_projects
                    if contract.lower() in proj.lower()]
                if part_matches:
                    harvest_project = part_matches[0]
        # Because of harvest's limited filtering we want bugs in a separate project.
        if tracker == 'Bug':
            if 'recensio' in harvest_project.lower():
                harvest_project = 'recensio-bugpool'
            if 'star' in harvest_project.lower():
                harvest_project = 'star-bugpool'
        return (harvest_project, task)


    def get_harvest_target(self, entry):
        harvest_projects = [project[u'code'] for project in self.projects]

        issue_no = entry['issue_id']
        issue = None
        project = ''
        contracts = []
        if issue_no is not None:
            if ticket_pattern_jira.match(issue_no) and self.jira:
                try:
                    issue = self.jira.jira.issue(issue_no)
                except JIRAError as je:
                    print(u'Could not find issue {0}: {1} - {2}'.format(
                        str(issue_no), je.status_code, je.text, ))
            elif self.redmine:
                try:
                    issue = self.redmine.Issue.get(issue_no)
                except (ResourceNotFound, connection.Error, socket.error):
                    print('Could not find issue ' + str(issue_no))

        if issue is not None:
            if ticket_pattern_jira.match(issue_no) and self.jira:
                project = issue.fields.project.key
                contracts_field = issue.fields.customfield_10902
                contracts = ([contracts_field.child.value]
                             if hasattr(contracts_field, 'child')
                             else [])
            elif self.redmine:
                pid = issue['project']['id']
                try:
                    project = self.redmine.Projects.get(pid)['identifier'].decode('utf-8')
                except Exception as e:
                    print('Could not get project identifier: {0}; {1}'.format(
                        issue['project']['name'], e))
                    project = ''
                contracts = [f.get('value', []) for f in issue['custom_fields'] if
                            f['name'].startswith('Contracts')]

        for tag in entry['tags']:
            if tag in harvest_projects:
                project = tag.decode('utf-8')
        if entry['category'] in harvest_projects:
            project = entry['category']

        tracker = None
        if issue_no and ticket_pattern_jira.match(issue_no) and self.jira:
            tracker = issue and issue.fields.issuetype.name
        elif self.redmine:
            tracker = issue and issue['tracker']['name']

        harvest_project, task = self.redmine_harvest_mapping(
            harvest_projects,
            project=project,
            tracker=tracker,
            contracts=contracts,
            description=entry['description'])
        if not harvest_project:
            harvest_project = self.recall_project(
                issue_no, default=harvest_project)
        if not harvest_project and (project or tracker or contracts):
            print('No project match for {0}, {1}, {2}, {3}'.format(
                project, tracker, contracts, entry['description']))
        return harvest_project, task


class Octodon(Cmd):
    def __init__(self, config, spent_on, new_session=False, *args):
        Cmd.__init__(self, *args)
        self.config = get_config(cfgfile)

        if config.get('main', 'source') == 'hamster':
            self.time_log = HamsterTimeLog()
        elif config.get('main', 'source') == 'orgmode':
            filename = config.get('orgmode', 'filename')
            self.time_log = OrgModeTimeLog(filename)
        elif config.get('main', 'source') == 'plaintext':
            log_path = config.get('plaintext', 'log_path')
            self.time_log = ClockWorkTimeLog(log_path=log_path)

        self.redmine = None
        if config.has_section('redmine'):
            if config.has_option('redmine', 'password_command'):
                cmd = config.get('redmine', 'password_command')
                password = subprocess.check_output(cmd.split(' ')).strip().decode("utf-8")
                config.set('redmine', 'pass', password)
            self.redmine = Redmine(
                config.get('redmine', 'url'),
                config.get('redmine', 'user'),
                config.get('redmine', 'pass'))

        self.jira = None
        if config.has_section('jira'):
            if config.has_option('jira', 'password_command'):
                cmd = config.get('jira', 'password_command')
                password = subprocess.check_output(cmd.split(' ')).strip().decode("utf-8")
                config.set('jira', 'pass', password)
            self.jira = Jira(
                config.get('jira', 'url'),
                config.get('jira', 'user'),
                config.get('jira', 'pass'))

        vcs_class = {
            'git': GitLog,
            'svn': SvnLog,
        }

        self.vcs_list = []
        for vcs in self.config.get('main', 'vcs').split('\n'):
            if not vcs:
                continue
            if not self.config.has_section(vcs):
                continue
            author = None
            repos = []
            if self.config.has_option(vcs, 'author'):
                author = self.config.get(vcs, 'author')
            if self.config.has_option(vcs, 'repos'):
                repos = [r for r in self.config.get(vcs, 'repos').split('\n')
                         if r.strip()]
            if self.config.has_option(vcs, 'executable'):
                exe = self.config.get(vcs, 'executable')
            else:
                exe = '/usr/bin/env ' + vcs
            self.vcs_list.append({
                'name': vcs,
                'class': vcs_class.get(vcs, VCSLog),
                'author': author,
                'repos': repos,
                'exe': exe,
            })

        if config.has_section('harvest'):
            from harvest import Harvest
            if config.has_option('harvest', 'password_command'):
                cmd = config.get('harvest', 'password_command')
                password = subprocess.check_output(cmd.split(' ')).strip().decode("utf-8")
                config.set('harvest', 'pass', password)
            harvest = Harvest(
                    config.get('harvest', 'url'),
                    config.get('harvest', 'user'),
                    config.get('harvest', 'pass'))
        else:
            harvest = None

        if self.config.has_option('main', 'project-mapping'):
            project_mapping = self.config.get('main', 'project-mapping')
            project_mapping = project_mapping.split('\n')
            project_mapping = dict([pair.split(' ')
                                    for pair in project_mapping if pair])
        else:
            project_mapping = {}

        if self.config.has_option('main', 'task-mapping'):
            task_mapping = self.config.get('main', 'task-mapping')
            task_mapping = task_mapping.split('\n')
            task_mapping = dict([pair.split(' ', 1)
                                 for pair in task_mapping if pair])
        else:
            task_mapping = {}

        self.tracking = Tracking(
            redmine=self.redmine,
            jira=self.jira,
            harvest=harvest,
            project_mapping=project_mapping,
            task_mapping=task_mapping,
        )

        self.prompt = 'octodon> '
        self.sessionfile = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '.octodon_session_timelog.rst')
        activities = self.redmine and self.redmine.activities or []
        if os.path.exists(self.sessionfile):
            start_new_session = (
                new_session or
                raw_input('Continue existing session? [Y/n] ').lower() == 'n'
            )
            if not start_new_session:
                spent_on, self.bookings = read_from_file(
                    self.sessionfile, activities=activities)
            else:
                spent_on, self.bookings = self.get_bookings(spent_on)
                self.bookings = clean_up_bookings(self.bookings)
            os.remove(self.sessionfile)
        else:
            spent_on, self.bookings = self.get_bookings(spent_on)
            self.bookings = clean_up_bookings(self.bookings)

        self.sessionfile = write_to_file(
            self.bookings,
            spent_on,
            activities,
            file_name=self.sessionfile)

    def get_bookings(self, spent_on, search_back=4):
        bookings = None
        for i in range(search_back):
            bookings = self._get_bookings(spent_on - timedelta(i))
            if bookings:
                break
        return spent_on - timedelta(i), bookings

    def _get_bookings(self, spent_on):
        loginfo = {}
        for vcs_config in self.vcs_list:
            vcslog = vcs_config['class'](exe=vcs_config['exe'])
            try:
                loginfo = vcslog.get_loginfo(
                    date=spent_on,
                    author=vcs_config['author'],
                    repos=vcs_config['repos'],
                    mergewith=loginfo)
            except NotImplemented:
                print('Unrecognized vcs: %s' % vcs_config['name'])

        activities = self.redmine and self.redmine.activities or []
        bookings = self.time_log.get_timeinfo(
            date=spent_on,
            loginfo=loginfo,
            activities=activities)
        if self.tracking.harvest is not None:
            for entry in bookings:
                project, task = self.tracking.get_harvest_target(entry)
                entry['project'] = project
                entry['activity'] = task
        return bookings

    def check_issue_and_comment(self, bookings):
        no_issue_or_comment = [
            entry for entry in bookings
            if entry['issue_id'] is None or len(entry['comments']) <= 0]
        activities = self.redmine and self.redmine.activities or []
        if len(no_issue_or_comment) > 0:
            rows = [make_row(entry, activities) for entry in no_issue_or_comment]
            print('Warning: No issue id and/or comments for the following entries:'
                '\n{0}'.format(make_table(rows)))

    def print_summary(self, bookings):
        total_time = get_time_sum(bookings)
        total_hours = total_time / 60.
        print('total hours: %.2f (%s)' % (
            total_hours, format_spent_time(total_time)))

    def postcmd(self, stop, line):
        if not stop:
            self.print_summary(self.bookings)
        return stop

    def do_edit(self, *args):
        """ Edit the current time booking values in an editor. """
        subprocess.check_call(
            [config.get('main', 'editor') + ' ' + self.sessionfile],
            shell=True)
        activities = self.redmine and self.redmine.activities or []
        spent_on, self.bookings = read_from_file(
            self.sessionfile, activities)
        self.check_issue_and_comment(self.bookings)

    def do_redmine(self, *args):
        """ Write current bookings to redmine. """
        try:
            self.redmine.book_redmine(self.bookings)
        except Exception as e:
            print('Error while booking - comments too long? Error was: '
                    '%s: %s' % (e.__class__.__name__, e))

    def do_jira(self, *args):
        """ Write current bookings to jira. """
        try:
            self.jira.book_jira(self.bookings)
        except Exception as e:
            print('Error while booking - '
                    '%s: %s' % (e.__class__.__name__, e))

    def do_harvest(self, *args):
        """ Write current bookings to harvest. """
        try:
            self.tracking.book_harvest(self.bookings)
        except Exception as e:
            print('Error while booking - '
                    '%s: %s' % (e.__class__.__name__, e))

    def do_book(self, *args):
        """ Write current bookings to all configured targets. """
        if self.redmine:
            self.do_redmine()
        if self.jira:
            self.do_jira()
        self.do_harvest()

    def do_fetch(self, *args):
        """ EXPERIMENTAL. Freshly fetch bookings from source. """
        old_bookings = self.bookings[:]
        spent_on, bookings = self.get_bookings(spent_on)
        bookings = clean_up_bookings(bookings)
        import ipdb; ipdb.set_trace()

    def do_exit(self, line):
        return True

    def do_quit(self, line):
        return True

    def do_EOF(self, line):
        return True


def get_config(cfgfile):
    config = SafeConfigParser()
    default_cfgfile = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   'defaults.cfg')
    config.readfp(open(default_cfgfile))

    editor = os.environ.get('EDITOR')
    if editor:
        config.set('main', 'editor', editor)

    if not os.path.exists(cfgfile):
        print('Warning: config file {0} not found! Trying '
              'octodon.cfg'.format(cfgfile))
        if not os.path.exists('octodon.cfg'):
            print('No config file found! Please create %s' % cfgfile)
            sys.exit(1)
        config.read('octodon.cfg')
    config.read(cfgfile)
    return config


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Extract time tracking data '
        'from hamster or emacs org mode and book it to redmine/jira/harvest')
    parser.add_argument(
        '--date',
        type=str,
        help='the date for which to extract tracking data, in format YYYYMMDD'
        ' or as an offset in days from today, e.g. -1 for yesterday')
    parser.add_argument(
        '--config-file',
        '-c',
        type=str,
        help='the configuration file to use for this session')
    parser.add_argument(
        '--new-session',
        '-n',
        action='store_true',
        help='discard any existing session and start a new one')
    args = parser.parse_args()

    if args.config_file:
        cfgfile = args.config_file
    else:
        cfgfile = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'octodon.cfg')
    config = get_config(cfgfile)

    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if now.hour >= 16:
        spent_on = today
    else:
        spent_on = today - timedelta(1)
    if args.date:
        if args.date == 'today':
            spent_on = today
        elif re.match(r'[+-][0-9]*$', args.date):
            spent_on = today + timedelta(int(args.date))
        elif re.match(r'[0-9]{8}$', args.date):
            spent_on = datetime.strptime(args.date, '%Y%m%d')
        elif re.match(r'[0-9]{4}-[0-9]{2}-[0-9]{2}$', args.date):
            spent_on = datetime.strptime(args.date, '%Y-%m-%d')
        else:
            raise Exception('unrecognized date format: {0}'.format(
                args.date))

    octodon = Octodon(config, spent_on, new_session=args.new_session)
    octodon.cmdloop()
