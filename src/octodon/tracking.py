import os
import pickle
import socket
import re
from octodon.utils import get_data_home

try:
    from pyactiveresource.connection import ResourceNotFound
    from pyactiveresource.connection import Error
except ImportError:
    class ResourceNotFound(Exception):
        pass

    class Error(Exception):
        pass

try:
    from jira import JIRAError
except ImportError:
    class JIRAError(Exception):
        pass

ticket_pattern_jira = re.compile("#?([A-Z0-9]+-[0-9]+)")


class Tracking(object):
    def __init__(
        self,
        redmine=None,
        jira=None,
        harvest=None,
        project_mapping={},
        task_mapping={},
        project_history_file=None,
    ):
        self.redmine = redmine
        self.jira = jira
        self.harvest = harvest
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
                    )
                )
                if u"message" in harvest_data:
                    print(harvest_data[u"message"])
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
                if ticket_pattern_jira.match(entry["issue_id"]) and self.jira:
                    try:
                        issue = self.jira.jira.issue(entry["issue_id"])
                        issue_title = issue.fields.summary
                    except JIRAError as je:
                        print(
                            u"Could not find issue {0}: {1} - {2}".format(
                                str(entry["issue_id"]), je.status_code, je.text
                            )
                        )
                if not issue_title and self.redmine:
                    try:
                        issue = self.redmine.Issue.get(int(entry["issue_id"]))
                        issue_title = issue["subject"]
                    except (ResourceNotFound, Error):
                        print("Could not find issue " + str(entry["issue_id"]))

            self.harvest.add(
                {
                    "notes": "[#{1}] {2}: {0}".format(
                        entry["comments"].encode("utf-8"),
                        str(entry["issue_id"]).encode("utf-8"),
                        issue_title.encode("utf-8"),
                    ),
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

    def redmine_harvest_mapping(
        self, harvest_projects, project=None, tracker=None, contracts=[], description=""
    ):
        task = "Development"
        for key, value in self.task_mapping.items():
            if key in description.lower():
                task = value
                break

        harvest_project = ""
        if project in self.project_mapping:
            harvest_project = self.project_mapping[project]
        elif project in harvest_projects:
            harvest_project = project
        elif project:
            part_matches = [
                proj
                for proj in harvest_projects
                if project.lower().startswith(proj.lower())
                or proj.lower().startswith(project.lower())
            ]
            if part_matches:
                harvest_project = part_matches[0]
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
        # Because of harvest's limited filtering we want bugs in a separate project.
        if tracker == "Bug":
            if "recensio" in harvest_project.lower():
                harvest_project = "recensio-bugpool"
            if "star" in harvest_project.lower():
                harvest_project = "star-bugpool"
        return (harvest_project, task)

    def get_harvest_target(self, entry):
        harvest_projects = [project[u"code"] for project in self.projects]

        issue_no = entry["issue_id"]
        issue = None
        project = ""
        contracts = []
        if issue_no is not None:
            if ticket_pattern_jira.match(issue_no) and self.jira:
                try:
                    issue = self.jira.jira.issue(issue_no)
                except JIRAError as je:
                    print(
                        u"Could not find issue {0}: {1} - {2}".format(
                            str(issue_no), je.status_code, je.text
                        )
                    )
            elif self.redmine:
                try:
                    issue = self.redmine.Issue.get(issue_no)
                except (ResourceNotFound, Error, socket.error):
                    print("Could not find issue " + str(issue_no))

        if issue is not None:
            if ticket_pattern_jira.match(issue_no) and self.jira:
                project = issue.fields.project.key
                contracts_field = issue.fields.customfield_10902
                contracts = (
                    [contracts_field.child.value]
                    if hasattr(contracts_field, "child")
                    else []
                )
            elif self.redmine:
                pid = issue["project"]["id"]
                try:
                    project = self.redmine.Projects.get(pid)["identifier"]
                except Exception as e:
                    print(
                        "Could not get project identifier: {0}; {1}".format(
                            issue["project"]["name"], e
                        )
                    )
                    project = ""
                contracts = [
                    f.get("value", [])
                    for f in issue["custom_fields"]
                    if f["name"].startswith("Contracts")
                ]

        for tag in entry["tags"]:
            if tag in harvest_projects:
                project = tag
        if entry["category"] in harvest_projects:
            project = entry["category"]

        tracker = None
        if issue_no and ticket_pattern_jira.match(issue_no) and self.jira:
            tracker = issue and issue.fields.issuetype.name
        elif self.redmine:
            tracker = issue and issue["tracker"]["name"]

        harvest_project, task = self.redmine_harvest_mapping(
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
                )
            )
        return harvest_project, task
