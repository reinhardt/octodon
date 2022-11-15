# from __future__ import absolute_import
from cmd import Cmd
from contextlib import contextmanager
from datetime import datetime
from datetime import timedelta
from octodon.tracking import Tracking
from octodon.utils import clean_up_bookings
from octodon.utils import format_spent_time
from octodon.utils import get_data_home
from octodon.utils import get_time_sum
from octodon.utils import make_row
from octodon.utils import make_table
from octodon.utils import read_from_file
from octodon.utils import write_to_file
from octodon.version_control import GitLog
from octodon.version_control import SvnLog
from octodon.version_control import VCSLog
from six.moves.configparser import ConfigParser

import argparse
import os
import pystache
import re
import subprocess
import sys


class Octodon(Cmd):
    def __init__(self, config, spent_on, new_session=False, *args):
        Cmd.__init__(self, *args)
        self.config = config

        ticket_patterns = []
        for tracker in self.trackers:
            ticket_patterns.append(tracker.ticket_pattern)

        self.time_log = get_time_log(config, ticket_patterns)

        self.editor = config.get("main", "editor")

        self.list_item_template = "- {comments}"
        if config.has_option("main", "list-item-template"):
            self.list_item_template = config.get("main", "list-item-template")

        self.list_template = None
        if config.has_option("main", "list-template-file"):
            list_template_file = os.path.expanduser(
                config.get("main", "list-template-file")
            )
            with open(list_template_file, "r") as tmpl_file:
                self.list_template = pystache.parse(tmpl_file.read())

        self.list_file_name = None
        if config.has_option("main", "list-file"):
            self.list_file_name = os.path.expanduser(config.get("main", "list-file"))

        self.prompt = "octodon> "
        self.sessionfile = os.path.join(get_data_home(), "octodon_session_timelog.rst")
        self.is_new_session = True
        if os.path.exists(self.sessionfile):
            if not new_session:
                prompt = "Continue existing session? [Y/n] "
                if sys.version_info[0] == 2:
                    answer = raw_input(prompt)
                else:
                    answer = input(prompt)
                self.is_new_session = answer.lower() == "n"
        self.spent_on = spent_on

    @property
    def vcs_list(self):
        vcs_list = getattr(self, "_vcs_list", None)
        if vcs_list is None:
            vcs_list = []
            vcs_class = {"git": GitLog, "svn": SvnLog}
            ticket_patterns = []
            for tracker in self.trackers:
                ticket_patterns.append(tracker.ticket_pattern)

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
                        r
                        for r in self.config.get(vcs, "repos").split("\n")
                        if r.strip()
                    ]
                if self.config.has_option(vcs, "executable"):
                    exe = self.config.get(vcs, "executable")
                else:
                    exe = "/usr/bin/env " + vcs
                if vcs in vcs_class:
                    vcs_list.append(
                        vcs_class.get(vcs)(
                            exe=exe,
                            author=author,
                            repos=repos,
                            patterns=ticket_patterns,
                        )
                    )
                else:
                    print("Unrecognized vcs: %s" % vcs, file=sys.stderr)
        return vcs_list

    @property
    def jira(self):
        jira = getattr(self, "_jira", None)
        if jira is None and self.config.has_section("jira"):
            try:
                from octodon.jira import Jira
            except ImportError:
                return None

            if self.config.has_option("jira", "password_command"):
                cmd = self.config.get("jira", "password_command")
                password = (
                    subprocess.check_output(cmd.split(" ")).strip().decode("utf-8")
                )
                self.config.set("jira", "pass", password)
            self._jira = jira = Jira(
                self.config.get("jira", "url"),
                self.config.get("jira", "user"),
                self.config.get("jira", "pass"),
            )
        return jira

    @property
    def github(self):
        github = getattr(self, "_github", None)
        if github is None and self.config.has_section("github"):
            try:
                from octodon.github import Github
            except ImportError:
                return None

            if self.config.has_option("github", "token_command"):
                cmd = self.config.get("github", "token_command")
                token = subprocess.check_output(cmd.split(" ")).strip().decode("utf-8")
                self.config.set("github", "token", token)
            self._github = github = Github(
                self.config.get("github", "token"),
                self.config.get("github", "organization"),
                int(self.config.get("github", "project_num")),
            )
        return github

    @property
    def redmine(self):
        redmine = getattr(self, "_redmine", None)
        if redmine is None and self.config.has_section("redmine"):
            try:
                from octodon.redmine import Redmine
            except ImportError:
                return None

            if self.config.has_option("redmine", "password_command"):
                cmd = self.config.get("redmine", "password_command")
                password = (
                    subprocess.check_output(cmd.split(" ")).strip().decode("utf-8")
                )
                self.config.set("redmine", "pass", password)
            self._redmine = redmine = Redmine(
                self.config.get("redmine", "url"),
                self.config.get("redmine", "user"),
                self.config.get("redmine", "pass"),
            )
        return redmine

    @property
    def trackers(self):
        trackers = getattr(self, "_trackers", None)
        if trackers is None:
            self._trackers = trackers = list(
                filter(None, [self.jira, self.redmine, self.github])
            )
        return trackers or []

    @property
    def harvest(self):
        harvest = getattr(self, "_harvest", None)
        if harvest is None and self.config.has_section("harvest"):
            try:
                from octodon.harvest import Harvest
            except ImportError:
                return None

            if self.config.has_option("harvest", "token_command"):
                cmd = self.config.get("harvest", "token_command")
                token = subprocess.check_output(cmd.split(" ")).strip().decode("utf-8")
                self.config.set("harvest", "personal_token", token)

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
                task_mapping = dict(
                    [pair.split(" ", 1) for pair in task_mapping if pair]
                )
            else:
                task_mapping = {}

            self._harvest = harvest = Harvest(
                self.config.get("harvest", "url"),
                self.config.get("harvest", "account_id"),
                self.config.get("harvest", "personal_token"),
                project_mapping=project_mapping,
                task_mapping=task_mapping,
                default_task=self.config.get("main", "default-task"),
            )
        return harvest

    @property
    def tracking(self):
        tracking = getattr(self, "_tracking", None)
        if tracking is None:
            self._tracking = tracking = Tracking(
                trackers=self.trackers,
                harvest=self.harvest,
            )
        return tracking

    @property
    def activities(self):
        if getattr(self, "_activities", None) is None:
            self._activities = []
            if self.redmine:
                self._activities.extend(self.redmine.activities)
            if self.harvest:
                self._activities.extend(self.harvest.activities)
        return self._activities

    @property
    def bookings(self):
        bookings = getattr(self, "_bookings", None)
        if bookings is None:
            if not self.is_new_session:
                self.spent_on, bookings = read_from_file(
                    self.sessionfile, activities=self.activities
                )
            else:
                self.spent_on, bookings = self.get_bookings(self.spent_on)
                bookings = clean_up_bookings(bookings)

            for entry in bookings:
                if entry["issue_id"] is not None:
                    entry["issue_title"] = self.tracking.get_issue_title(
                        entry["issue_id"]
                    )
                else:
                    entry["issue_title"] = ""
            self._bookings = bookings
        return bookings

    def clear_bookings(self):
        self.is_new_session = False
        self._bookings = None

    def get_bookings(self, spent_on, search_back=4):
        bookings = None
        for i in range(search_back):
            bookings = self._get_bookings(spent_on - timedelta(i))
            if bookings:
                break
        return spent_on - timedelta(i), bookings

    def _get_bookings(self, spent_on):
        loginfo = {}
        for vcs in self.vcs_list:
            loginfo = vcs.get_loginfo(
                date=spent_on,
                mergewith=loginfo,
            )

        bookings = self.time_log.get_timeinfo(
            date=spent_on, loginfo=loginfo, activities=self.activities
        )
        for entry in bookings:
            project, task = self.tracking.get_booking_target(entry)
            entry["project"] = project
            entry["activity"] = task

        return bookings

    def check_issue_and_comment(self, bookings):
        no_issue_or_comment = [
            entry
            for entry in bookings
            if entry["issue_id"] is None or len(entry["comments"]) <= 0
        ]
        if len(no_issue_or_comment) > 0:
            rows = [make_row(entry, self.activities) for entry in no_issue_or_comment]
            print(
                "Warning: No issue id and/or comments for the following entries:"
                "\n{0}".format(make_table(rows)),
                file=sys.stderr,
            )
            return False
        return True

    def print_summary(self, bookings):
        total_time = get_time_sum(bookings)
        print("total hours:%s" % format_spent_time(total_time))

    def do_summary(self, *args):
        self.print_summary(self.bookings)

    def do_total(self, *args):
        bookings = self.time_log.get_timeinfo(date=self.spent_on)
        print(format_spent_time(get_time_sum(bookings)))

    def do_list(self, arg):
        """Print the current bookings or save them to a file.
        Subcommands: show \tsave
        """
        args = filter(None, arg.split(" "))
        subcommand = next(args, "show")
        filename = next(args, None)

        if subcommand not in ["show", "save"]:
            print("Unknown subcommand {}".format(subcommand))
            return
        if subcommand == "save":
            if filename:
                filename = os.path.expanduser(filename)
            else:
                filename = self.list_file_name
            if not filename:
                print("Error: File name is required")
                return
        elif subcommand == "show":
            if filename:
                print("Subcommand '{}' takes no arguments".format(subcommand))
                return
            filename = "-"

        try:
            with self.prepare_outfile(filename) as outfile:
                if self.list_template:
                    print(self.get_templated_list(self.bookings), file=outfile)
                else:
                    print(self.get_simple_list(self.bookings), file=outfile)
        except FileNotFoundError as fnfe:
            print(
                "Could not open {0}: {1}".format(filename, fnfe),
                file=sys.stderr,
            )
            return

        if filename != "-":
            print("Printed to {}".format(filename), file=sys.stderr)

    @contextmanager
    def prepare_outfile(self, filename):
        outfile = None
        try:
            if filename == "-":
                outfile = sys.stdout
            else:
                outfile = open(filename, "w")
            yield outfile
        finally:
            if filename != "-" and outfile is not None:
                outfile.close()

    def get_simple_list(self, bookings):
        try:
            for entry in bookings:
                return self.list_item_template.format(**entry)
        except Exception as e:
            print(
                "Error when using template ({})! {}: {}".format(
                    self.list_item_template, e.__class__.__name__, e
                ),
                file=sys.stderr,
            )

    def get_templated_list(self, bookings):
        renderer = pystache.Renderer()
        return renderer.render(self.list_template, {"bookings": self.bookings})

    def do_edit(self, *args):
        """Edit the current time booking values in an editor."""
        self.sessionfile = write_to_file(
            self.bookings, self.spent_on, self.activities, file_name=self.sessionfile
        )
        retval = subprocess.run([self.editor + " " + self.sessionfile], shell=True)
        if retval.returncode:
            print("Warning: The editor reported a problem ({})".format(retval))
        self.clear_bookings()
        if not self.check_issue_and_comment(self.bookings):
            self.cmdqueue.clear()

    def do_redmine(self, *args):
        """Write current bookings to redmine."""
        try:
            self.redmine.book_time(self.bookings)
        except Exception as e:
            print(
                "Error while booking - comments too long? Error was: "
                "%s: %s" % (e.__class__.__name__, e),
                file=sys.stderr,
            )

    def do_jira(self, *args):
        """Write current bookings to jira."""
        try:
            self.jira.book_time(self.bookings)
        except Exception as e:
            print(
                "Error while booking - " "%s: %s" % (e.__class__.__name__, e),
                file=sys.stderr,
            )

    def do_harvest(self, *args):
        """Write current bookings to harvest."""
        try:
            self.harvest.book_time(self.bookings)
        except Exception as e:
            print(
                "Error while booking - " "%s: %s" % (e.__class__.__name__, e),
                file=sys.stderr,
            )

    def do_book(self, *args):
        """Write current bookings to all configured targets."""
        if self.redmine:
            self.do_redmine()
        if self.jira:
            self.do_jira()
        self.do_harvest()

    def do_flush(self, *args):
        """Executes summary, book, list save in this order"""
        self.cmdqueue.extend(["summary", "book", "list save"])

    def do_fetch(self, *args):
        """EXPERIMENTAL. Freshly fetch bookings from source."""
        old_bookings = self.bookings[:]
        self.spent_on, bookings = self.get_bookings(self.spent_on)
        bookings = clean_up_bookings(bookings)
        import pdb

        pdb.set_trace()

    def do_exit(self, line):
        if os.path.exists(self.sessionfile):
            os.remove(self.sessionfile)
        return True

    def do_quit(self, line):
        if os.path.exists(self.sessionfile):
            os.remove(self.sessionfile)
        return True

    def do_EOF(self, line):
        if os.path.exists(self.sessionfile):
            os.remove(self.sessionfile)
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
    cfgfiles.append(os.path.expanduser("~/.octodon.cfg"))
    cfgfiles.append(os.path.join(config_home, "octodon.cfg"))
    config.read(cfgfiles)

    editor = os.environ.get("EDITOR")
    if editor:
        config.set("main", "editor", editor)

    return config


def get_time_log(config, ticket_patterns=[]):
    time_log = None
    if not config.has_option("main", "source"):
        return None
    if config.get("main", "source") == "hamster":
        from octodon.hamster import HamsterTimeLog

        time_log = HamsterTimeLog(ticket_patterns=ticket_patterns)
    elif config.get("main", "source") == "orgmode":
        from octodon.orgmode import OrgModeTimeLog

        filename = config.get("orgmode", "filename")
        time_log = OrgModeTimeLog(filename, ticket_patterns=ticket_patterns)
    elif config.get("main", "source") == "plaintext":
        from octodon.clockwork import ClockWorkTimeLog

        log_path = config.get("plaintext", "log_path")
        time_log = ClockWorkTimeLog(ticket_patterns=ticket_patterns, log_path=log_path)
    return time_log


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

    if args.command == "total":
        time_log = get_time_log(config)
        bookings = ()
        if time_log:
            bookings = time_log.get_timeinfo(date=spent_on)
        print(format_spent_time(get_time_sum(bookings)))
    elif args.command and args.command != "shell":
        octodon = Octodon(config, spent_on, new_session=True)
        octodon.onecmd(args.command)
    else:
        octodon = Octodon(config, spent_on, new_session=args.new_session)
        if args.command != "shell":
            octodon.cmdqueue.extend(["edit"])
        octodon.cmdloop()
