import argparse
import os
import re
from datetime import datetime
from datetime import timedelta
from harvest import Harvest
from octodon import get_config
from pprint import pprint
from functools import reduce


def harvest_date_range(startdate, enddate):
    currentdate = startdate
    while currentdate < enddate:
        year = currentdate.year
        day = int(currentdate.strftime('%j'))
        yield day, year
        currentdate = currentdate + timedelta(1)


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
    else:
        min_date = today - timedelta(60)

    searchterm = args.search

    harvest = Harvest(
        config.get('harvest', 'url'),
        config.get('harvest', 'user'),
        config.get('harvest', 'pass'))

    entries = reduce(lambda l1, l2: l1 + l2,
                     [harvest.get_day(
                         day_of_the_year=day, year=year)['day_entries']
                      for day, year in harvest_date_range(min_date, today)])
    matches = filter(lambda entry: searchterm in entry['notes'], entries)
    total_hours = sum([entry['hours'] for entry in matches])
    pprint(matches)
    print('Total hours: ' + str(total_hours))

    old_tasks = set([entry['task'] for entry in matches])
    print('Booked tasks: {0}.'.format(', '.join(old_tasks)))

    if args.new_task:
        new_task = args.new_task
    else:
        new_task = raw_input('Enter new task (blank for no change): ').strip()
    if not new_task:
        exit(0)

    do_change = raw_input(
        'Change task on {0} entries to {1}? [y/N] '.format(
            len(matches), new_task))
    if do_change.lower() != 'y':
        exit(0)
    for entry in matches:
        entry['task'] = new_task
        result = harvest.update(entry['id'], entry)
        if 'error' in result:
            print('Error booking entry {0}: {1}'.format(
                entry['id'], result['error'].get('message', 'No message')))
