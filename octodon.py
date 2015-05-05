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
ref_keyword_pattern = re.compile('([Rr]efs |[Ff]ixes )')


def get_default_activity(activities):
    default_activity = [act for act in activities
                        if act['is_default'] == 'true']
    fallback = {'id': None}
    return default_activity and default_activity[0] or fallback


def get_ticket_no(strings):
    tickets = [ticket_pattern.search(s).group(1) for s in strings
               if ticket_pattern.search(s)]
    return len(tickets) and int(tickets[0]) or -1


harvest_task_map = {
    'Support': 'Development',
    'Feature': 'Development',
    'Tasks': 'Development',
    'Bug': 'Bugfixing',
}


def redmine_harvest_mapping(harvest_projects, project=None, tracker=None):
    if tracker == 'Support' or tracker == 'Feature':
        task = 'Development'
    elif tracker == 'Bug':
        task = 'Bugfixing'
    else:
        task = ''
    task = harvest_task_map.get(tracker, 'Development')
    harvest_project = ''
    if project in harvest_projects:
        harvest_project = project
    else:
        part_matches = [
            proj for proj in harvest_projects
            if project.lower() in proj.lower()]
        if part_matches:
            harvest_project = part_matches[0]
    return (harvest_project, task)


def get_harvest_target(entry, Issue, harvest_projects, redmine_harvest_mapping):
    issue_no = entry['issue_id']
    if issue_no > 0:
        try:
            issue = Issue.get(issue_no)
        except (ResourceNotFound, connection.Error):
            print('Could not find issue ' + str(issue_no))
            return ('', '')
    else:
        return ('', '')

    project = issue['project']['name']

    for tag in entry['tags']:
        if tag in harvest_projects:
            project = str(tag)
    if entry['category'] in harvest_projects:
        project = entry['category']

    return redmine_harvest_mapping(
        harvest_projects,
        project=project,
        tracker=issue['tracker']['name'])


def get_timeinfo(config, date=datetime.now(), baseurl='',
                 loginfo={}, activities=[]):
    if config.get('main', 'source') == 'hamster':
        return get_timeinfo_hamster(date=date, baseurl=baseurl,
                                    loginfo=loginfo, activities=activities)
    elif config.get('main', 'source') == 'orgmode':
        filename = config.get('orgmode', 'filename')
        if not filename:
            print('Please specify a source file name for org mode!')
            sys.exit(2)
        return get_timeinfo_orgmode(date=date, baseurl=baseurl,
                                    loginfo=loginfo, activities=activities,
                                    filename=filename)


def get_timeinfo_orgmode(filename, date=datetime.now(), baseurl='',
                         loginfo={}, activities=[]):
    bookings = read_from_file(filename, activities)
    for booking in bookings:
        ticket = get_ticket_no([booking['description']])
        booking['issue_id'] = ticket
        booking['comments'] = '; '.join(loginfo.get(ticket, []))
        booking['project'] = ''
    return bookings


def get_timeinfo_hamster(date=datetime.now(), baseurl='',
                         loginfo={}, activities=[]):
    default_activity = get_default_activity(activities)
    from hamster.client import Storage
    sto = Storage()
    facts = sto.get_facts(date)
    bookings = []
    for fact in facts:
        #delta = (fact.end_time or datetime.now()) - fact.start_time
        #hours = round(fact.delta.seconds / 3600. * 4 + .25) / 4.
        hours = fact.delta.seconds / 3600.
        existing = filter(lambda b: b['description'] == fact.activity
                          and b['spent_on'] == fact.date, bookings)
        if existing:
            existing[0]['hours'] += hours
            continue
        ticket = get_ticket_no(
            fact.tags + [fact.activity] + [fact.description or ''])
        bookings.append({'issue_id': ticket,
                         'spent_on': fact.date,
                         'hours': hours,
                         'description': fact.activity,
                         'activity': default_activity.get('name', 'none'),
                         'comments': '; '.join(loginfo.get(ticket, [])),
                         'category': fact.category,
                         'tags': fact.tags,
                         'project': ''})
    return bookings


def extract_loginfo(log, mergewith={}):
    matches = ref_pattern.finditer(log) or []
    logdict = mergewith
    for match in matches:
        comment = ref_keyword_pattern.sub('', match.group(1))
        comment = comment.strip(' ,').strip(' .')
        logdict.setdefault(int(match.group(2)), []).append(comment)
    return logdict


def _get_loginfo(command, args, repos=[], mergewith={}):
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
        logdict = extract_loginfo(log, logdict)
    return logdict


def get_loginfo(vcs, date=datetime.now(), author=None, repos=[], mergewith={}):
    if vcs == 'git':
        return get_loginfo_git(
            date=date, author=author, repos=repos, mergewith=mergewith)
    elif vcs == 'svn':
        return get_loginfo_svn(
            date=date, author=author, repos=repos, mergewith=mergewith)
    else:
        print('Unrecognized vcs: %s' % vcs)
        return mergewith


def get_loginfo_git(date=datetime.now(), author=None, repos=[], mergewith={}):
    command = ['/usr/bin/git', '--no-pager', '-c', 'color.diff=false', 'log', '--all', '--reverse']
    args = ['--since="{%s}"' % date, '--until="{%s}"' % (date + timedelta(1))]
    if author:
        args.append('--author="%s"' % author)
    return _get_loginfo(
        command=command, args=args, repos=repos, mergewith=mergewith)


def get_loginfo_svn(date=datetime.now(), author=None, repos=[], mergewith={}):
    command = ['/usr/bin/svn', 'log']
    args = ['-r "{%s}:{%s}"' % (date, date + timedelta(1))]
    if author:
        args.append('--search="%s"' % author)
    return _get_loginfo(
        command=command, args=args, repos=repos, mergewith=mergewith)


def format_spent_time(time):
    hours = math.floor(time)
    mins = (time - hours) * 60
    return '%2d:%02d' % (hours, mins)


def pad(string, length):
    return string + ' ' * (length - len(string))


def make_row(entry, activities):
    act_name = entry['activity']
    return ['1',
            entry['description'],
            format_spent_time(entry['hours']),
            act_name,
            '%04d' % entry['issue_id'],
            entry['project'],
            entry['comments'],
            ]


def make_table(rows):
    rows = [['L', 'Headline', 'Time', 'Activity', 'iss', 'Project', 'Comments']] + rows
    columns = zip(*rows)
    max_lens = [max([len(entry) for entry in column]) for column in columns]
    out_strs = []
    divider = '+%s+' % '+'.join(
        ['-' * (max_len + 2) for max_len in max_lens]
    )
    for row in rows:
        vals = []
        for i in range(len(row)):
            vals.append(' %s ' % pad(row[i], max_lens[i]))
        row_str = '|%s|' % '|'.join(vals)
        out_strs.append(divider)
        out_strs.append(row_str)

    out_strs.append(divider)
    return '\n'.join(out_strs)


def print_summary(bookings, activities):
    no_issue_or_comment = [
        entry for entry in bookings
        if entry['issue_id'] < 0 or len(entry['comments']) <= 0]
    if len(no_issue_or_comment) > 0:
        rows = [make_row(entry, activities) for entry in no_issue_or_comment]
        print('Warning: No issue id and/or comments for the following entries:'
              '\n{0}'.format(make_table(rows)))
    print('total hours: %.2f' % get_time_sum(bookings))


def get_time_sum(bookings):
    if len(bookings) == 0:
        return 0.
    return reduce(lambda x, y: x+y, map(lambda x: x['hours'], bookings))


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
                  summary_time.strftime('%Y-%m-%d %a %H:%M') + ']\n')
    tmpfile.write('\n')

    rows = []

    if len(bookings) == 0:
        sum = 0.
    else:
        sum = reduce(lambda x, y: x+y, map(lambda x: x['hours'], bookings))
    rows.append([' ', '*Total time*', '*%s*' % format_spent_time(sum), ' ',
                 ' ', ' ', ' '])
    rows += [make_row(entry, activities) for entry in bookings]
    tmpfile.write(make_table(rows))

    tmpfile.write('\n')
    tmpfile.write('\n')
    tmpfile.write('Available activities: %s\n' % ', '.join(
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
        spenthours = float(hours) + float(minutes) / 60.
        bookings.append({'issue_id': int(columns[4]),
                         'spent_on': spentdate.date(),
                         'hours': float(spenthours),
                         'comments': columns[6],
                         'project': columns[5],
                         'description': columns[1],
                         'activity': columns[3],
                         })
    return bookings


def book_redmine(TimeEntry, bookings, activities):
    default_activity = get_default_activity(activities)
    for entry in bookings:
        rm_entry = entry.copy()

        activities_dict = dict([(act['name'], act) for act in activities])
        act = activities_dict.get(entry['activity'])
        rm_entry['activity_id'] = act and act['id'] or default_activity['id']

        if 'description' in rm_entry:
            del rm_entry['description']
        if 'activity' in rm_entry:
            del rm_entry['activity']

        redmine_entry = TimeEntry(rm_entry)
        redmine_entry.save()


def book_harvest(harvest, bookings):
    projects = harvest.get_day()['projects']
    projects_lookup = dict(
        [(project[u'name'], project) for project in projects])
    for entry in bookings:
        project = projects_lookup[entry['project']]
        project_id = project and project[u'id'] or -1
        tasks_lookup = dict(
            [(task[u'name'], task) for task in project[u'tasks']])
        task = tasks_lookup.get(entry['activity'])
        task_id = task and task[u'id'] or -1
        harvest.add({'notes': entry['comments'] + ' #' + str(entry['issue_id']),
                     'project_id': project_id,
                     'hours': str(entry['hours']),
                     'task_id': task_id,
                     'spent_at': entry['spent_on'],
                     })


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


def get_bookings(config, Issue, harvest, spent_on):
    loginfo = {}
    for vcs in config.get('main', 'vcs').split('\n'):
        if not vcs:
            continue
        if not config.has_section(vcs):
            continue
        author = None
        repos = []
        if config.has_option(vcs, 'author'):
            author = config.get(vcs, 'author')
        if config.has_option(vcs, 'repos'):
            repos = [r for r in config.get(vcs, 'repos').split('\n')
                     if r.strip()]
        loginfo = get_loginfo(
            vcs, date=spent_on, author=author, repos=repos, mergewith=loginfo)
    bookings = get_timeinfo(
        config=config,
        date=spent_on,
        loginfo=loginfo,
        activities=activities)
    if harvest is not None:
        try:
            projects = harvest.get_day()['projects']
        except Exception as e:
            print('Could not get harvest projects: {0}: {1}'.format(
                e.__class__.__name__, e))
            projects = []
        harvest_projects = [project[u'name'] for project in projects]
        for entry in bookings:
            project, task = get_harvest_target(
                entry,
                Issue,
                harvest_projects,
                redmine_harvest_mapping)
            entry['project'] = project
            entry['activity'] = task
    return bookings


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
    sessionfile = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               '.octodon_session_timelog')
    config = get_config(cfgfile)

    class RedmineResource(ActiveResource):
        _site = config.get('redmine', 'url')
        _user = config.get('redmine', 'user')
        _password = config.get('redmine', 'pass')

    class TimeEntry(RedmineResource):
        pass

    class Enumerations(RedmineResource):
        pass

    class Issue(RedmineResource):
        pass

    try:
        activities = Enumerations.get('time_entry_activities')
    except connection.Error:
        activities = []

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
            print('error: unrecognized date format: {0}'.format(args.date))
            exit(1)

    if config.has_section('harvest'):
        from harvest import Harvest
        harvest = Harvest(
            config.get('harvest', 'url'),
            config.get('harvest', 'user'),
            config.get('harvest', 'pass'))
    else:
        harvest = None

    if os.path.exists(sessionfile):
        continue_session = raw_input('Continue existing session? [Y/n] ')
        if not continue_session.lower() == 'n':
            bookings = read_from_file(sessionfile, activities=activities)
        else:
            bookings = get_bookings(config, Issue, harvest, spent_on)
        os.remove(sessionfile)
    else:
        bookings = get_bookings(config, Issue, harvest, spent_on)

    finished = False
    edit = True
    while not finished:
        if edit:
            tempfile = write_to_file(
                bookings,
                spent_on,
                activities,
                file_name=sessionfile)
            subprocess.check_call(
                [config.get('main', 'editor') + ' ' + tempfile.name],
                shell=True)
            bookings = read_from_file(tempfile.name, activities)
            tempfile.close()

        print_summary(bookings, activities)
        action = raw_input(
            '(e)dit again/book (r)edmine/book (h)arvest/(b)ook all/'
            '(q)uit/(Q)uit and discard session? [e] ')

        if bookings and action.lower() in ['b', 'r']:
            try:
                book_redmine(TimeEntry, bookings, activities)
            except Exception as e:
                print('Error while booking - comments too long? Error was: '
                      '%s: %s' % (e.__class__.__name__, e))
            edit = False
        if bookings and action.lower() in ['b', 'h']:
            try:
                book_harvest(harvest, bookings)
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
