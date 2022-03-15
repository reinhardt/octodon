from github3api import GitHubAPI
from octodon.issue import Issue

import re


class GithubIssue(Issue):
    def __init__(self, data):
        self._data = data

    def get_tracker(self):
        return "Development"

    def get_title(self):
        return self._data.get("title", "")

    def get_project(self):
        return self._data.get("project", "")

    def get_contracts(self):
        contracts = []
        contract = self._data.get("contract", "")
        if contract:
            contracts.append(contract)
        return contracts


class Github(object):
    ticket_pattern = re.compile("(([^/ ]+)/([^/]+)#([0-9]+))")

    def __init__(self, token, organization, project_num):
        self._github = GitHubAPI(bearer_token=token)
        self.organization = organization
        self.project_num = project_num

    @property
    def issues(self):
        if not hasattr(self, "_issues"):
            query = """
                query($organization:String!, $project_num:Int!) {
                    organization(login: $organization) {
                        projectNext(number: $project_num) {
                            items(first:60) {
                            nodes {
                                fieldValues(first:60) {
                                nodes {
                                    value
                                    projectField {
                                        name
                                    }
                                }
                                }
                                content {
                                ...on Issue {
                                    number
                                    title
                                    repository {
                                    owner {
                                        login
                                    }
                                    name
                                    }
                                }
                                }
                            }
                            }
                        }
                    }
                }
            """
            result = self._github.graphql(
                query,
                {"organization": self.organization, "project_num": self.project_num},
            )
            nodes = result["data"]["organization"]["projectNext"]["items"]["nodes"]
            self._issues = {}
            for node in nodes:
                contract = next(
                    (
                        field["value"]
                        for field in node["fieldValues"]["nodes"]
                        if field["projectField"]["name"] == "Contracts"
                    ),
                    None,
                )
                if not node.get("content"):
                    # probably a draft card
                    continue
                repo = node["content"].get("repository")
                if not repo:
                    continue
                owner = repo["owner"]["login"]
                name = repo["name"]
                number = node["content"]["number"]
                title = node["content"]["title"]
                self._issues.setdefault(owner, {}).setdefault(name, {})[number] = {
                    "contract": contract,
                    "title": title,
                }
        return self._issues

    def get_project_id(self, organization, project_num):
        query = """
            query($org:String!, $project_num:Int!) {
                organization(login: $org) {
                    projectNext(number: $project_num) {
                        id
                    }
                }
            }
        """
        variables = {
            "organization": self.organization,
            "project_num": self.project_num,
        }
        result = self._github.graphql(query, variables)
        return result["organization"]["projectNext"]["id"]

    def get_issue(self, issue_no):
        match = self.ticket_pattern.match(issue_no)
        if not match:
            return None
        org, repo, number = match.groups()[1:4]
        try:
            return GithubIssue(self.issues[org][repo][int(number)])
        except KeyError:
            return None
