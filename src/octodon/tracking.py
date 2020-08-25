import os
import socket
import sys

# from octodon.exceptions import ConnectionError
from octodon.exceptions import NotFound
from octodon.utils import get_data_home


class Tracking(object):
    def __init__(
        self, redmine=None, jira=None, harvest=None, project_history_file=None,
    ):
        self.redmine = redmine
        self.jira = jira
        self.harvest = harvest
        self.trackers = list(filter(None, [self.jira, self.redmine]))
        self._projects = []
        self._issue_to_project = {}
        if project_history_file is None:
            self.project_history_file = os.path.join(
                get_data_home(), "octodon-projects.pickle"
            )
        else:
            self.project_history_file = project_history_file

    def get_issue_title(self, issue_id):
        issue_title = ""
        for tracker in self.trackers:
            issue = None
            try:
                issue = tracker.get_issue(issue_id)
            except NotFound as nf:
                print(
                    u"Could not find issue {0}: {1} - {2}".format(
                        str(issue_id), nf.status_code, nf.text
                    ),
                    file=sys.stderr,
                )
            except (ConnectionError, socket.error):
                print(
                    "Could not find issue " + str(issue_id), file=sys.stderr,
                )
            if issue is None:
                continue
            issue_title = issue.get_title()
            if issue_title:
                break
        return issue_title

    def get_booking_target(self, entry):
        harvest_projects = [project[u"code"] for project in self.harvest.projects]

        issue_no = entry["issue_id"]
        issue = None
        project = ""
        contracts = []
        if issue_no is not None:
            for tracker in self.trackers:
                try:
                    issue = tracker.get_issue(issue_no)
                except NotFound as nf:
                    print(
                        u"Could not find issue {0}: {1} - {2}".format(
                            str(issue_no), nf.status_code, nf.text
                        ),
                        file=sys.stderr,
                    )
                except (ConnectionError, socket.error):
                    print("Could not find issue " + str(issue_no), file=sys.stderr)
                if issue:
                    break

        if issue is not None:
            try:
                project = issue.get_project()
            except Exception as e:
                print(
                    "Could not get project identifier: {0}; {1}".format(
                        issue["project"]["name"], e
                    ),
                    file=sys.stderr,
                )
                project = ""
            contracts = issue.get_contracts()

        for tag in entry["tags"]:
            if tag in harvest_projects:
                project = tag
        if entry["category"] in harvest_projects:
            project = entry["category"]

        tracker = None
        if issue_no:
            tracker = issue and issue.get_tracker()

        harvest_project = self.harvest.guess_project(
            harvest_projects,
            project=project,
            tracker=tracker,
            contracts=contracts,
            description=entry["description"],
        )
        if not harvest_project:
            harvest_project = self.harvest.recall_project(
                issue_no, default=harvest_project
            )

        if not harvest_project and (project or tracker or contracts):
            print(
                "No project match for {0}, {1}, {2}, {3}".format(
                    project, tracker, contracts, entry["description"]
                ),
                file=sys.stderr,
            )
        task = self.harvest.guess_task(
            project=project, description=entry["description"]
        )
        return harvest_project, task
