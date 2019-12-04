import argparse
import re
import sys
import os
from datetime import datetime, timedelta
from octodon.cmd import Octodon
from six.moves.configparser import ConfigParser


def get_config(cfgfile):
    config = ConfigParser()
    default_cfgfile = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "defaults.cfg"
    )
    config.read([default_cfgfile])

    editor = os.environ.get("EDITOR")
    if editor:
        config.set("main", "editor", editor)

    if not os.path.exists(cfgfile):
        print(
            "Warning: config file {0} not found! Trying " "octodon.cfg".format(cfgfile)
        )
        if not os.path.exists("octodon.cfg"):
            print("No config file found! Please create %s" % cfgfile)
            sys.exit(1)
        config.read("octodon.cfg")
    config.read(cfgfile)
    return config


def main():
    parser = argparse.ArgumentParser(
        description="Extract time tracking data "
        "from hamster or emacs org mode and book it to redmine/jira/harvest"
    )
    parser.add_argument(
        "--date",
        type=str,
        help="the date for which to extract tracking data, in format YYYYMMDD"
        " or as an offset in days from today, e.g. -1 for yesterday",
    )
    parser.add_argument(
        "--config-file",
        "-c",
        type=str,
        help="the configuration file to use for this session",
    )
    parser.add_argument(
        "--new-session",
        "-n",
        action="store_true",
        help="discard any existing session and start a new one",
    )
    args = parser.parse_args()

    if args.config_file:
        cfgfile = args.config_file
    else:
        cfgfile = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "octodon.cfg"
        )
    config = get_config(cfgfile)

    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if now.hour >= 16:
        spent_on = today
    else:
        spent_on = today - timedelta(1)
    if args.date:
        if args.date == "today":
            spent_on = today
        elif re.match(r"[+-][0-9]*$", args.date):
            spent_on = today + timedelta(int(args.date))
        elif re.match(r"[0-9]{8}$", args.date):
            spent_on = datetime.strptime(args.date, "%Y%m%d")
        elif re.match(r"[0-9]{4}-[0-9]{2}-[0-9]{2}$", args.date):
            spent_on = datetime.strptime(args.date, "%Y-%m-%d")
        else:
            raise Exception("unrecognized date format: {0}".format(args.date))

    octodon = Octodon(config, spent_on, new_session=args.new_session)
    octodon.cmdloop()


if __name__ == "__main__":
    main()
