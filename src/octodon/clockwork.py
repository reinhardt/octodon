import os
import re
import sys
from datetime import datetime
from glob import glob
from octodon.tracking import ticket_pattern_jira


class ClockWorkTimeLog(object):
    date_pattern = re.compile("^([0-9]{4})-([0-9]{2})-([0-9]{2}):?")
    time_pattern = re.compile("^([0-9]{2}:?[0-9]{2}) ?(.*)")
    tag_pattern = re.compile("#([^ ]*)")

    def __init__(self, log_path="time_log.txt"):
        self.log_path = log_path

    def get_timeinfo(self, date=datetime.now(), loginfo={}, activities=[]):
        timesheet = self.get_raw_log()
        facts = self.get_facts(timesheet)
        bookings = self.aggregate_facts(facts, date=date, loginfo=loginfo)
        return bookings

    def aggregate_facts(self, facts, date=datetime.now(), loginfo={}):
        bookings = []
        for fact in facts:
            existing = [
                b
                for b in bookings
                if b["description"] == fact["description"]
                and b["spent_on"].date() == fact["spent_on"].date()
            ]
            if existing:
                existing[0]["time"] += fact["time"]
                continue

            if fact["spent_on"].date() == date.date():
                tags = [
                    match
                    for match in self.tag_pattern.findall(fact["description"])
                ]
                fact.update(
                    {
                        "activity": "none",
                        "comments": ". ".join(loginfo.get(fact["issue_id"], [])),
                        "category": "Work",
                        "tags": tags,
                        "project": "",
                    }
                )
                bookings.append(fact)
        return bookings

    def get_raw_log(self, log_path=None):
        if log_path is None:
            log_path = self.log_path
        if os.path.isfile(log_path):
            log_file = open(log_path, "r")
            for line in log_file:
                yield line
            log_file.close()
        elif os.path.isdir(log_path):
            for file_path in os.listdir(log_path):
                log_file = open(os.path.join(log_path, file_path), "r")
                for line in log_file:
                    yield line
                log_file.close()
        else:
            paths = glob(self.log_path)
            for log_path in paths:
                for line in self.get_raw_log(log_path):
                    yield line

    def finalize_task(self, current_task, end_time=None):
        if end_time is None:
            # Missing task end - assuming now if current date or end of day if past date
            now = datetime.now()
            if now.date() == self.current_date.date():
                end_time = now
            else:
                print(
                    "*** Warning: Entry has no end time: {}, {}".format(
                        current_task["description"], self.current_date
                    ),
                    file=sys.stderr,
                )
                end_of_day = self.current_date.replace(
                    day=self.current_date.day + 1, hour=0, minute=0
                )
                end_time = end_of_day
        time_spent = end_time - current_task["clock"]
        fact = {
            "description": current_task["description"],
            "issue_id": current_task["issue_id"],
            "spent_on": self.current_date,
            "time": time_spent.seconds / 60.0,
        }
        return fact

    def get_facts(self, timesheet):
        facts = []
        current_task = None
        self.current_date = None
        if isinstance(timesheet, str):
            timesheet = timesheet.split("\n")
        for line in timesheet:
            date_match = self.date_pattern.match(line)
            time_match = self.time_pattern.match(line)
            if date_match:
                if current_task and current_task["description"]:
                    facts.append(self.finalize_task(current_task))
                    current_task = None

                self.current_date = datetime(
                    int(date_match.group(1)),
                    int(date_match.group(2)),
                    int(date_match.group(3)),
                )
            elif time_match:
                next_task = {}
                next_task["clock"] = datetime.strptime(
                    time_match.group(1).replace(":", ""), "%H%M"
                )
                next_task["description"] = time_match.group(2).strip()
                issue_match = ticket_pattern_jira.search(next_task["description"])
                next_task["issue_id"] = None
                if issue_match:
                    next_task["issue_id"] = issue_match.group(1)
                if current_task and current_task["description"]:
                    if next_task["clock"] < current_task["clock"]:
                        next_task["clock"] = next_task["clock"].replace(
                            day=next_task["clock"].day + 1
                        )
                    facts.append(
                        self.finalize_task(current_task, end_time=next_task["clock"])
                    )
                current_task = next_task
        if current_task and current_task["description"]:
            facts.append(self.finalize_task(current_task))
        return facts
