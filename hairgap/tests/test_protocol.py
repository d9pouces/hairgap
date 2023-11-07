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
import logging
import os
import shutil
import socket
import tempfile
import uuid
from tempfile import TemporaryDirectory
from threading import Thread
from typing import Dict, Optional
from unittest import TestCase

import time

from hairgap.constants import (
    HAIRGAP_MAGIC_NUMBER_EMPTY,
    HAIRGAP_MAGIC_NUMBER_ESCAPE,
    HAIRGAP_MAGIC_NUMBER_INDEX,
)
from hairgap.receiver import Receiver
from hairgap.sender import DirectorySender
from hairgap.tests.test_utils import get_filename
from hairgap.utils import Config, ensure_dir, now


class SingleDirReceiver(Receiver):
    available_attributes = {"current_uid", "previous_uid", "title", "url", "creation"}

    def __init__(
        self,
        config: Config,
        after_reception_path: str,
        threading: bool = False,
        port: int = None,
    ):
        super().__init__(config, threading=threading, port=port)
        self.after_reception_path = after_reception_path
        self.unexpected_content = None

    def transfer_complete(self):
        super().transfer_complete()
        self.continue_loop = False

    def transfer_file_unexpected(self, tmp_abspath: str, prefix: bytes = None):
        self.continue_loop = False
        self.unexpected_content = prefix
        return super().transfer_file_unexpected(tmp_abspath, prefix)

    def get_current_transfer_directory(self) -> Optional[str]:
        if not self.current_attributes["current_uid"]:
            return None
        return self.after_reception_path


class SingleDirSender(DirectorySender):
    def __init__(self, config: Config, directory_path: str):
        super().__init__(config)
        self.directory_path = directory_path
        self.index_path = directory_path + ".txt"
        self.creation_date = now()
        self.uid = uuid.uuid4()

    def get_attributes(self) -> Dict[str, str]:
        return {
            "current_uid": str(self.uid),
            "creation": self.creation_date.strftime("%Y-%m-%dT%H:%M:%s"),
        }

    @property
    def transfer_abspath(self):
        return self.directory_path

    @property
    def index_abspath(self):
        return self.index_path


class TestDiodeTransfer(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.receiver = None

    def test_send_file(self):
        with TemporaryDirectory() as tmp_dir:
            config = self.get_config(tmp_dir)
            ref = importlib.resources.files("hairgap").joinpath("tests/__init__.py")
            dst_path = os.path.join(tmp_dir, "received.txt")

            process_thread = Thread(target=self.receive_file, args=(config, dst_path))
            process_thread.start()
            time.sleep(1.0)
            sender = SingleDirSender(config, os.path.join(tmp_dir, "source"))
            with importlib.resources.as_file(ref) as src_path:
                sender.send_file(config, str(src_path))
                time.sleep(1.0)
                self.assertTrue(os.path.isfile(dst_path))
                with open(src_path) as fd:
                    expected_content = fd.read()
            with open(dst_path) as fd:
                actual_content = fd.read()
            self.assertEqual(expected_content, actual_content)

    ##########################################################################
    #               Small files
    ##########################################################################

    def test_create_transfer_no_tar_no_split(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            ref = importlib.resources.files("hairgap").joinpath("tests")
            with importlib.resources.as_file(ref) as src_path:
                self.send_directory(
                    tmp_dir, str(src_path), use_tar_archives=False, split_size=None
                )

    def test_create_transfer_no_tar_split(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            ref = importlib.resources.files("hairgap").joinpath("tests")
            with importlib.resources.as_file(ref) as src_path:
                self.send_directory(
                    tmp_dir, str(src_path), use_tar_archives=False, split_size=20000
                )

    def test_create_transfer_tar(self):
        logging.basicConfig(level=logging.DEBUG)
        with tempfile.TemporaryDirectory() as tmp_dir:
            ref = importlib.resources.files("hairgap").joinpath("tests")
            with importlib.resources.as_file(ref) as src_path:
                self.send_directory(tmp_dir, str(src_path), use_tar_archives=True)

    ##########################################################################
    #               Empty file
    ##########################################################################
    def test_send_empty_file_no_tar_split(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            src_path = os.path.join(tmp_dir, "original")
            ensure_dir(src_path, parent=False)
            open(os.path.join(src_path, "empty_file.txt"), "w").close()
            self.send_directory(
                tmp_dir, src_path, use_tar_archives=False, split_size=20000
            )

    def test_send_empty_file_no_tar_no_split(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            src_path = os.path.join(tmp_dir, "original")
            ensure_dir(src_path, parent=False)
            open(os.path.join(src_path, "empty_file.txt"), "w").close()
            self.send_directory(
                tmp_dir, src_path, use_tar_archives=False, split_size=None
            )

    def test_send_empty_file_tar(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            src_path = os.path.join(tmp_dir, "original")
            ensure_dir(src_path, parent=False)
            open(os.path.join(src_path, "empty_file.txt"), "w").close()
            self.send_directory(tmp_dir, src_path, use_tar_archives=True)

    ##########################################################################
    #               Empty directory
    ##########################################################################
    def test_send_empty_dir_no_tar_split(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            src_path = os.path.join(tmp_dir, "original")
            ensure_dir(src_path, parent=False)
            self.send_directory(
                tmp_dir, src_path, use_tar_archives=False, split_size=20000
            )

    def test_send_empty_dir_no_tar_no_split(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            src_path = os.path.join(tmp_dir, "original")
            ensure_dir(src_path, parent=False)
            self.send_directory(
                tmp_dir, src_path, use_tar_archives=False, split_size=None
            )

    def test_send_empty_dir_tar(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            src_path = os.path.join(tmp_dir, "original")
            ensure_dir(src_path, parent=False)
            self.send_directory(tmp_dir, src_path, use_tar_archives=True)

    ##########################################################################
    #               Unexpected file
    ##########################################################################

    def test_unexpected_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = self.get_config(tmp_dir)
            src_path = os.path.join(tmp_dir, "test_filename")
            with open(src_path, "w") as fd:
                fd.write("Unexpected content\n")
            dst_path = os.path.join(tmp_dir, "destination")
            receiver = SingleDirReceiver(config, dst_path)
            process_thread = Thread(target=receiver.loop, args=())
            process_thread.start()
            time.sleep(1.0)
            SingleDirSender.send_file(config, src_path)
            self.assertEqual(b"Unexpected content\n", receiver.unexpected_content)

    def test_send_constants(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            src_path = os.path.join(tmp_dir, "original")
            ensure_dir(src_path, parent=False)
            for name, value in (
                ("empty.txt", HAIRGAP_MAGIC_NUMBER_EMPTY),
                ("escape.txt", HAIRGAP_MAGIC_NUMBER_ESCAPE),
                ("index.txt", HAIRGAP_MAGIC_NUMBER_INDEX),
            ):
                with open(os.path.join(src_path, name), "w") as fd:
                    fd.write("%s\n" % value)
            self.send_directory(tmp_dir, src_path)

    def send_directory(
        self,
        tmp_dir,
        original_path,
        use_tar_archives=True,
        split_size: Optional[int] = None,
    ):
        config = self.get_config(
            tmp_dir, use_tar_archives=use_tar_archives, split_size=split_size
        )
        src_path = os.path.join(tmp_dir, "original_copy")
        shutil.copytree(original_path, src_path)
        dst_path = os.path.join(tmp_dir, "destination")
        receiver = SingleDirReceiver(config, dst_path)
        process_thread = Thread(target=receiver.loop, args=())
        process_thread.start()
        time.sleep(1.0)
        sender = SingleDirSender(config, src_path)
        sender.prepare_directory()
        sender.send_directory()
        self.assertEqual(
            list(sorted(os.listdir(original_path))), list(sorted(os.listdir(dst_path)))
        )
        for filename in os.listdir(original_path):
            src_filename = os.path.join(original_path, filename)
            dst_filename = os.path.join(dst_path, filename)
            if os.path.isdir(src_filename):
                continue
            with open(src_filename, "rb") as fd:
                src_content = fd.read()
            with open(dst_filename, "rb") as fd:
                dst_content = fd.read()
            self.assertTrue(os.path.isfile(dst_filename))
            self.assertEqual(src_content, dst_content)

    @staticmethod
    def get_config(
        tmp_dir, use_tar_archives: bool = False, split_size: Optional[int] = None
    ):
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

    @staticmethod
    def receive_file(config: Config, tmp_path):
        Receiver(config).receive_file(tmp_path)
