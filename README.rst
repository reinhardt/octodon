INSTALL
-------

::

    $ pip install pyactiveresource
    $ cp octodon.cfg.example octodon.cfg

CONFIGURATION
-------------

See octodon.cfg.example

To be able to book time to redmine, you need to fill in the url, user and pass options in the redmine section.

For the source option you can choose hamster or orgmode. orgmode needs an extra section of the same name with an entry filename. Octodon will expect a time tracking report table in this file.

The vcs option currently only supports git. In the git section you can specify paths to repositories, one per line, that will be searched for log entries from the relevant date.
The author option may hold a string that will be passed with --author to git when retrieving the log. If it is ommitted, all log entries will be considered.

RUN
---

::

    python octodon.py

or for other dates than today

::

    python octodon.py --date=20130523
