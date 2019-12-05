# -*- coding: utf-8 -*-
"""Installer for the octodon package."""

from setuptools import find_packages
from setuptools import setup

import os


def read(*rnames):
    return open(os.path.join(os.path.dirname(__file__), *rnames)).read()


long_description = (
    read("README.rst") + read("docs", "CHANGELOG.rst") + read("docs", "LICENSE.rst")
)

setup(
    name="octodon",
    version="1.0.0.dev0",
    description="Import, manage and export time tracking data",
    long_description=long_description,
    # Get more from http://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        "Environment :: Console",
        "Environment :: Plugins",
        "License :: OSI Approved :: BSD License",
        "Programming Language :: Python",
    ],
    keywords="time tracking harvest redmine jira",
    author="Manuel Reinhardt",
    author_email="manuel.reinhardt@neon-cathedral.net",
    url="https://pypi.python.org/pypi/octodon",
    license="BSD",
    packages=find_packages(".", exclude=["ez_setup"]),
    package_dir={"": "src"},
    include_package_data=True,
    zip_safe=False,
    install_requires=["jira", "pyactiveresource", "python-harvest-redux", "setuptools"],
    extras_require={"test": ["mock"]},
    entry_points="""
      [console_scripts]
      octodon=octodon.cmd:main
    """,
)
