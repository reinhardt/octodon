from datetime import datetime
from octodon.utils import get_ticket_no
from octodon.utils import read_from_file


class OrgModeTimeLog(object):
    def __init__(self, filename):
        self.filename = filename

    def get_timeinfo(self, date=datetime.now(), loginfo={}, activities=[]):
        _, bookings = read_from_file(self.filename, activities)
        for booking in bookings:
            ticket = get_ticket_no([booking["description"]])
            booking["issue_id"] = ticket
            booking["comments"] = "; ".join(loginfo.get(ticket, []))
            booking["project"] = ""
        return bookings
