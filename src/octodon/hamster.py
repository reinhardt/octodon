from datetime import datetime
from hamster.client import Storage
from octodon.utils import get_default_activity
from octodon.utils import get_ticket_no


class HamsterTimeLog(object):
    def __init__(self, ticket_patterns=[]):
        self.ticket_patterns = ticket_patterns

    def get_timeinfo(self, date=datetime.now(), loginfo={}, activities=[]):
        default_activity = get_default_activity(activities)

        sto = Storage()
        facts = sto.get_facts(date)
        bookings = []
        for fact in facts:
            # delta = (fact.end_time or datetime.now()) - fact.start_time
            # hours = round(fact.delta.seconds / 3600. * 4 + .25) / 4.
            minutes = fact.delta.seconds / 60.0
            # hours = minutes / 60.
            existing = filter(
                lambda b: b["description"] == fact.activity
                and b["spent_on"] == fact.date,
                bookings,
            )
            if existing:
                existing[0]["time"] += minutes
                continue
            ticket = get_ticket_no(
                ["#" + tag for tag in fact.tags]
                + [fact.activity]
                + [fact.description or ""],
                ticket_patterns=self.ticket_patterns,
            )
            bookings.append(
                {
                    "issue_id": ticket,
                    "spent_on": fact.date,
                    "time": minutes,
                    "description": fact.activity,
                    "activity": default_activity.get("name", "none"),
                    "comments": ". ".join(loginfo.get(ticket, [])),
                    "category": fact.category,
                    "tags": fact.tags,
                    "project": "",
                }
            )
        return bookings
