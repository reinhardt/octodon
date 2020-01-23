import re
import sys
from octodon.exceptions import NotFound
from octodon.utils import get_default_activity
from pyactiveresource.activeresource import ActiveResource
from pyactiveresource import connection

ticket_pattern_redmine = re.compile("#?([0-9]+)")


class Redmine(object):
    def __init__(self, url, user, password):
        class RedmineResource(ActiveResource):
            _site = url
            _user = user
            _password = password

        class TimeEntry(RedmineResource):
            pass

        class Enumerations(RedmineResource):
            pass

        class Issue(RedmineResource):
            pass

        class Projects(RedmineResource):
            pass

        self.TimeEntry = TimeEntry
        self.Enumerations = Enumerations
        self.Issue = Issue
        self.Projects = Projects

        try:
            self.activities = self.Enumerations.get("time_entry_activities")
        except connection.Error:
            print("Could not get redmine activities: Connection error", file=sys.stderr)
            self.activities = []

    def get_issue(self, issue_id):
        try:
            return self.Issue.get(int(issue_id))
        except (connection.ResourceNotFound, connection.Error):
            raise NotFound()

    def book_redmine(self, bookings):
        default_activity = get_default_activity(self.activities)
        for entry in bookings:
            if not ticket_pattern_redmine.match(entry["issue_id"]):
                continue
            if entry["issue_id"] is None:
                print(
                    "No valid issue id, skipping entry (%s)" % entry["description"],
                    file=sys.stderr,
                )
                continue
            rm_entry = entry.copy()

            activities_dict = dict([(act["name"], act) for act in self.activities])
            act = activities_dict.get(entry["activity"])
            rm_entry["activity_id"] = act and act["id"] or default_activity["id"]
            rm_entry["hours"] = rm_entry["time"] / 60.0
            del rm_entry["time"]

            if "description" in rm_entry:
                del rm_entry["description"]
            if "activity" in rm_entry:
                del rm_entry["activity"]

            rm_time_entry = self.TimeEntry(rm_entry)
            success = rm_time_entry.save()
            if not success:
                for field, msgs in rm_time_entry.errors.errors.items():
                    print(
                        u"{0}: {1} ({2})".format(
                            field, u",".join(msgs), rm_entry["comments"]
                        ),
                        file=sys.stderr,
                    )
