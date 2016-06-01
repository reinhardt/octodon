#!/usr/bin/env python
from datetime import datetime, timedelta
from ConfigParser import SafeConfigParser
import argparse
import subprocess
from tempfile import NamedTemporaryFile
import re
import sys
import os
import math
from pyactiveresource.activeresource import ActiveResource
from pyactiveresource.connection import ResourceNotFound
from pyactiveresource import connection


ticket_pattern = re.compile('#([0-9]+)')
ref_pattern = re.compile('(?:    )?(.*)#([0-9]+)')
ref_keyword_pattern = re.compile('([Rr]efs |[Ff]ixes )$')


def get_default_activity(activities):
    default_activity = [act for act in activities
                        if act.get('is_default', False)]
    fallback = {'id': None}
    return default_activity and default_activity[0] or fallback


def get_ticket_no(strings):
    tickets = [ticket_pattern.search(s).group(1) for s in strings
               if ticket_pattern.search(s)]
    return len(tickets) and int(tickets[0]) or -1


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
                             'comments': '; '.join(loginfo.get(ticket, [])),
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


class VCSLog(object):

    def __init__(self, exe=None):
        self.exe = exe

    def extract_loginfo(self, log, mergewith={}):
        matches = ref_pattern.finditer(log) or []
        logdict = mergewith
        for match in matches:
            comment = ref_keyword_pattern.sub('', match.group(1))
            comment = comment.strip(' ,').strip(' .')
            logdict.setdefault(int(match.group(2)), []).append(comment)
        return logdict


    def _get_loginfo(self, command, args, repos=[], mergewith={}):
        logdict = mergewith
        for repo in repos:
            if not os.path.exists(repo):
                print("Warning: Repository path does not exist: {0}".format(repo))
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
    return string + ' ' * (length - len(string))


def make_row(entry, activities):
    act_name = entry['activity']
    return ['1',
            entry['description'].encode('utf-8'),
            format_spent_time(entry['time']),
            act_name,
            '%04d' % entry['issue_id'],
            entry['project'].encode('utf-8'),
            entry['comments'].encode('utf-8'),
            ]


def make_table(rows):
    rows = [['L', 'Headline', 'Time', 'Activity', 'iss', 'Project', 'Comments']] + rows
    columns = zip(*rows)
    max_lens = [max([len(entry) for entry in column]) for column in columns]
    out_strs = []
    divider = u'+%s+' % u'+'.join(
        [u'-' * (max_len + 2) for max_len in max_lens]
    )
    for row in rows:
        vals = []
        for i in range(len(row)):
            vals.append(u' %s ' % pad(row[i], max_lens[i]))
        row_str = u'|%s|' % u'|'.join(vals)
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
    tmpfile.write(u'#+BEGIN: clocktable :maxlevel 2 :scope file\n')
    tmpfile.write(u'Clock summary at [' +
                  summary_time.strftime('%Y-%m-%d %a %H:%M') + u']\n')
    tmpfile.write('\n')

    rows = []

    sum = get_time_sum(bookings)
    rows.append([' ', u'*Total time*', u'*%s*' % format_spent_time(sum), ' ',
                 ' ', ' ', ' '])
    rows += [make_row(entry, activities) for entry in bookings]
    tmpfile.write(make_table(rows))

    tmpfile.write(u'\n')
    tmpfile.write(u'\n')
    tmpfile.write(u'Available activities: %s\n' % u', '.join(
        [act['name'] for act in activities]))
    tmpfile.flush()
    return tmpfile


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
        bookings.append({'issue_id': int(columns[4]),
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
    for booking in bookings:
        if booking['issue_id'] == -1:
            if booking['category'] == u'Work':
                print('Removing ' + booking['description'])
                removed_time += booking['time']
                bookings.remove(booking)
            else:
                ignored_time += booking['time']
    sum_time = get_time_sum(bookings) - ignored_time
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

        self.TimeEntry = TimeEntry
        self.Enumerations = Enumerations
        self.Issue = Issue

        try:
            self.activities = self.Enumerations.get('time_entry_activities')
        except connection.Error:
            print('Could not get redmine activities: Connection error')
            self.activities = []

    def book_redmine(self, bookings):
        default_activity = get_default_activity(self.activities)
        for entry in bookings:
            if entry['issue_id'] <= 0:
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


class Tracking(object):

    harvest_task_map = {
        'Support': 'Development',
        'Feature': 'Development',
        'Tasks': 'Development',
        'Bug': 'Bugfixing',
    }

    def __init__(self, redmine, harvest):
        self.redmine = redmine
        self.harvest = harvest

    def book_harvest(self, bookings):
        projects = self.harvest.get_day()['projects']
        projects_lookup = dict(
            [(project[u'name'], project) for project in projects])
        for entry in bookings:
            project = projects_lookup[entry['project']]
            project_id = project and project[u'id'] or -1
            tasks_lookup = dict(
                [(task[u'name'], task) for task in project[u'tasks']])
            task = tasks_lookup.get(entry['activity'])
            task_id = task and task[u'id'] or -1

            issue = None
            if entry['issue_id'] > 0:
                try:
                    issue = self.redmine.Issue.get(entry['issue_id'])
                except (ResourceNotFound, connection.Error):
                    print('Could not find issue ' + str(entry['issue_id']))

            if issue is not None:
                issue_title = issue['subject']

            self.harvest.add(
                {'notes': '#{1} {2}: {0}'.format(
                 entry['comments'], str(entry['issue_id']), issue_title),
                 'project_id': project_id,
                 'hours': str(entry['time'] / 60.),
                 'task_id': task_id,
                 'spent_at': entry['spent_on'],
                 })

    def redmine_harvest_mapping(self, harvest_projects, project=None,
                                tracker=None, contracts=[], description=''):
        task = self.harvest_task_map.get(tracker, 'Development')
        if 'scrum' in description.lower():
            task = 'SCRUM Meetings'
        harvest_project = ''
        if project in harvest_projects:
            harvest_project = project
        elif project:
            part_matches = [
                proj for proj in harvest_projects
                if project.lower() in proj.lower()
                or proj.lower() in project.lower()]
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
        if task == 'Bugfixing':
            if 'recensio' in harvest_project.lower():
                harvest_project = 'Recensio Bugpool'
            if 'star' in harvest_project.lower():
                harvest_project = 'Star Bugpool'
        return (harvest_project, task)


    def get_harvest_target(self, entry):
        try:
            projects = self.harvest.get_day()['projects']
        except Exception as e:
            print('Could not get harvest projects: {0}: {1}'.format(
                e.__class__.__name__, e))
            projects = []
        harvest_projects = [project[u'name'] for project in projects]

        issue_no = entry['issue_id']
        issue = None
        project = ''
        contracts = []
        if issue_no > 0:
            try:
                issue = self.redmine.Issue.get(issue_no)
            except (ResourceNotFound, connection.Error):
                print('Could not find issue ' + str(issue_no))

        if issue is not None:
            project = issue['project']['name'].decode('utf-8')
            contracts = [f.get('value', []) for f in issue['custom_fields'] if
                        f['name'].startswith('Contracts')]

        for tag in entry['tags']:
            if tag in harvest_projects:
                project = unicode(tag)
        if entry['category'] in harvest_projects:
            project = entry['category']

        tracker = issue and issue['tracker']['name']

        return self.redmine_harvest_mapping(
            harvest_projects,
            project=project,
            tracker=tracker,
            contracts=contracts,
            description=entry['description'])


class Octodon(object):
    def __init__(self, config):
        self.config = get_config(cfgfile)

        if config.get('main', 'source') == 'hamster':
            self.time_log = HamsterTimeLog()
        elif config.get('main', 'source') == 'orgmode':
            filename = config.get('orgmode', 'filename')
            self.time_log = OrgModeTimeLog(filename)

        self.redmine = Redmine(
            config.get('redmine', 'url'),
            config.get('redmine', 'user'),
            config.get('redmine', 'pass'))

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
                #XXX better default
                exe = '/usr/bin/' + vcs
            self.vcs_list.append({
                'name': vcs,
                'class': vcs_class.get(vcs, VCSLog),
                'author': author,
                'repos': repos,
                'exe': exe,
            })

        if config.has_section('harvest'):
            from harvest import Harvest
            harvest = Harvest(
                    config.get('harvest', 'url'),
                    config.get('harvest', 'user'),
                    config.get('harvest', 'pass'))
        else:
            harvest = None

        self.tracking = Tracking(self.redmine, harvest)

    def get_bookings(self, spent_on):
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

        bookings = self.time_log.get_timeinfo(
            date=spent_on,
            loginfo=loginfo,
            activities=self.redmine.activities)
        if self.tracking.harvest is not None:
            for entry in bookings:
                project, task = self.tracking.get_harvest_target(entry)
                entry['project'] = project
                entry['activity'] = task
        return bookings

    def print_summary(self, bookings):
        no_issue_or_comment = [
            entry for entry in bookings
            if entry['issue_id'] < 0 or len(entry['comments']) <= 0]
        if len(no_issue_or_comment) > 0:
            rows = [make_row(entry, self.redmine.activities) for entry in no_issue_or_comment]
            print('Warning: No issue id and/or comments for the following entries:'
                '\n{0}'.format(make_table(rows)))
        total_time = get_time_sum(bookings)
        total_hours = total_time / 60.
        print('total hours: %.2f (%s)' % (
            total_hours, format_spent_time(total_time)))

    def __call__(self, spent_on):
        sessionfile = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '.octodon_session_timelog')
        if os.path.exists(sessionfile):
            continue_session = raw_input('Continue existing session? [Y/n] ')
            if not continue_session.lower() == 'n':
                spent_on, bookings = read_from_file(
                    sessionfile, activities=self.redmine.activities)
            else:
                bookings = self.get_bookings(spent_on)
                bookings = clean_up_bookings(bookings)
            os.remove(sessionfile)
        else:
            bookings = self.get_bookings(spent_on)
            bookings = clean_up_bookings(bookings)

        finished = False
        edit = True
        while not finished:
            if edit:
                tempfile = write_to_file(
                    bookings,
                    spent_on,
                    self.redmine.activities,
                    file_name=sessionfile)
                subprocess.check_call(
                    [config.get('main', 'editor') + ' ' + tempfile.name],
                    shell=True)
                spent_on, bookings = read_from_file(
                    tempfile.name, self.redmine.activities)
                tempfile.close()

            self.print_summary(bookings)
            action = raw_input(
                '(e)dit again/book (r)edmine/book (h)arvest/(b)ook all/'
                '(q)uit/(Q)uit and discard session? [e] ')

            if bookings and action.lower() in ['b', 'r']:
                try:
                    self.redmine.book_redmine(bookings)
                except Exception as e:
                    print('Error while booking - comments too long? Error was: '
                          '%s: %s' % (e.__class__.__name__, e))
                edit = False
            if bookings and action.lower() in ['b', 'h']:
                try:
                    self.tracking.book_harvest(bookings)
                except Exception as e:
                    print('Error while booking - '
                          '%s: %s' % (e.__class__.__name__, e))
                edit = False

            if action == 'q':
                finished = True
            if action == 'Q':
                finished = True
                os.remove(sessionfile)
            if action == 'e' or action == '':
                edit = True


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
        'from hamster or emacs org mode and book it to redmine')
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
        else:
            raise Esception('unrecognized date format: {0}'.format(
                args.date))

    octodon = Octodon(config)
    octodon(spent_on)
