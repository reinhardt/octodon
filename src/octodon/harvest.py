import os
import pickle
import sys

from harvest import Harvest as HarvestConnection
from octodon.exceptions import NotFound
from octodon.utils import get_data_home


class Harvest(object):
    connection_factory = HarvestConnection

    def __init__(
        self,
        url,
        user,
        password,
        project_mapping={},
        task_mapping={},
        default_task=None,
    ):
        self.harvest = self.connection_factory(url, user, password)
        self.project_mapping = project_mapping
        self.task_mapping = task_mapping
        self._projects = []
        self._issue_to_project = {}
        self.project_history_file = os.path.join(
            get_data_home(), "octodon-projects.pickle"
        )
        self.default_task = default_task

    def get_issue(self, issue_id):
        raise NotFound()

    def book_time(self, bookings):
        projects_lookup = dict(
            [(project[u"code"], project) for project in self.projects]
        )
        for entry in bookings:
            project = projects_lookup[entry["project"]]
            project_id = project and project[u"id"] or -1
            tasks_lookup = dict([(task[u"name"], task) for task in project[u"tasks"]])
            task = tasks_lookup.get(entry["activity"])
            task_id = task and task[u"id"] or -1

            issue_desc = ""
            if entry["issue_id"]:
                issue_desc = "[#{0}] {1}: ".format(
                    str(entry["issue_id"]), entry["issue_title"]
                )
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

    @property
    def activities(self):
        return [act["task"] for act in self.harvest.tasks()]

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
