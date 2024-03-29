" octodon.vim
" Author: Manuel Reinhardt
" Created: Fri 22 Nov 09:51:36 CET 2019
" Requires: Vim Ver7.0+
" Version:  1.0
"
" Documentation:
"   This plugin provides helpers for plain text time tracking.
"
" History:
"  1.0:
"    - initial version

if v:version < 700 || !has('python3')
    echo "This script requires vim7.0+ with Python 3.6 support."
    finish
endif

if exists("g:load_octodon")
   finish
endif

let g:load_octodon = "py1.0"
if !exists("g:octodon_virtualenv")
  let g:octodon_virtualenv = "~/.vim/octodon"
endif

python3 << endpython3
import os
import sys
import vim

def _get_python_binary(exec_prefix):
  try:
    default = vim.eval("g:pymode_python").strip()
  except vim.error:
    default = ""
  if default and os.path.exists(default):
    return default
  if sys.platform[:3] == "win":
    return exec_prefix / 'python.exe'
  return exec_prefix / 'bin' / 'python3'

def _get_pip(venv_path):
  if sys.platform[:3] == "win":
    return venv_path / 'Scripts' / 'pip.exe'
  return venv_path / 'bin' / 'pip'

def _get_virtualenv_site_packages(venv_path, pyver):
  if sys.platform[:3] == "win":
    return venv_path / 'Lib' / 'site-packages'
  return venv_path / 'lib' / f'python{pyver[0]}.{pyver[1]}' / 'site-packages'

def _initialize_octodon_env(upgrade=False):
  from pathlib import Path
  import subprocess
  import venv
  pyver = sys.version_info[:2]
  virtualenv_path = Path(vim.eval("g:octodon_virtualenv")).expanduser()
  virtualenv_site_packages = str(_get_virtualenv_site_packages(virtualenv_path, pyver))
  first_install = False
  if not virtualenv_path.is_dir():
    print('Please wait, one time setup for Octodon.')
    _executable = sys.executable
    try:
      sys.executable = str(_get_python_binary(Path(sys.exec_prefix)))
      print(f'Creating a virtualenv in {virtualenv_path}...')
      print('(this path can be customized in .vimrc by setting g:octodon_virtualenv)')
      venv.create(virtualenv_path, with_pip=True)
    finally:
      sys.executable = _executable
    first_install = True
  if first_install:
    print('Installing Octodon with pip...')
  if upgrade:
    print('Upgrading Octodon with pip...')
  if first_install or upgrade:
    subprocess.run([str(_get_pip(virtualenv_path)), 'install', '-U', 'octodon'], stdout=subprocess.PIPE)
    print('DONE! You are all set, thanks for waiting ✨ 🍰 ✨')
  if first_install:
    print('Pro-tip: to upgrade Octodon in the future, use the :OctodonUpgrade command and restart Vim.\n')
  if sys.path[0] != virtualenv_site_packages:
    sys.path.insert(0, virtualenv_site_packages)
  return True

if _initialize_octodon_env():
    import re
    import subprocess
    from datetime import datetime
    from octodon.clockwork import ClockWorkTimeLog
    from octodon.cli import get_config
    from octodon.github import Github
    from octodon.utils import format_spent_time
    from octodon.utils import get_time_sum

def OctodonTimeSum():
    clockwork = ClockWorkTimeLog()
    facts = clockwork.get_facts('\n'.join(vim.current.buffer) + '\n')
    bookings = clockwork.aggregate_facts(facts)
    sum = get_time_sum(bookings)
    print(format_spent_time(sum))

def OctodonClock():
    line = vim.current.line
    current_line_no = vim.current.window.cursor[0] - 1
    previous_line_no = current_line_no - 1
    next_line_no = current_line_no + 1

    # when on a previous line, start that task
    time_pattern = "^[0-9]{4} "
    if re.search(time_pattern, line) and current_line_no < len(vim.current.buffer) - 1:
        current_line_no = len(vim.current.buffer)
        buffer = vim.current.buffer.range(0, current_line_no)
        buffer.append(re.sub(time_pattern, "", line))
        vim.current.window.cursor = (current_line_no + 1, vim.current.window.cursor[1])
        line = vim.current.line

    # when line is empty, continue last task
    previous_task = ""
    if not line.strip() and previous_line_no > 0:
        previous_line = vim.current.buffer[previous_line_no].strip()
        previous_task = re.sub("^[0-9]{4}", "", previous_line).strip()
        if not previous_task:
            previous_line = vim.current.buffer[previous_line_no - 1].strip()
            previous_task = re.sub("^[0-9]{4} ", "", previous_line)
            line = vim.current.line = previous_task

    # add current time if none given
    if previous_task or not re.search(time_pattern, line):
        now = datetime.now().strftime("%H%M")
        line = f"{now} {line}"

    line = re.sub("https://github.com/([^/]*)/([^/]*)/issues/([0-9]*)", "\\1/\\2#\\3", line)

    # expand ticket reference
    from octodon.github import Github
    from github3api import GitHubAPI
    ticket_match = Github.ticket_pattern.search(line)
    if ticket_match:
        config = get_config()
        if config.has_section("github"):
            if config.has_option("github", "token_command"):
                cmd = config.get("github", "token_command")
                token = subprocess.check_output(cmd.split(" ")).strip().decode("utf-8")
                config.set("github", "token", token)
            githubapi = GitHubAPI(bearer_token=config.get("github", "token"))

            org, repo, number = ticket_match.groups()[1:4]
            try:
                issue = githubapi.get(f"/repos/{org}/{repo}/issues/{number}")
            except:
                issue = None
            if issue:
                issue_id = ticket_match[1]
                summary = issue.get("title", "")
                issue_text = f"{summary} {issue_id}"
                if issue_text not in line:
                    line = line.replace(issue_id, issue_text)
    vim.current.line = line

    # when previous line is empty, start a new day
    if previous_line_no < 0 or not vim.current.buffer[previous_line_no].strip():
        date_line = "{}:".format(datetime.now().strftime("%Y-%m-%d"))
        buffer = vim.current.buffer.range(0, current_line_no)
        buffer.append(date_line)

def OctodonUpgrade():
  _initialize_octodon_env(upgrade=True)

def OctodonVersion():
  print(f'Octodon, version {octodon.__version__} on Python {sys.version}.')

endpython3

command! OctodonClock :py3 OctodonClock()
command! OctodonTimeSum :py3 OctodonTimeSum()
command! OctodonUpgrade :py3 OctodonUpgrade()
command! OctodonVersion :py3 OctodonVersion()

