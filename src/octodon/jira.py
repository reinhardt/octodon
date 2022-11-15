# from __future__ import absolute_import
from datetime import datetime
from jira import JIRA
from jira import JIRAError

# from octodon.exceptions import ConnectionError
from octodon.exceptions import NotFound
from octodon.issue import Issue

import re
import sys


class JiraIssue(Issue):
    def __init__(self, issue):
        self.issue = issue

    def get_tracker(self):
        return self.issue.fields.issuetype.name

    def get_title(self):
        return self.issue.fields.summary

    def get_project(self):
        return self.issue.fields.project.key

    def get_contracts(self):
        contracts_field = self.issue.fields.customfield_10902
        return (
            [contracts_field.child.value] if hasattr(contracts_field, "child") else []
        )


class Jira(object):
    ticket_pattern = re.compile("#?([A-Z]+-[0-9]+)")

    def __init__(self, url, user, password):
        self.url = url
        self.user = user
        self.password = password

    @property
    def jira(self):
        conn = getattr(self, "_connection", None)
        if conn is None:
            self._connection = conn = JIRA(self.url, auth=(self.user, self.password))
        return conn

    def get_issue(self, issue_id):
        if not self.ticket_pattern.match(issue_id):
            return None
        try:
            return JiraIssue(self.jira.issue(issue_id))
        except JIRAError as je:
            raise NotFound(status_code=je.status_code, text=je.text)

    def book_time(self, bookings):
        for entry in bookings:
            if not self.ticket_pattern.match(entry["issue_id"]):
                continue
            rm_entry = entry.copy()

            rm_entry["hours"] = rm_entry["time"] / 60.0
            del rm_entry["time"]

            if "description" in rm_entry:
                del rm_entry["description"]
            if "activity" in rm_entry:
                del rm_entry["activity"]

            try:
                self.jira.add_worklog(
                    issue=entry["issue_id"],
                    timeSpent=entry["time"],
                    started=datetime.strptime(entry["spent_on"], "%Y-%m-%d"),
                    comment=entry["comments"],
                )
            except JIRAError as je:
                print(
                    "{0}: {1} ({2})".format(
                        je.status_code, je.text, rm_entry["comments"]
                    ),
                    file=sys.stderr,
                )
