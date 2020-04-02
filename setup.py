"""Setup file for the Hairgap project.
"""

# ##############################################################################
#  This file is part of Hairgap                                                #
#                                                                              #
#  Copyright (C) 2020 Matthieu Gallet <github@19pouces.net>                    #
#  All Rights Reserved                                                         #
#                                                                              #
#  You may use, distribute and modify this code under the                      #
#  terms of the (BSD-like) CeCILL-B license.                                   #
#                                                                              #
#  You should have received a copy of the CeCILL-B license with                #
#  this file. If not, please visit:                                            #
#  https://cecill.info/licences/Licence_CeCILL-B_V1-en.txt (English)           #
#  or https://cecill.info/licences/Licence_CeCILL-B_V1-fr.txt (French)         #
#                                                                              #
# ##############################################################################

import os.path
import re

from setuptools import find_packages, setup

# avoid a from hairgap import __version__ as version (that compiles hairgap.__init__ and is not compatible with bdist_deb)
version = None
with open(os.path.join("hairgap", "__init__.py")) as fd:
    for line in fd:
        matcher = re.match(r"""^__version__\s*=\s*['"](.*)['"]\s*$""", line)
        version = version or matcher and matcher.group(1)

# get README content from README.md file
with open(os.path.join(os.path.dirname(__file__), "README.md")) as fd:
    long_description = fd.read()

entry_points = {"console_scripts": ["pyhairgap = hairgap.cli:main"]}

setup(
    name="hairgap",
    version=version,
    description="Basic protocol to send files using the hairgap binary ( github.com/cea-sec/hairgap ).",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Matthieu Gallet",
    author_email="github@19pouces.net",
    license="CeCILL-B",
    url="https://github.com/d9pouces/hairgap",
    entry_points=entry_points,
    packages=find_packages(),
    include_package_data=True,
    zip_safe=True,
    test_suite="hairgap.tests",
    install_requires=[],
    setup_requires=[],
    tests_require=["tox", "pytest", "sphinx"],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX :: BSD",
        "Operating System :: POSIX :: Linux",
        "Operating System :: Unix",
        "License :: OSI Approved :: CEA CNRS Inria Logiciel Libre License, version 2.1 (CeCILL-2.1)",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3 :: Only",
    ],
)
