import os
import re
import subprocess
from datetime import datetime, timedelta

ref_pattern = re.compile("(?:    )?(.*)#([A-Z0-9-]+)")
ref_keyword_pattern = re.compile("([Rr]efs |[Ff]ixes )$")


class VCSLog(object):
    def __init__(self, exe=None):
        self.exe = exe

    def extract_loginfo(self, log, mergewith={}):
        matches = ref_pattern.finditer(log) or []
        logdict = mergewith
        for match in matches:
            comment = ref_keyword_pattern.sub("", match.group(1))
            comment = comment.strip(" ,").strip(" .")
            logdict.setdefault(match.group(2), []).append(comment)
        return logdict

    def _get_loginfo(self, command, args, repos=[], mergewith={}):
        logdict = mergewith
        for repo in repos:
            if not os.path.exists(repo):
                print("Warning: Repository path not found: {0}".format(repo))
                continue
            os.chdir(repo)
            try:
                out = subprocess.check_output(" ".join(command + args), shell=True)
            except subprocess.CalledProcessError as cpe:
                print("%s returned %d: %s" % (command, cpe.returncode, cpe.output))
                continue
            log = "\n".join(
                [
                    re.sub("^([A-Za-z]*:\s*.*\n)*", "", entry)
                    .replace("\n    ", " ")
                    .strip()
                    for entry in re.split("^commit [a-z0-9]*\n", out)
                    if entry
                ]
            )
            logdict = self.extract_loginfo(log, logdict)
        return logdict

    def get_loginfo(self, date=datetime.now(), author=None, repos=[], mergewith={}):
        raise NotImplemented


class SvnLog(VCSLog):
    def __init__(self, exe="/usr/bin/svn"):
        self.exe = exe

    def get_loginfo(self, date=datetime.now(), author=None, repos=[], mergewith={}):
        command = [self.exe, "log"]
        args = ['-r "{%s}:{%s}"' % (date, date + timedelta(1))]
        if author:
            args.append('--search="%s"' % author)
        return self._get_loginfo(
            command=command, args=args, repos=repos, mergewith=mergewith
        )


class GitLog(VCSLog):
    def __init__(self, exe="/usr/bin/git"):
        self.exe = exe

    def get_loginfo(self, date=datetime.now(), author=None, repos=[], mergewith={}):
        command = [
            self.exe,
            "--no-pager",
            "-c",
            "color.diff=false",
            "log",
            "--branches",
            "--reverse",
        ]
        args = ['--since="{%s}"' % date, '--until="{%s}"' % (date + timedelta(1))]
        if author:
            args.append('--author="%s"' % author)
        return self._get_loginfo(
            command=command, args=args, repos=repos, mergewith=mergewith
        )
