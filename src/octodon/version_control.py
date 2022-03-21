import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

ref_keyword_pattern = re.compile("([Rr]efs? ?|[Ff]ixes ?)$")


class VCSLog(object):
    def __init__(self, exe=None, patterns=[]):
        self.exe = exe
        self.patterns = patterns

    def extract_loginfo(self, log, mergewith={}):
        logdict = {}
        logdict.update(mergewith)
        for entry in log:
            for ref_pattern in self.patterns:
                matches = ref_pattern.finditer(entry) or []
                for match in matches:
                    comment = ref_pattern.sub("", entry)
                    comment = ref_keyword_pattern.sub("", comment)
                    comment = comment.strip("\n").strip(" ,").strip(" .")
                    logdict.setdefault(match.group(1), []).append(comment)
        return logdict

    def _get_loginfo(self, command, args, repos=[], mergewith={}):
        logdict = mergewith
        for repo in repos:
            if not os.path.exists(repo):
                print(
                    "Warning: Repository path not found: {0}".format(repo),
                    file=sys.stderr,
                )
                continue
            os.chdir(repo)
            try:
                out = subprocess.check_output(" ".join(command + args), shell=True)
            except subprocess.CalledProcessError as cpe:
                print(
                    "%s returned %d: %s" % (command, cpe.returncode, cpe.output),
                    file=sys.stderr,
                )
                continue
            out = out.decode("utf-8")
            log = [
                entry.replace("\n", " ").strip() for entry in out.split("\n\n") if entry
            ]
            logdict = self.extract_loginfo(log, logdict)
        return logdict

    def get_loginfo(self, date=datetime.now(), author=None, repos=[], mergewith={}):
        raise NotImplemented


class SvnLog(VCSLog):
    def __init__(self, exe="/usr/bin/svn", patterns=[]):
        self.exe = exe
        self.patterns = patterns

    def get_loginfo(self, date=datetime.now(), author=None, repos=[], mergewith={}):
        command = [self.exe, "log"]
        args = ['-r "{%s}:{%s}"' % (date, date + timedelta(1))]
        if author:
            args.append('--search="%s"' % author)
        return self._get_loginfo(
            command=command, args=args, repos=repos, mergewith=mergewith
        )


class GitLog(VCSLog):
    def __init__(self, exe="/usr/bin/git", patterns=[]):
        self.exe = exe
        self.patterns = patterns

    def get_loginfo(self, date=datetime.now(), author=None, repos=[], mergewith={}):
        command = [
            self.exe,
            "--no-pager",
            "-c",
            "color.diff=false",
            "log",
            "--branches",
            "--reverse",
            "--pretty=%B",
        ]
        args = ['--since="{%s}"' % date, '--until="{%s}"' % (date + timedelta(1))]
        if author:
            args.append('--author="%s"' % author)
        return self._get_loginfo(
            command=command, args=args, repos=repos, mergewith=mergewith
        )
