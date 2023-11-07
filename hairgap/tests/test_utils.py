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
import importlib.resources
import os
from contextlib import ExitStack
from sysconfig import get_platform
from unittest import TestCase

import atexit

from hairgap.utils import Config, get_arp_cache


def get_filename(name: str) -> str:
    file_manager = ExitStack()
    atexit.register(file_manager.close)
    ref = importlib.resources.files("hairgap").joinpath(f"tests/{name}")
    return str(file_manager.enter_context(importlib.resources.as_file(ref)))


class TestUtils(TestCase):
    def test_config(self):
        c = Config()
        self.assertIsNotNone(c.tar)
        self.assertIsNotNone(c.cat)
        self.assertIsNotNone(c.split)
        self.assertTrue(os.path.isfile(c.tar))
        self.assertTrue(os.path.isfile(c.split))
        self.assertTrue(os.path.isfile(c.cat))
        platform = get_platform()
        if platform == "linux-x86_64":
            self.assertTrue(os.path.isfile(c.hairgapr_path))
            self.assertTrue(os.path.isfile(c.hairgaps_path))
        else:
            print("Unknown platform : %s" % platform)

    def test_parse_arp(self):
        value = """Address                  HWtype  HWaddress           Flags Mask            Iface
192.168.56.150                   (incomplete)                              enp2s0
10.2.1.103               ether   f0:18:98:a4:58:e2   C                     enp0s31f6
10.2.1.1                 ether   14:91:82:34:97:33   C                     enp0s31f6"""
        actual = get_arp_cache(content=value)
        expected = {
            "192.168.56.150": (None, "enp2s0"),
            "10.2.1.103": ("f0:18:98:a4:58:e2", "enp0s31f6"),
            "10.2.1.1": ("14:91:82:34:97:33", "enp0s31f6"),
        }
        self.assertEqual(expected, actual)
