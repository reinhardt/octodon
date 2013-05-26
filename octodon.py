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


class Issue(ActiveResource):
    _site = None
    _user = None
    _password = None


ticket_pattern = re.compile('#([0-9]+)')
ref_pattern = re.compile('    (.*)(refs |fixes )#([0-9]+)')


def get_default_activity(activities):
    default_activity = [act for act in activities
                        if act['is_default'] == 'true']
    return default_activity and default_activity[0] or None


def get_ticket_no(strings):
    tickets = [ticket_pattern.search(s).group(1) for s in strings
               if ticket_pattern.search(s)]
    return len(tickets) and int(tickets[0]) or -1


def get_timeinfo(source='hamster', date=datetime.now(), baseurl='',
                 loginfo={}, activities=[]):
    if source['type'] == 'hamster':
        return get_timeinfo_hamster(date=date, baseurl=baseurl,
                                    loginfo=loginfo, activities=activities)
    elif source['type'] == 'orgmode':
        if not source.get('filename'):
            print('Please specify a source file name for org mode!')
            sys.exit(2)
        return get_timeinfo_orgmode(date=date, baseurl=baseurl,
                                    loginfo=loginfo, activities=activities,
                                    filename=source['filename'])


def get_timeinfo_orgmode(filename, date=datetime.now(), baseurl='',
                         loginfo={}, activities=[]):
    bookings = read_from_file(filename, activities)
    for booking in bookings:
        ticket = get_ticket_no([booking['description']])
        booking['issue_id'] = ticket
        booking['comments'] = '; '.join(loginfo.get(ticket, []))
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
                         'activity_id': default_activity['id'],
                         'comments': '; '.join(loginfo.get(ticket, []))})
    return bookings


def extract_loginfo(log, mergewith={}):
    matches = ref_pattern.finditer(log) or []
    logdict = mergewith
    for match in matches:
        logdict.setdefault(int(match.group(3)),
                           []).append(match.group(1).strip(' ,'))
    return logdict


def get_loginfo_git(date=datetime.now(), author=None, repos=[], mergewith={}):
    command = ['/usr/bin/git', '--no-pager', 'log', '--all', '--reverse']
    args = ['--since="{%s}"' % date, '--until="{%s}"' % (date + timedelta(1))]
    if author:
        args.append('--author="%s"' % author)
    logdict = mergewith
    for repo in repos:
        os.chdir(repo)
        try:
            out = subprocess.check_output(' '.join(command + args), shell=True)
        except subprocess.CalledProcessError as cpe:
            print('git returned %d: %s' % (cpe.returncode, cpe.output))
            continue
        logdict = extract_loginfo(out, logdict)
    return logdict


def format_spent_time(time):
    hours = math.floor(time)
    mins = (time - hours) * 60
    return '%2d:%02d' % (hours, mins)


def pad(string, length):
    return string + ' ' * (length - len(string))


def make_table(rows):
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


def print_bookings(bookings):
    for i, b in enumerate(bookings):
        print('[%d]' % i)
        for key in b:
            print('  %s: %s' % (key, b[key]))
        print('')
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
    activities_dict = dict([(act['id'], act) for act in activities])
    summary_time = min(
        datetime.now(),
        (spent_on + timedelta(1) - timedelta(0, 1)))
    tmpfile.write('#+BEGIN: clocktable :maxlevel 2 :scope file\n')
    tmpfile.write('Clock summary at [' +
                  summary_time.strftime('%Y-%m-%d %a %H:%M') + ']\n')
    tmpfile.write('\n')

    rows = []
    rows.append(['L', 'Headline', 'Time', 'Activity', 'iss', 'Comments'])

    if len(bookings) == 0:
        sum = 0.
    else:
        sum = reduce(lambda x, y: x+y, map(lambda x: x['hours'], bookings))
    rows.append([' ', '*Total time*', '*%s*' % format_spent_time(sum), ' ',
                 ' ', ' '])
    rows += [['1',
              entry['description'],
              format_spent_time(entry['hours']),
              activities_dict[entry['activity_id']]['name'],
              '%04d' % entry['issue_id'],
              entry['comments'],
              ] for entry in bookings]
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
    activities_dict = dict([(act['name'], act) for act in activities])
    default_activity = get_default_activity(activities)
    print(default_activity['name'])
    default_columns = [1, '', '0:0', default_activity['name'], -1, '']

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
                         'comments': columns[5],
                         'description': columns[1],
                         'activity_id': activities_dict[columns[3]]['id'],
                        })
    return bookings


def book_time(TimeEntry, bookings):
    for entry in bookings:
        rm_entry = entry.copy()
        if 'description' in rm_entry:
            del rm_entry['description']
        redmine_entry = TimeEntry(rm_entry)
        redmine_entry.save()


if __name__ == "__main__":
    cfgfile = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'octodon.cfg')
    sessionfile = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               '.octodon_session_timelog')
    config = SafeConfigParser()
    if not os.path.exists(cfgfile):
        if not os.path.exists('octodon.cfg'):
            print('No config file found! Please create %s' % cfgfile)
            sys.exit(1)
        config.read('octodon.cfg')
    config.read(cfgfile)

    editor = os.environ.get('EDITOR', 'vi')
    if config.has_section('main') and config.has_option('main', 'editor'):
        editor = config.get('main', 'editor')

    class RedmineResource(ActiveResource):
        _site = config.get('redmine', 'url')
        _user = config.get('redmine', 'user')
        _password = config.get('redmine', 'pass')

    class TimeEntry(RedmineResource):
        pass

    class Enumerations(RedmineResource):
        pass

    activities = Enumerations.get('time_entry_activities')

    parser = argparse.ArgumentParser(
        description='Extract time tracking data '
        'from hamster or emacs org mode and book it to redmine')
    parser.add_argument(
        '--date',
        type=str,
        help='the date for which to extract tracking data, in format YYYYMMDD')
    args = parser.parse_args()

    if args.date:
        spent_on = datetime.strptime(args.date, '%Y%m%d')
    else:
        spent_on = datetime.now().replace(hour=0, minute=0, second=0,
                                          microsecond=0)

    loginfo = {}
    if config.has_section('main') and config.has_option('main', 'vcs') and \
            'git' in config.get('main', 'vcs'):
        author = config.get('git', 'author')
        repos = [r for r in config.get('git', 'repos').split('\n')
                 if r.strip()]
        loginfo = get_loginfo_git(date=spent_on, author=author, repos=repos,
                                  mergewith=loginfo)

    source = {'type': 'hamster'}
    if config.has_section('main') and config.has_option('main', 'source') and \
            config.get('main', 'source') in ['hamster', 'orgmode']:
        source['type'] = config.get('main', 'source')
        if config.has_section(source['type']):
            source.update(config.items(source['type']))

    if os.path.exists(sessionfile):
        continue_session = raw_input('Continue existing session? [Y/n] ')
        if not continue_session.lower() == 'n':
            bookings = read_from_file(sessionfile, activities=activities)
        else:
            bookings = get_timeinfo(
                source=source,
                date=spent_on,
                loginfo=loginfo,
                activities=activities)
        os.remove(sessionfile)
    else:
        bookings = get_timeinfo(
            source=source,
            date=spent_on,
            loginfo=loginfo,
            activities=activities)

    finished = False
    while not finished:
        tempfile = write_to_file(bookings, spent_on, activities)
        subprocess.check_call(
            [editor + ' ' + tempfile.name], shell=True)
        bookings = read_from_file(tempfile.name, activities)
        tempfile.close()

        print_bookings(bookings)
        book_now = raw_input('Book now? [y/N] ')

        if bookings and book_now.lower() == 'y':
            write_to_file(
                bookings,
                spent_on,
                activities=activities,
                file_name=sessionfile)
            book_time(TimeEntry, bookings)
            os.remove(sessionfile)
            finished = True
        else:
            edit_again = raw_input('Edit again? [Y/n] ')
            if edit_again.lower() == 'n':
                write_to_file(
                    bookings,
                    spent_on,
                    activities=activities,
                    file_name=sessionfile)
                finished = True
