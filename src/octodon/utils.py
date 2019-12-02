import math
import re
from datetime import datetime, timedelta
from functools import reduce
from tempfile import NamedTemporaryFile

ticket_pattern = re.compile("#([A-Z0-9-]+)")


def get_default_activity(activities):
    default_activity = [act for act in activities if act.get("is_default", False)]
    fallback = {"id": None}
    return default_activity and default_activity[0] or fallback


def get_ticket_no(strings):
    tickets = [
        ticket_pattern.search(s).group(1) for s in strings if ticket_pattern.search(s)
    ]
    return len(tickets) and tickets[0] or None


def format_spent_time(time):
    rounded_time = math.ceil(time)
    hours = int(rounded_time / 60.0)
    mins = math.ceil(rounded_time - (hours * 60.0))
    # hours = round(time) / 60
    # mins = round(time) - (hours * 60)
    return "%2d:%02d" % (hours, mins)


def pad(string, length):
    return string + " " * (length - len(string))


def make_row(entry, activities):
    act_name = entry["activity"]
    return [
        "1",
        entry["description"],
        format_spent_time(entry["time"]),
        act_name,
        entry["issue_id"] or "",
        entry["project"],
        entry["comments"],
    ]


def make_table(rows):
    rows = [["L", "Headline", "Time", "Activity", "iss", "Project", "Comments"]] + rows
    columns = zip(*rows)
    max_lens = [max([len(entry) for entry in column]) for column in columns]
    out_strs = []
    divider = "+%s+" % "+".join(["-" * (max_len + 2) for max_len in max_lens])
    for row in rows:
        vals = []
        for i in range(len(row)):
            vals.append(" %s " % pad(row[i].replace("|", " "), max_lens[i]))
        row_str = "|%s|" % "|".join(vals)
        out_strs.append(divider)
        out_strs.append(row_str)

    out_strs.append(divider)
    return "\n".join(out_strs)


def get_time_sum(bookings):
    if len(bookings) == 0:
        return 0.0
    return reduce(lambda x, y: x + y, map(lambda x: x["time"], bookings))


def write_to_file(bookings, spent_on, activities, file_name=None):
    if file_name is not None:
        tmpfile = open(file_name, "w")
    else:
        tmpfile = NamedTemporaryFile(mode="w")
    summary_time = min(datetime.now(), (spent_on + timedelta(1) - timedelta(0, 1)))
    tmpfile.write("#+BEGIN: clocktable :maxlevel 2 :scope file\n")
    tmpfile.write(
        "Clock summary at [" + summary_time.strftime("%Y-%m-%d %a %H:%M") + u"]\n"
    )
    tmpfile.write("\n")

    rows = []

    sum = get_time_sum(bookings)
    rows.append(
        [" ", "*Total time*", "*%s*" % format_spent_time(sum), " ", " ", " ", " "]
    )
    rows += [make_row(entry, activities) for entry in bookings]
    tmpfile.write(make_table(rows))

    tmpfile.write("\n")
    tmpfile.write("\n")
    tmpfile.write(
        "Available activities: %s\n" % ", ".join([act["name"] for act in activities])
    )
    tmpfile.flush()
    new_file_name = tmpfile.name
    tmpfile.close()
    return new_file_name


def read_from_file(filename, activities):
    tmpfile = open(filename, "r")
    data = tmpfile.readlines()
    tmpfile.close()
    bookings = []
    spentdate = None
    default_activity = get_default_activity(activities)
    default_act_name = default_activity.get("name", "[noname]")
    default_columns = [1, "", "0:0", default_act_name, -1, "", ""]

    for line in data:
        if line.startswith("Clock summary at ["):
            splitdate = line[18:-2].split(" ")[0].split("-")
            spentdate = datetime(
                int(splitdate[0]), int(splitdate[1]), int(splitdate[2])
            )
            continue
        if not line.startswith("|") or re.match("^[+-|]*\n", line):
            continue
        columns = [val.strip() for val in re.findall(" *([^|\n]+) *", line)]
        if columns[0] in ["L", ""]:
            continue
        columns = columns + default_columns[len(columns) :]
        hours, minutes = columns[2].split(":")
        spenttime = int(hours) * 60 + int(minutes)
        bookings.append(
            {
                "issue_id": columns[4],
                "spent_on": spentdate.strftime("%Y-%m-%d"),
                "time": float(spenttime),
                "comments": columns[6],
                "project": columns[5],
                "description": columns[1],
                "activity": columns[3],
            }
        )
    tmpfile.close()
    return spentdate, bookings


def clean_up_bookings(bookings):
    removed_time = 0.0
    ignored_time = 0.0
    removed_bookings = []
    for booking in bookings[:]:
        if booking["issue_id"] is None:
            if booking["category"] == u"Work":
                removed_time += booking["time"]
                removed_bookings.append(booking)
                bookings.remove(booking)
            else:
                ignored_time += booking["time"]

    if not bookings:
        return removed_bookings

    sum_time = get_time_sum(bookings) - ignored_time

    if ignored_time > 3.0 * 60.0:
        print(
            "*** Warning: Ignored time is {0} {1}".format(
                ignored_time, format_spent_time(ignored_time)
            )
        )
    if sum_time and (removed_time / sum_time) > 0.1:
        print(
            "*** Warning: Removed time is {0} ({1}) ({2:.2f}%)".format(
                removed_time,
                format_spent_time(removed_time),
                removed_time / (removed_time + sum_time) * 100,
            )
        )
        for booking in sorted(removed_bookings, key=lambda b: b["time"], reverse=True):
            print(
                "    Removed {0} ({1:.0f})".format(
                    booking["description"], booking["time"]
                )
            )

    for booking in bookings:
        if booking["category"] == u"Work":
            booking["time"] += removed_time * booking["time"] / sum_time
    return bookings
