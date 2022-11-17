from github3api import GitHubAPI
from github3api.githubapi import GraphqlError
from octodon.issue import Issue

import logging
import re


logger = logging.getLogger(__name__)


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
                query($organization:String!, $project_num:Int!, $items_cursor:String!) {
                    organization(login: $organization) {
                        projectV2(number: $project_num) {
                            items(first:100, after: $items_cursor) {
                            nodes {
                                fieldValueByName(name: "Contracts") {
                                    ...on ProjectV2ItemFieldTextValue {
                                        text
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
                            pageInfo {
                              endCursor
                              hasNextPage
                            }
                            }
                        }
                    }
                }
            """
            items_cursor = ""
            hasNextPage = True
            self._issues = {}
            while hasNextPage:
                try:
                    result = self._github.graphql(
                        query,
                        {
                            "organization": self.organization,
                            "project_num": self.project_num,
                            "items_cursor": items_cursor,
                        },
                    )
                except GraphqlError as e:
                    logger.error(str(e))
                    return self._issues
                nodes = result["data"]["organization"]["projectV2"]["items"]["nodes"]
                for node in nodes:
                    contract = (node.get("fieldValueByName") or {}).get("text")
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
                hasNextPage = result["data"]["organization"]["projectV2"]["items"][
                    "pageInfo"
                ]["hasNextPage"]
                items_cursor = result["data"]["organization"]["projectV2"]["items"][
                    "pageInfo"
                ]["endCursor"]
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
