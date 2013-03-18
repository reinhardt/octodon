#!/usr/bin/env python
from datetime import datetime, date, timedelta
from hamster.client import Storage
from ConfigParser import SafeConfigParser
import argparse
import subprocess
from tempfile import NamedTemporaryFile
import re
import sys, os, math
from pyactiveresource.activeresource import ActiveResource

class Issue(ActiveResource):
    _site = None
    _user = None
    _password = None

ticket_pattern = re.compile('#([0-9]+)')
ref_pattern = re.compile('    (.*)(refs |fixes )#([0-9]+)')

def get_timeinfo(date=datetime.now(), baseurl='', loginfo={}):
    sto = Storage()
    facts = sto.get_facts(date)
    bookings = []
    for fact in facts:
        #delta = (fact.end_time or datetime.now()) - fact.start_time
        #hours = round(fact.delta.seconds / 3600. * 4 + .25) / 4.
        hours = fact.delta.seconds / 3600.
        existing = filter(lambda b: b['description'] == fact.activity and b['spent_on'] == fact.date, bookings)
        if existing:
            existing[0]['hours'] += hours
            continue
        tickets = [ticket_pattern.search(s).group(1) for s in fact.tags + [fact.activity]  + [fact.description or ''] if ticket_pattern.search(s)]
        ticket = len(tickets) and int(tickets[0]) or -1
        bookings.append({'issue_id': ticket, 
                         'spent_on': fact.date,
                         'hours': hours, 
                         #'link': ticket and baseurl + '/issues/%d/time_entries/new' % int(ticket[1:]) or '',
                         'description': fact.activity,
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

def write_to_file(bookings, spent_on, file_name=None):
    if file_name is not None:
        tmpfile = open(file_name, 'w')
    else:
        tmpfile = NamedTemporaryFile(mode='w')
    summary_time = min(datetime.now(),
            (spent_on + timedelta(1) - timedelta(0,1)))
    tmpfile.write('#+BEGIN: clocktable :maxlevel 2 :scope file\n')
    tmpfile.write('Clock summary at [' + 
            summary_time.strftime('%Y-%m-%d %a %H:%M') + ']\n')
    tmpfile.write('\n')

    rows = []
    rows.append(['L', 'Headline', 'Time', 'iss', 'Comments'])

    if len(bookings) == 0:
        sum = 0.
    else:
        sum = reduce(lambda x,y: x+y, map(lambda x: x['hours'], bookings))
    rows.append([' ', '*Total time*', '*%s*' % format_spent_time(sum), ' ', 
                 ' '])
    rows += [['1',
              entry['description'],
              format_spent_time(entry['hours']),
              '%04d' % entry['issue_id'],
              entry['comments'],
              ] for entry in bookings]
    tmpfile.write(make_table(rows))
    tmpfile.flush()
    return tmpfile

def read_from_file(filename):
    tmpfile = open(filename, 'r')
    data = tmpfile.readlines()
    tmpfile.close()
    bookings = []
    spentdate = None
    for line in data:
        if line.startswith('Clock summary at ['):
            splitdate = line[18:-2].split(' ')[0].split('-')
            spentdate = datetime(int(splitdate[0]),
                                 int(splitdate[1]),
                                 int(splitdate[2]))
            continue
        if not line.startswith('|') or re.match('\+(-*\+)*-*\+', line):
            continue
        columns = [val.strip() for val in re.findall(' *([^|]+) *', line)]
        if columns[0] in ['L', '']:
            continue
        hours, minutes = columns[2].split(':')
        spenthours = float(hours) + float(minutes) / 60.
        bookings.append({'issue_id': int(columns[3]), 
                         'spent_on': spentdate.date(),
                         'hours': float(spenthours), 
                         'comments': columns[4],
                         'description': columns[1],})
    return bookings


def book_time(TimeEntry, bookings):
    for entry in bookings:
        rm_entry = entry.copy()
        if 'description' in rm_entry:
            del rm_entry['description']
        redmine_entry = TimeEntry(rm_entry)
        redmine_entry.save()

class BookingsMenu(object):
    
    bookings = []

    def __init__(self, bookings):
        self.bookings = bookings

    def __call__(self):
        self.print_all()
        command = self.get_command()
        while not command.startswith('c'):
            if command.startswith('e'):
                self.edit()
            elif command.isdigit():
                self.edit(int(command))
            elif command.startswith('d'):
                entry = int(raw_input('Delete Entry No.? '))
                del self.bookings[entry]
            elif command.startswith('b'):
                return self.bookings
            if command.startswith('a'):
                self.add()
            self.print_all()
            command = self.get_command()
        return None

    def get_command(self):
        print('[a]dd, [e]dit, [d]elete, [b]ook, [c]ancel')
        return raw_input('Command/Entry No.? ')
        
    def print_all(self):
        for i, b in enumerate(self.bookings):
            print('[%d]' % i)
            for key in b:
                print('  %s: %s' % (key, b[key]))
            print('')
        print('total hours: %.2f' % self.sum())

    def add(self):
        self.bookings.append({'issue_id': -1, 
                             'spent_on': date.today(),
                             'hours': 0., 
                             'description': '',
                             'comments': ''})
        self.edit(-1)

    def edit(self, entry=None):
        if entry is None:
            entry = int(raw_input('Edit Entry No.? '))
        while entry < 0 - len(self.bookings) or entry >= len(self.bookings):
            print('No entry with index %d!' % entry)
            entry = int(raw_input('Edit Entry No.? '))
            if not entry:
                return
        print('description: ' + self.bookings[entry]['description'])
        for key in bookings[entry]:
            if key == 'description':
                continue
            success = False
            while not success:
                newval = raw_input('%s [%s]: ' % (key, self.bookings[entry][key]))
                if newval:
                    if isinstance(self.bookings[entry][key], date):
                        try:
                            newval = date(*(map(lambda x: int(x), newval.split('-'))))
                            success = True
                        except:
                            print('ERROR: Could not convert to date: ' + newval)
                            success = False
                    else:
                        valtype = type(self.bookings[entry][key])
                        try:
                            newval = valtype(newval)
                            success = True
                        except:
                            print('ERROR: Could not convert to %s: %s' % (valtype, newval))
                            success = False
                    if success:
                        self.bookings[entry][key] = newval
                else:
                    success = True

    def sum(self):
        if len(self.bookings) == 0:
            return 0.
        return reduce(lambda x,y: x+y, map(lambda x: x['hours'], self.bookings))

if __name__ == "__main__":
    cfgfile = os.path.join(os.path.dirname(os.path.abspath(__file__)),
            'octodon.cfg')
    sessionfile = os.path.join(os.path.dirname(os.path.abspath(__file__)),
            '.octodon_session_timelog')
    config = SafeConfigParser()
    if not os.path.exists(cfgfile):
        if not os.path.exists('octodon.cfg'):
            print('No config file found! Please create %s' % cfgfile)
            sys.exit()
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

    parser = argparse.ArgumentParser(description='Extract time tracking data '\
        'from hamster and book it to redmine')
    parser.add_argument('--date', type=str, 
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
        repos = [r for r in config.get('git', 'repos').split('\n') if r.strip()]
        loginfo = get_loginfo_git(date=spent_on, author=author, repos=repos,
                mergewith=loginfo)

    if os.path.exists(sessionfile):
        continue_session = raw_input('Continue existing session? [Y/n] ')
        if not continue_session.lower() == 'n':
            bookings = read_from_file(sessionfile)
        else:
            bookings = get_timeinfo(date=spent_on, loginfo=loginfo)
        os.remove(sessionfile)
    else:
        bookings = get_timeinfo(date=spent_on, loginfo=loginfo)

    finished = False
    while not finished:
        tempfile = write_to_file(bookings, spent_on)
        subprocess.check_call(
            [editor + ' ' + tempfile.name], shell=True)
        bookings = read_from_file(tempfile.name)
        tempfile.close()

        BookingsMenu(bookings).print_all()
        book_now = raw_input('Book now? [y/N] ')

        if bookings and book_now.lower() == 'y':
            write_to_file(bookings, spent_on, file_name=sessionfile)
            book_time(TimeEntry, bookings)
            os.remove(sessionfile)
            finished = True
        else:
            edit_again = raw_input('Edit again? [Y/n] ')
            if edit_again.lower() == 'n':
                write_to_file(bookings, spent_on, file_name=sessionfile)
                finished = True
