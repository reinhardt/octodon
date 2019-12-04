from __future__ import absolute_import
from datetime import datetime
from jira import JIRA
from jira import JIRAError
from octodon.tracking import ticket_pattern_jira


class Jira(object):
    def __init__(self, url, user, password):
        self.jira = JIRA(url, auth=(user, password))

    def book_jira(self, bookings):
        for entry in bookings:
            if not ticket_pattern_jira.match(entry["issue_id"]):
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
                    u"{0}: {1} ({2})".format(
                        je.status_code, je.text, rm_entry["comments"]
                    )
                )
