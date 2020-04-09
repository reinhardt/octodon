INTRODUCTION
------------

Octodon reads time tracking data from a source like hamster or plain text files, processes it, allows you to modify or add to it, and writes it to one or more targets like jira or harvest.

If you mention (redmine or jira) tickets in your time log and also in commit messages, octodon pairs them up and suggests the commit messages as comments for your time bookings. Time that doesn't reference a ticket is regarded as overhead. Octodon divides it up and proportionally adds it to the other time tracking entries.

INSTALL
-------

::

    $ pip install octodon
    $ cp octodon.cfg.example ~/.config/octodon.cfg

CONFIGURATION
-------------

See octodon.cfg.example

To be able to book time to redmine or harvest, you need to fill in the *url*, *user* and *pass* options in the respective section (*redmine* or *harvest*).

For the *source* option you can choose *hamster*, *orgmode* or *plaintext*. *orgmode* needs a section *[orgmode]* with an entry *filename*. Octodon will expect a time tracking report table in this file. *plaintext* needs a section *[plaintext]* with an entry *log_path*. This can be a path to a file, a folder, or a glob, specifying data in a format like this:

::

    2019-12-04:
    0805 PROJ-123: improve deployment infrastructure
    0915
    0930 daily standup
    0945

The *vcs* option currently supports *git* and *svn*. In the *git* and *svn* sections you can use the *repos* option to specify paths to repositories, one per line, that will be searched for log entries from the relevant date.
In *git* the *author* option may hold a string that will be used for filtering for authors, i.e. will be passed with --author to git when retrieving the log. If it is ommitted, all log entries will be considered.

RUN
---

::

    octodon

or for other dates than today

::

    octodon --date=20130523

Relative dates are supported as well, e.g. for the day before yesterday

::

    octodon --date=-2

There is a simple command-line interface. The most important commands are *edit*, which lets you review and modify the time tracking data, and *book*, which writes it to the configured target(s) (e.g. harvest).

VIM PLUGIN
----------

You can install the vim plugin via vundle, pathogen, etc. by adding this to your .vimrc:

::

    Plugin "reinhardt/octodon"

If you have a plaintext time log file open, the command :OctodonTimeSum shows you the total time tracked today.
