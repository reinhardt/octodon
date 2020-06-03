import os
import pickle
import socket
import sys

# from octodon.exceptions import ConnectionError
from octodon.exceptions import NotFound
from octodon.utils import get_data_home


class Tracking(object):
    def __init__(
        self,
        redmine=None,
        jira=None,
        harvest=None,
        project_mapping={},
        task_mapping={},
        project_history_file=None,
        default_task=None,
    ):
        self.redmine = redmine
        self.jira = jira
        self.harvest = harvest
        self.trackers = list(filter(None, [self.jira, self.redmine]))
        self.project_mapping = project_mapping
        self.task_mapping = task_mapping
        self._projects = []
        self._issue_to_project = {}
        if project_history_file is None:
            self.project_history_file = os.path.join(
                get_data_home(), "octodon-projects.pickle"
            )
        else:
            self.project_history_file = project_history_file
        self.default_task = default_task

    @property
    def projects(self):
        if not self._projects:
            harvest_data = {}
            try:
                harvest_data = self.harvest.get_day()
                self._projects = harvest_data["projects"]
            except Exception as e:
                print(
                    "Could not get harvest projects: {0}: {1}".format(
                        e.__class__.__name__, e
                    ),
                    file=sys.stderr,
                )
                if u"message" in harvest_data:
                    print(harvest_data[u"message"], file=sys.stderr)
                self._projects = []
        return self._projects

    def book_harvest(self, bookings):
        if not self.harvest:
            return
        projects_lookup = dict(
            [(project[u"code"], project) for project in self.projects]
        )
        for entry in bookings:
            project = projects_lookup[entry["project"]]
            project_id = project and project[u"id"] or -1
            tasks_lookup = dict([(task[u"name"], task) for task in project[u"tasks"]])
            task = tasks_lookup.get(entry["activity"])
            task_id = task and task[u"id"] or -1

            issue_title = ""
            if entry["issue_id"] is not None:
                for tracker in self.trackers:
                    issue = None
                    try:
                        issue = tracker.get_issue(entry["issue_id"])
                    except NotFound as nf:
                        print(
                            u"Could not find issue {0}: {1} - {2}".format(
                                str(entry["issue_id"]), nf.status_code, nf.text
                            ),
                            file=sys.stderr,
                        )
                    except (ConnectionError, socket.error):
                        print(
                            "Could not find issue " + str(entry["issue_id"]),
                            file=sys.stderr,
                        )
                    if issue is None:
                        continue
                    issue_title = issue.get_title()
                    if issue_title:
                        break

            issue_desc = ""
            if entry["issue_id"]:
                issue_desc = "[#{0}] {1}: ".format(str(entry["issue_id"]), issue_title)
            self.harvest.add(
                {
                    "notes": "{0}{1}".format(issue_desc, entry["comments"]),
                    "project_id": project_id,
                    "hours": str(entry["time"] / 60.0),
                    "task_id": task_id,
                    "spent_at": entry["spent_on"],
                }
            )
            self.remember_project(entry["issue_id"], project["code"])

    def _load_project_history(self):
        if not os.path.exists(self.project_history_file):
            self._issue_to_project = {}
        else:
            with open(self.project_history_file, "rb") as cache:
                self._issue_to_project = pickle.load(cache)

    def remember_project(self, issue_id, project_code):
        self._load_project_history()
        self._issue_to_project[issue_id] = project_code
        with open(self.project_history_file, "wb") as cache:
            pickle.dump(self._issue_to_project, cache)

    def recall_project(self, issue_id, default=None):
        self._load_project_history()
        return self._issue_to_project.get(issue_id, default)

    def guess_project(
        self, harvest_projects, project=None, tracker=None, contracts=[], description=""
    ):
        harvest_project = ""
        if project in self.project_mapping:
            harvest_project = self.project_mapping[project]
        elif project in harvest_projects:
            harvest_project = project
        if not harvest_project:
            for contract in contracts:
                if contract in harvest_projects:
                    harvest_project = contract
                    break
                part_matches = [
                    proj
                    for proj in harvest_projects
                    if contract.lower() in proj.lower()
                ]
                if part_matches:
                    harvest_project = part_matches[0]

        if not harvest_project and project:
            part_matches = [
                proj
                for proj in harvest_projects
                if project.lower().startswith(proj.lower())
                or proj.lower().startswith(project.lower())
            ]
            if part_matches:
                harvest_project = part_matches[0]
        return harvest_project

    def guess_task(self, project=None, description=""):
        task = self.default_task
        for key, value in self.task_mapping.items():
            if key.lower() in description.lower() or key.lower() in project.lower():
                task = value
                break
        return task

    def get_harvest_target(self, entry):
        harvest_projects = [project[u"code"] for project in self.projects]

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

        harvest_project = self.guess_project(
            harvest_projects,
            project=project,
            tracker=tracker,
            contracts=contracts,
            description=entry["description"],
        )
        if not harvest_project:
            harvest_project = self.recall_project(issue_no, default=harvest_project)

        if not harvest_project and (project or tracker or contracts):
            print(
                "No project match for {0}, {1}, {2}, {3}".format(
                    project, tracker, contracts, entry["description"]
                ),
                file=sys.stderr,
            )
        task = self.guess_task(project=project, description=entry["description"])
        return harvest_project, task
