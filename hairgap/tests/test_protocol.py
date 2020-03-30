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

# ##############################################################################
#  This file is part of Interdiode                                             #
#                                                                              #
#  Copyright (C) 2020 Matthieu Gallet <matthieu.gallet@19pouces.net>           #
#  All Rights Reserved                                                         #
#                                                                              #
# ##############################################################################

import hashlib
import os
import random
import tempfile
import time
import uuid
from tempfile import TemporaryDirectory
from threading import Thread
from typing import Optional, Dict
from unittest import TestCase

import pkg_resources

from hairgap.constants import (
    HAIRGAP_MAGIC_NUMBER_EMPTY,
    HAIRGAP_MAGIC_NUMBER_ESCAPE,
    HAIRGAP_MAGIC_NUMBER_INDEX,
)
from hairgap.receiver import Receiver
from hairgap.sender import DirectorySender
from hairgap.utils import ensure_dir, Config, now


class SingleDirReceiver(Receiver):
    available_attributes = {"current_uid", "previous_uid", "title", "url", "creation"}

    def __init__(
        self,
        transfer_path: str,
        config: Config,
        threading: bool = False,
        port: int = None,
    ):
        super().__init__(config, threading=threading, port=port)
        self.transfer_path = transfer_path

    def transfer_complete(self):
        super().transfer_complete()
        self.continue_loop = False

    def get_current_transfer_directory(self) -> Optional[str]:
        if not self.current_attributes["current_uid"]:
            return None
        return os.path.join(self.transfer_path, "reception")


class TestSender(DirectorySender):
    def __init__(self, config: Config, directory_path: str, index_path: str):
        super().__init__(config)
        self.directory_path = directory_path
        self.index_path = index_path
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
            src_path = pkg_resources.resource_filename("hairgap.tests", "__init__.py")
            dst_path = os.path.join(tmp_dir, "received.txt")

            process_thread = Thread(target=self.receive_file, args=(config, dst_path,))
            process_thread.start()
            time.sleep(1.0)
            sender = TestSender(
                config,
                os.path.join(tmp_dir, "to_send"),
                os.path.join(tmp_dir, "to_send.txt"),
            )
            sender.send_file(config, src_path)
            time.sleep(1.0)
            self.assertTrue(os.path.isfile(dst_path))
            with open(src_path) as fd:
                expected_content = fd.read()
            with open(dst_path) as fd:
                actual_content = fd.read()
            self.assertEqual(expected_content, actual_content)

    def test_create_transfer(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = self.get_config(tmp_dir)

            input_abspath = os.path.join(tmp_dir, "test-directory")
            ensure_dir(input_abspath + "/subdir", parent=False)
            with open(os.path.join(input_abspath, "test-file-1.txt"), "w") as fd:
                fd.write("TEST-1\n")

            with open(
                os.path.join(input_abspath, "subdir", "test-file-2.txt"), "w"
            ) as fd:
                fd.write("TEST-2\n")
            transfer = DiodeTransfer.create_transfer(input_abspath)
            self.assertEqual(
                ["test-file-1.txt", "subdir"], os.listdir(transfer.transfer_abspath)
            )
            self.assertTrue(os.path.isfile(transfer.transfer_abspath + ".ini"))
            self.assertFalse(os.path.exists(input_abspath))
            with open(transfer.transfer_abspath + ".ini") as fd:
                content = fd.read()

            actual_lines = content.splitlines()
            self.assertTrue(actual_lines[2].startswith("creation = "))
            del actual_lines[2]  # remove the creation date
            expected_lines = [
                "# *-* HAIRGAP-INDEX *-*",
                "[hairgap]",
                "current_uid = %s" % transfer.uid,
                "[files]",
                "f1a75678168b3b1edab3a49011e3f8fe9af8736af4a67da9494e4c431761defb = test-file-1.txt",
                "a420777344bf67a8a2c8b7686e89c6b55146fe6d93020ef073fdab7ba311941b = subdir/test-file-2.txt",
            ]
            self.assertEqual(expected_lines, actual_lines)

    @staticmethod
    def get_config(tmp_dir):
        return Config(
            destination_ip="localhost",
            destination_port=15124,
            destination_path=os.path.join(tmp_dir, "destination"),
            end_delay_s=3.0,
            error_chunk_size=None,
            keepalive_ms=500,
            max_rate_mbps=None,
            mem_limit_mb=None,
            mtu_b=None,
            timeout_s=3.0,
            redundancy=3.0,
            hairgapr=pkg_resources.resource_filename("hairgap.tests", "hairgapr.py"),
            hairgaps=pkg_resources.resource_filename("hairgap.tests", "hairgaps.py"),
        )

    @staticmethod
    def receive_file(config: Config, tmp_path):
        Receiver(config).receive_file(tmp_path)

    def test_receiver(self):
        with PatchSettings(
            HAIRGAP_PATH_S=None,
            HAIRGAP_PATH_R=None,
            HAIRGAP_KEEP_TRANSFERS=None,
            TRANSFER_PATH=None,
            HAIRGAP_DESTINATION_PORT=16100,
        ):
            start_time = now()
            current_uid = str(uuid.uuid4())
            previous_uid = str(uuid.uuid4())

            receiver = TransferReceiver(hairgap_config)
            receiver.transfer_start_time = start_time
            url = "/v1/transfers/<id>"
            title = "Transfer title"
            receiver.current_attributes = {
                "current_uid": current_uid,
                "previous_uid": previous_uid,
                "title": title,
                "url": url,
                "creation": start_time.strftime("%Y-%m-%dT%H:%M:%s"),
            }
            receiver.transfer_received_size = 0
            receiver.transfer_success_count = 0
            receiver.transfer_received_count = 0
            receiver.transfer_error_count = 0
            with tempfile.TemporaryDirectory() as tmp_dir:
                settings.HAIRGAP_PATH_R = os.path.join(tmp_dir, "receive")
                settings.HAIRGAP_PATH_S = os.path.join(tmp_dir, "send")
                settings.TRANSFER_PATH = os.path.join(tmp_dir, "transfers")
                self.assertEqual(
                    0, DiodeTransfer.objects.filter(uid=current_uid).count()
                )
                self.assertEqual(
                    0, DiodeTransfer.objects.filter(uid=previous_uid).count()
                )
                receiver.transfer_start()
                self.assertEqual(
                    1, DiodeTransfer.objects.filter(uid=current_uid).count()
                )

                expected = {
                    "state": TRANSFER_SENDING,
                    "size": 0,
                    "count": 0,
                    "start": start_time,
                    "end": None,
                    "duration": None,
                    "title": title,
                    "url": url,
                    "previous_transfer_id": None,
                }
                self.assertEqual(
                    expected,
                    DiodeTransfer.objects.filter(uid=current_uid)
                    .values(*expected)
                    .first(),
                )

                tmp_abspath = os.path.join(settings.HAIRGAP_PATH_R, str(uuid.uuid4()))
                ensure_dir(tmp_abspath, parent=True)
                content = b"TEST\n"
                with open(tmp_abspath, "wb") as fd:
                    fd.write(content)
                sha256 = hashlib.sha256(content).hexdigest()

                receiver.transfer_file_received(
                    tmp_abspath,
                    "dir/test",
                    expected_sha256=sha256,
                    actual_sha256=sha256,
                )
                expected = {
                    "state": TRANSFER_SENDING,
                    "size": 5,
                    "count": 1,
                    "start": start_time,
                    "end": None,
                    "duration": None,
                    "title": title,
                    "url": url,
                    "previous_transfer_id": None,
                }
                self.assertEqual(
                    expected,
                    DiodeTransfer.objects.filter(uid=current_uid)
                    .values(*expected)
                    .first(),
                )
                self.assertTrue(
                    os.path.isfile(
                        os.path.join(settings.HAIRGAP_PATH_R, current_uid, "dir/test")
                    )
                )

                receiver.transfer_complete()
                end_time = now()
                expected = {
                    "state": TRANSFER_RECEIVED,
                    "size": 5,
                    "count": 1,
                    "start": start_time,
                    "duration": 0,
                    "title": title,
                    "url": url,
                    "previous_transfer_id": uuid.UUID(previous_uid),
                }
                self.assertEqual(
                    expected,
                    DiodeTransfer.objects.filter(uid=current_uid)
                    .values(*expected)
                    .first(),
                )
                self.assertEqual([], os.listdir(os.path.join(settings.HAIRGAP_PATH_R)))
                self.assertEqual(
                    [current_uid], os.listdir(os.path.join(settings.TRANSFER_PATH))
                )
                self.assertLessEqual(
                    DiodeTransfer.objects.filter(uid=current_uid)
                    .values_list("end", flat=True)
                    .first(),
                    end_time,
                )
                self.assertEqual(
                    1, DiodeTransfer.objects.filter(uid=previous_uid).count()
                )

    def test_complete_process(self):
        with PatchSettings(
            HAIRGAP_PATH_S=None,
            HAIRGAP_PATH_R=None,
            HAIRGAP_KEEP_TRANSFERS=None,
            TRANSFER_PATH=None,
            HAIRGAP_DESTINATION_PORT=16100,
        ):
            with tempfile.TemporaryDirectory() as tmp_dir:
                settings.HAIRGAP_PATH_R = os.path.join(tmp_dir, "receive")
                settings.HAIRGAP_PATH_S = os.path.join(tmp_dir, "send")
                settings.HAIRGAP_KEEP_TRANSFERS = False
                input_abspath = os.path.join(tmp_dir, "test-directory")
                ensure_dir(input_abspath + "/subdir", parent=False)
                with open(os.path.join(input_abspath, "test-file-1.txt"), "w") as fd:
                    fd.write("TEST-1\n")
                contents = [
                    (
                        "test-file-index.txt",
                        HAIRGAP_MAGIC_NUMBER_INDEX + str(random.randint(10000, 90000)),
                    ),
                    (
                        "test-file-empty.txt",
                        HAIRGAP_MAGIC_NUMBER_EMPTY + str(random.randint(10000, 90000)),
                    ),
                    (
                        "test-file-escape.txt",
                        HAIRGAP_MAGIC_NUMBER_ESCAPE + str(random.randint(10000, 90000)),
                    ),
                ]
                for name, content in contents:
                    with open(os.path.join(input_abspath, "subdir", name), "w") as fd:
                        fd.write(content)
                self.receiver = SingleDirReceiver(hairgap_config)
                # cannot use the actual TransferReceiver since we use several threads (and the ORM will block queries)
                before_start = now()
                process_thread = Thread(target=self.receiver.loop)
                process_thread.start()
                time.sleep(2.0)
                transfer = DiodeTransfer.create_transfer(
                    input_abspath, url="/v1/url/<id>", title="test transfer"
                )
                self.assertEqual(2, len(os.listdir(settings.HAIRGAP_PATH_S)))
                # the directory to transfer and the index file
                transfer.send()
                self.assertEqual(0, len(os.listdir(settings.HAIRGAP_PATH_S)))
                time.sleep(2.0)
                after_start = now()
                actual_dir_content = os.listdir(settings.HAIRGAP_PATH_R)
                actual_dir_content.sort()
                self.assertEqual([str(transfer.uid), "receiving"], actual_dir_content)
                actual_dir_content = os.listdir(
                    os.path.join(settings.HAIRGAP_PATH_R, str(transfer.uid))
                )
                actual_dir_content.sort()
                self.assertEqual(["subdir", "test-file-1.txt"], actual_dir_content)
                actual_subdir_content = os.listdir(
                    os.path.join(settings.HAIRGAP_PATH_R, str(transfer.uid), "subdir")
                )
                actual_subdir_content.sort()
                self.assertEqual(
                    list(sorted([x[0] for x in contents])), actual_subdir_content,
                )
                for name, content in contents:
                    with open(
                        os.path.join(
                            settings.HAIRGAP_PATH_R, str(transfer.uid), "subdir", name,
                        ),
                        "r",
                    ) as fd:
                        self.assertEqual(content, fd.read())

                actual_dir_content = os.listdir(
                    os.path.join(settings.HAIRGAP_PATH_R, "receiving")
                )
                self.assertEqual([], actual_dir_content)

                self.assertTrue(
                    before_start < self.receiver.transfer_start_time < after_start
                )
                self.assertEqual(
                    {
                        "previous_uid": None,
                        "current_uid": str(transfer.uid),
                        "url": "/v1/url/<id>",
                        "title": "test transfer",
                        "creation": transfer.creation_date.strftime(
                            "%Y-%m-%dT%H:%M:%s"
                        ),
                    },
                    self.receiver.current_attributes,
                )
                self.assertEqual(633, self.receiver.transfer_received_size)
                self.assertEqual(5, self.receiver.transfer_success_count)
                self.assertEqual(5, self.receiver.transfer_received_count)
                self.assertEqual(0, self.receiver.transfer_error_count)

    def test_send_empty_file(self):
        with PatchSettings(
            HAIRGAP_PATH_S=None,
            HAIRGAP_PATH_R=None,
            HAIRGAP_KEEP_TRANSFERS=None,
            TRANSFER_PATH=None,
            HAIRGAP_DESTINATION_PORT=16100,
        ):
            with TemporaryDirectory() as dirname:
                dst_path = os.path.join(dirname, "received.txt")
                src_path = os.path.join(dirname, "sent.txt")
                open(src_path, "w").close()
                process_thread = Thread(target=self.receive_file, args=(dst_path,))
                process_thread.start()
                time.sleep(2.0)
                DiodeTransfer.send_file(hairgap_config, src_path)
                time.sleep(2.0)
                self.assertTrue(os.path.isfile(dst_path))
                with open(dst_path) as fd:
                    actual_content = fd.read()
                self.assertEqual(HAIRGAP_MAGIC_NUMBER_EMPTY, actual_content)

    def test_send_large_file(self):
        with PatchSettings(
            HAIRGAP_PATH_S=None,
            HAIRGAP_PATH_R=None,
            HAIRGAP_KEEP_TRANSFERS=None,
            TRANSFER_PATH=None,
            HAIRGAP_DESTINATION_PORT=16100,
        ):
            with TemporaryDirectory() as dirname:
                dst_path = os.path.join(dirname, "received.txt")
                src_path = os.path.join(dirname, "sent.txt")
                with open(src_path, "w") as fd:
                    for index in range(10 * 1000 * 1000):
                        fd.write("%09d\n" % index)
                    fd.flush()

                expected_sha256 = hashlib.sha256()
                with open(src_path, "rb") as in_fd:
                    for data in iter(lambda: in_fd.read(65536), b""):
                        expected_sha256.update(data)
                expected_sha256_str = expected_sha256.hexdigest()
                self.assertEqual(
                    "b9af55566e94f51477475a55a523ea5d9ad29c4f9288e6e42066117535851831",
                    expected_sha256_str,
                )

                process_thread = Thread(target=self.receive_file, args=(dst_path,))
                process_thread.start()
                time.sleep(2.0)
                DiodeTransfer.send_file(hairgap_config, src_path)
                time.sleep(2.0)
                self.assertTrue(os.path.isfile(dst_path))

                actual_sha256 = hashlib.sha256()
                with open(src_path, "rb") as in_fd:
                    for data in iter(lambda: in_fd.read(65536), b""):
                        actual_sha256.update(data)
                actual_sha256_str = expected_sha256.hexdigest()

                self.assertEqual(expected_sha256_str, actual_sha256_str)
