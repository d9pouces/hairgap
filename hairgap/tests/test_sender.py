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
import os
import socket
import tempfile
from typing import Dict
from unittest import TestCase

from hairgap.sender import DirectorySender
from hairgap.tests.test_utils import get_filename
from hairgap.utils import Config, ensure_dir


class DemoDirectorySender(DirectorySender):
    def __init__(self, config: Config, dirname: str):
        super().__init__(config)
        self.config = config
        self.root_directory = dirname

    @property
    def transfer_abspath(self) -> str:
        """returns the absolute path of directory to send"""
        return os.path.join(self.root_directory, "original")

    @property
    def index_abspath(self):
        """returns the absolute path of the index file to create"""
        return os.path.join(self.root_directory, "index.txt")

    def get_attributes(self) -> Dict[str, str]:
        return {"key": "value"}

    def create_files(
        self,
        file_count=10,
        file_size=10000,
    ):
        ensure_dir(self.transfer_abspath, parent=False)
        for i in range(file_count):
            with open(os.path.join(self.transfer_abspath, "%08d.txt" % i), "w") as fd:
                fd.write("123456789\n" * file_size)


class TestSender(TestCase):
    def test_archive_and_split_directory(self):
        with tempfile.TemporaryDirectory() as dirname:
            sender = self.create_sender(dirname)
            splitted_path = os.path.join(dirname, "splitted")
            DirectorySender.archive_and_split_directory(
                sender.config, sender.transfer_abspath, splitted_path, split_size=12000
            )
            expected = {"content.tar.gz.aa"}
            actual = set(os.listdir(splitted_path))
            self.assertEqual(expected, actual)

    def test_split_source_files(self):
        with tempfile.TemporaryDirectory() as dirname:
            sender = self.create_sender(dirname)
            sender.split_source_files(sender.transfer_abspath, split_size=12000)
            expected = {"content.tar.gz.aa"}
            actual = set(os.listdir(sender.transfer_abspath))
            self.assertEqual(expected, actual)

    def test_split_source_files_2(self):
        with tempfile.TemporaryDirectory() as dirname:
            sender = self.create_sender(dirname)
            sender.split_source_files(sender.transfer_abspath, split_size=100000)
            expected = {"content.tar.gz.aa"}
            actual = set(os.listdir(sender.transfer_abspath))
            self.assertEqual(expected, actual)

    def test_prepare_directory_no_tar_splitted(self):
        with tempfile.TemporaryDirectory() as dirname:
            sender = self.create_sender(dirname)
            sender.prepare_directory_no_tar()
            with open(sender.index_abspath) as fd:
                index_content = fd.read()
        actual = index_content.splitlines()
        del actual[5]
        # the tar.gz header varies, so the sha256 always differs
        expected = [
            "# *-* HAIRGAP-INDEX *-*",
            "[hairgap]",
            "key = value",
            "[splitted_content]",
            "[files]",
        ]
        self.assertEqual(expected, actual)

    def test_prepare_directory_no_tar_not_splitted(self):
        with tempfile.TemporaryDirectory() as dirname:
            sender = self.create_sender(dirname, split_size=0)
            sender.prepare_directory_no_tar()
            with open(sender.index_abspath) as fd:
                index_content = fd.read()
        actual = index_content.splitlines()
        expected = [
            "# *-* HAIRGAP-INDEX *-*",
            "[hairgap]",
            "key = value",
            "[files]",
            "20adcf9eb97578a985b15102d302ca04b6405f7e242a09644611404cc89d5b47 = 00000000.txt",
            "20adcf9eb97578a985b15102d302ca04b6405f7e242a09644611404cc89d5b47 = 00000001.txt",
            "20adcf9eb97578a985b15102d302ca04b6405f7e242a09644611404cc89d5b47 = 00000002.txt",
            "20adcf9eb97578a985b15102d302ca04b6405f7e242a09644611404cc89d5b47 = 00000003.txt",
            "20adcf9eb97578a985b15102d302ca04b6405f7e242a09644611404cc89d5b47 = 00000004.txt",
            "20adcf9eb97578a985b15102d302ca04b6405f7e242a09644611404cc89d5b47 = 00000005.txt",
            "20adcf9eb97578a985b15102d302ca04b6405f7e242a09644611404cc89d5b47 = 00000006.txt",
            "20adcf9eb97578a985b15102d302ca04b6405f7e242a09644611404cc89d5b47 = 00000007.txt",
            "20adcf9eb97578a985b15102d302ca04b6405f7e242a09644611404cc89d5b47 = 00000008.txt",
            "20adcf9eb97578a985b15102d302ca04b6405f7e242a09644611404cc89d5b47 = 00000009.txt",
        ]
        self.assertEqual(expected, actual)

    def create_sender(
        self,
        dirname,
        split_size=15000,
        file_count=10,
        file_size=10000,
        use_tar_archives: bool = False,
    ):
        config = self.get_config(
            dirname, use_tar_archives=use_tar_archives, split_size=split_size
        )
        sender = DemoDirectorySender(config, dirname)
        sender.create_files(file_count=file_count, file_size=file_size)
        return sender

    @staticmethod
    def get_config(tmp_dir, use_tar_archives: bool = False, split_size=10000):
        src_port = 15124
        while True:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.bind(("localhost", src_port))
                break
            except OSError:
                src_port += 1
        return Config(
            destination_ip="localhost",
            destination_port=src_port,
            destination_path=os.path.join(tmp_dir, "transfering"),
            end_delay_s=3.0,
            error_chunk_size=None,
            keepalive_ms=500,
            max_rate_mbps=None,
            mem_limit_mb=None,
            mtu_b=None,
            timeout_s=3.0,
            redundancy=3.0,
            hairgapr=get_filename("hairgapr.py"),
            hairgaps=get_filename("hairgaps.py"),
            use_tar_archives=use_tar_archives,
            split_size=split_size,
        )
