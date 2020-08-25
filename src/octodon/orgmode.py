from datetime import datetime
from octodon.utils import get_ticket_no
from octodon.utils import read_from_file


class OrgModeTimeLog(object):
    def __init__(self, filename, ticket_patterns=[]):
        self.filename = filename
        self.ticket_patterns = ticket_patterns

    def get_timeinfo(self, date=datetime.now(), loginfo={}, activities=[]):
        _, bookings = read_from_file(self.filename, activities)
        for booking in bookings:
            ticket = get_ticket_no(
                [booking["description"]], ticket_patterns=self.ticket_patterns
            )
            booking["issue_id"] = ticket
            booking["comments"] = "; ".join(loginfo.get(ticket, []))
            booking["project"] = ""
        return bookings
