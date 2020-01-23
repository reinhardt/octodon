from __future__ import absolute_import
import os
import argparse
import re
import subprocess
import sys
from datetime import datetime, timedelta
from cmd import Cmd
from octodon.tracking import Tracking
from octodon.utils import clean_up_bookings
from octodon.utils import format_spent_time
from octodon.utils import get_time_sum
from octodon.utils import get_data_home
from octodon.utils import make_row
from octodon.utils import make_table
from octodon.utils import read_from_file
from octodon.utils import write_to_file
from octodon.version_control import GitLog
from octodon.version_control import SvnLog
from octodon.version_control import VCSLog
from six.moves.configparser import ConfigParser


class Octodon(Cmd):
    def __init__(self, config, spent_on, new_session=False, *args):
        Cmd.__init__(self, *args)
        self.config = config

        if config.get("main", "source") == "hamster":
            from octodon.hamster import HamsterTimeLog
            self.time_log = HamsterTimeLog()
        elif config.get("main", "source") == "orgmode":
            from octodon.orgmode import OrgModeTimeLog
            filename = config.get("orgmode", "filename")
            self.time_log = OrgModeTimeLog(filename)
        elif config.get("main", "source") == "plaintext":
            from octodon.clockwork import ClockWorkTimeLog
            log_path = config.get("plaintext", "log_path")
            self.time_log = ClockWorkTimeLog(log_path=log_path)

        self.editor = config.get("main", "editor")

        self.redmine = None
        if config.has_section("redmine"):
            from octodon.redmine import Redmine
            if config.has_option("redmine", "password_command"):
                cmd = config.get("redmine", "password_command")
                password = (
                    subprocess.check_output(cmd.split(" ")).strip().decode("utf-8")
                )
                config.set("redmine", "pass", password)
            self.redmine = Redmine(
                config.get("redmine", "url"),
                config.get("redmine", "user"),
                config.get("redmine", "pass"),
            )

        self.jira = None
        if config.has_section("jira"):
            from octodon.jira import Jira
            if config.has_option("jira", "password_command"):
                cmd = config.get("jira", "password_command")
                password = (
                    subprocess.check_output(cmd.split(" ")).strip().decode("utf-8")
                )
                config.set("jira", "pass", password)
            self.jira = Jira(
                config.get("jira", "url"),
                config.get("jira", "user"),
                config.get("jira", "pass"),
            )

        vcs_class = {"git": GitLog, "svn": SvnLog}

        self.vcs_list = []
        for vcs in self.config.get("main", "vcs").split("\n"):
            if not vcs:
                continue
            if not self.config.has_section(vcs):
                continue
            author = None
            repos = []
            if self.config.has_option(vcs, "author"):
                author = self.config.get(vcs, "author")
            if self.config.has_option(vcs, "repos"):
                repos = [
                    r for r in self.config.get(vcs, "repos").split("\n") if r.strip()
                ]
            if self.config.has_option(vcs, "executable"):
                exe = self.config.get(vcs, "executable")
            else:
                exe = "/usr/bin/env " + vcs
            self.vcs_list.append(
                {
                    "name": vcs,
                    "class": vcs_class.get(vcs, VCSLog),
                    "author": author,
                    "repos": repos,
                    "exe": exe,
                }
            )

        if config.has_section("harvest"):
            from harvest import Harvest

            if config.has_option("harvest", "password_command"):
                cmd = config.get("harvest", "password_command")
                password = (
                    subprocess.check_output(cmd.split(" ")).strip().decode("utf-8")
                )
                config.set("harvest", "pass", password)
            harvest = Harvest(
                config.get("harvest", "url"),
                config.get("harvest", "user"),
                config.get("harvest", "pass"),
            )
        else:
            harvest = None

        if self.config.has_option("main", "project-mapping"):
            project_mapping = self.config.get("main", "project-mapping")
            project_mapping = project_mapping.split("\n")
            project_mapping = dict(
                [pair.split(" ") for pair in project_mapping if pair]
            )
        else:
            project_mapping = {}

        if self.config.has_option("main", "task-mapping"):
            task_mapping = self.config.get("main", "task-mapping")
            task_mapping = task_mapping.split("\n")
            task_mapping = dict([pair.split(" ", 1) for pair in task_mapping if pair])
        else:
            task_mapping = {}

        self.tracking = Tracking(
            redmine=self.redmine,
            jira=self.jira,
            harvest=harvest,
            project_mapping=project_mapping,
            task_mapping=task_mapping,
        )

        self.prompt = "octodon> "
        self.sessionfile = os.path.join(
            get_data_home(), "octodon_session_timelog.rst"
        )
        activities = self.redmine and self.redmine.activities or []
        if os.path.exists(self.sessionfile):
            if not new_session:
                prompt = "Continue existing session? [Y/n] "
                if sys.version_info[0] == 2:
                    answer = raw_input(prompt)
                else:
                    answer = input(prompt)
                new_session = answer.lower() == "n"
            if not new_session:
                spent_on, self.bookings = read_from_file(
                    self.sessionfile, activities=activities
                )
            else:
                spent_on, self.bookings = self.get_bookings(spent_on)
                self.bookings = clean_up_bookings(self.bookings)
        else:
            spent_on, self.bookings = self.get_bookings(spent_on)
            self.bookings = clean_up_bookings(self.bookings)
        self.spent_on = spent_on

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
            vcslog = vcs_config["class"](exe=vcs_config["exe"])
            try:
                loginfo = vcslog.get_loginfo(
                    date=spent_on,
                    author=vcs_config["author"],
                    repos=vcs_config["repos"],
                    mergewith=loginfo,
                )
            except NotImplemented:
                print("Unrecognized vcs: %s" % vcs_config["name"], file=sys.stderr)

        activities = self.redmine and self.redmine.activities or []
        bookings = self.time_log.get_timeinfo(
            date=spent_on, loginfo=loginfo, activities=activities
        )
        if self.tracking.harvest is not None:
            for entry in bookings:
                project, task = self.tracking.get_harvest_target(entry)
                entry["project"] = project
                entry["activity"] = task
        return bookings

    def check_issue_and_comment(self, bookings):
        no_issue_or_comment = [
            entry
            for entry in bookings
            if entry["issue_id"] is None or len(entry["comments"]) <= 0
        ]
        activities = self.redmine and self.redmine.activities or []
        if len(no_issue_or_comment) > 0:
            rows = [make_row(entry, activities) for entry in no_issue_or_comment]
            print(
                "Warning: No issue id and/or comments for the following entries:"
                "\n{0}".format(make_table(rows)),
                file=sys.stderr,
            )

    def print_summary(self, bookings):
        total_time = get_time_sum(bookings)
        print("total hours:%s" % format_spent_time(total_time))

    def do_summary(self, *args):
        self.print_summary(self.bookings)

    def do_total(self, *args):
        print(format_spent_time(get_time_sum(self.bookings)))

    def do_edit(self, *args):
        """ Edit the current time booking values in an editor. """
        activities = self.redmine and self.redmine.activities or []
        self.sessionfile = write_to_file(
            self.bookings, self.spent_on, activities, file_name=self.sessionfile
        )
        subprocess.check_call([self.editor + " " + self.sessionfile], shell=True)
        activities = self.redmine and self.redmine.activities or []
        _, self.bookings = read_from_file(self.sessionfile, activities)
        self.check_issue_and_comment(self.bookings)

    def do_redmine(self, *args):
        """ Write current bookings to redmine. """
        try:
            self.redmine.book_redmine(self.bookings)
        except Exception as e:
            print(
                "Error while booking - comments too long? Error was: "
                "%s: %s" % (e.__class__.__name__, e),
                file=sys.stderr,
            )

    def do_jira(self, *args):
        """ Write current bookings to jira. """
        try:
            self.jira.book_jira(self.bookings)
        except Exception as e:
            print(
                "Error while booking - " "%s: %s" % (e.__class__.__name__, e),
                file=sys.stderr,
                )

    def do_harvest(self, *args):
        """ Write current bookings to harvest. """
        try:
            self.tracking.book_harvest(self.bookings)
        except Exception as e:
            print(
                "Error while booking - " "%s: %s" % (e.__class__.__name__, e),
                file=sys.stderr,
            )

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
        spent_on, bookings = self.get_bookings(self.spent_on)
        bookings = clean_up_bookings(bookings)
        import ipdb

        ipdb.set_trace()

    def do_exit(self, line):
        return True

    def do_quit(self, line):
        return True

    def do_EOF(self, line):
        return True


def get_config(cfgfile=None):
    config = ConfigParser()
    cfgfiles = []
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    config_home = os.path.join(config_home, "octodon")

    if cfgfile:
        cfgfiles.append(cfgfile)
    cfgfiles.append(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "defaults.cfg")
    )
    cfgfiles.append(
        os.path.expanduser("~/.octodon.cfg")
    )
    cfgfiles.append(
        os.path.join(config_home, "octodon.cfg")
    )
    config.read(cfgfiles)

    editor = os.environ.get("EDITOR")
    if editor:
        config.set("main", "editor", editor)

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
    parser.add_argument(
        "command",
        metavar="command",
        type=str,
        nargs="?",
        help="command to execute. Start interactive mode if ommitted",
    )

    args = parser.parse_args()

    cfgfile = None
    if args.config_file:
        cfgfile = args.config_file
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
    if args.command:
        octodon.onecmd(args.command)
    else:
        octodon.cmdloop()
