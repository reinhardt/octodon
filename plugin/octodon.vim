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

echo "Octodon"
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
  import octodon
  import time

def Octodon():
    print("Octodon")

def OctodonUpgrade():
  _initialize_octodon_env(upgrade=True)

def OctodonVersion():
  print(f'Octodon, version {octodon.__version__} on Python {sys.version}.')

endpython3

command! Octodon :py3 Octodon()
command! OctodonUpgrade :py3 OctodonUpgrade()
command! OctodonVersion :py3 OctodonVersion()

