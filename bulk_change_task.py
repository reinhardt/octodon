import argparse
import os
import re
from datetime import datetime
from datetime import timedelta
from harvest import Harvest
from octodon import get_config
from pprint import pprint


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Change task on multiple harvest entries')
    parser.add_argument(
        '--search', '-s',
        type=str,
        help='search term')
    parser.add_argument(
        '--new-task', '-n',
        type=str,
        help='search term')
    parser.add_argument(
        '--date', '-d',
        type=str,
        help='the earliest date to search back to, in format YYYYMMDD'
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
    if args.date:
        if args.date == 'today':
            min_date = today
        elif re.match(r'[+-][0-9]*$', args.date):
            min_date = today + timedelta(int(args.date))
        elif re.match(r'[0-9]{8}$', args.date):
            min_date = datetime.strptime(args.date, '%Y%m%d')
        else:
            print('error: unrecognized date format: {0}'.format(args.date))
            exit(1)
        interval = (today - min_date).days
    else:
        interval = 60

    maxyear = now.year
    maxday = int(now.strftime('%j'))
    searchterm = args.search

    harvest = Harvest(
        config.get('harvest', 'url'),
        config.get('harvest', 'user'),
        config.get('harvest', 'pass'))

    entries = reduce(lambda l1, l2: l1 + l2,
                     [harvest.get_day(
                         day_of_the_year=day, year=maxyear)['day_entries']
                      for day in xrange(maxday - interval, maxday)])
    matches = filter(lambda entry: searchterm in entry['notes'], entries)
    total_hours = sum([entry['hours'] for entry in matches])
    pprint(matches)
    print('Total hours: ' + str(total_hours))

    if args.new_task:
        old_tasks = set([entry['task'] for entry in matches])
        do_change = raw_input('Booked tasks: {0}. Change task on all entries '
                              'to {1}? [y/N] '.format(
                                  ', '.join(old_tasks), args.new_task))
        if do_change.lower() != 'y':
            exit(0)
        print('Not implemented yet :-(')
        #for entry in matches:
