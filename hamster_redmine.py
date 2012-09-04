#!/usr/bin/env python
from datetime import datetime, date
from hamster.client import Storage
from ConfigParser import SafeConfigParser
import argparse
import re
import sys,os
from pyactiveresource.activeresource import ActiveResource

class Issue(ActiveResource):
    _site = None
    _user = None
    _password = None

# tt1 = TimeEntry(dict(issue_id=4984, spent_on='2012-06-18', hours=.75, activity_id=9, comments='re-ran buildout'))
# tt1.save()

ticket_pattern = re.compile('#([0-9]*)')
def get_timeinfo(date=datetime.now(), baseurl=''):
    sto = Storage()
    facts = sto.get_facts(date)
    #facts = sto.get_facts(datetime(2012,3,1))
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
                         'comments': ''})
    return bookings

def book_time(TimeEntry, bookings):
    for entry in bookings:
        rm_entry = entry.copy()
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
            'hamster_redmine.cfg')
    config = SafeConfigParser()
    if not os.path.exists(cfgfile):
        if not os.path.exists('hamster_redmine.cfg'):
            print('No config file found! Please create %s' % cfgfile)
            sys.exit()
        config.read('hamster_redmine.cfg')
    config.read(cfgfile)

    class TimeEntry(ActiveResource):
        _site = config.get('redmine', 'url')
        _user = config.get('redmine', 'user')
        _password = config.get('redmine', 'pass')

    parser = argparse.ArgumentParser(description='Extract time tracking data '\
        'from hamster and book it to redmine')
    parser.add_argument('--date', type=str, 
        help='the date for which to extract tracking data, in format YYYYMMDD')
    args = parser.parse_args()
    if args.date:
        bookings = get_timeinfo(datetime.strptime(args.date, '%Y%m%d'))
    else:
        bookings = get_timeinfo()

    menu = BookingsMenu(bookings)
    new_bookings = menu()

    if new_bookings:
        #import pdb; pdb.set_trace()
        book_time(TimeEntry, new_bookings)
