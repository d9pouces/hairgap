"""
Receive data from hairgap using a proprietary protocol.
The algorithm is simple:

.. code-block: python

    while True:
        receive_file()
        process_file()


`receive_file` launches the command hairgapr that waits for a transfer and exists when a file is received.
`process_file` read the first bytes of the file
    - if they match HAIRGAP_MAGIC_NUMBER_INDEX, then this is an index file, with:
        - the transfer identifier
        - the previous transfer identifier
        - the list of following files and their sha256 (in the transfer order)
    - otherwise, this is the next expected file, as read by the index file

Empty files cannot be sent by hairgap, so they are replaced by the HAIRGAP_MAGIC_NUMBER_EMPTY constant.
If a new index file is read before the last expected file of the previous index, then we start a new index:
we assume that the sender has been interrupted and has restarted the whole process.

A 5-second sleep (HAIRGAP_END_DELAY_S) is performed by the sender after each send.

Both functions can be serialized (only if we assume that the process_file function takes less than 5 seconds),
but can also be run in separate threads for handling large files.

"""
# ##############################################################################
#  This file is part of Interdiode                                             #
#                                                                              #
#  Copyright (C) 2020 Matthieu Gallet <matthieu.gallet@19pouces.net>           #
#  All Rights Reserved                                                         #
#                                                                              #
# ##############################################################################

import datetime
import hashlib
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
from queue import Empty, Queue
from threading import Thread
from typing import Dict, Optional, Set

from hairgap.constants import (
    HAIRGAP_MAGIC_NUMBER_EMPTY,
    HAIRGAP_MAGIC_NUMBER_ESCAPE,
    HAIRGAP_MAGIC_NUMBER_INDEX,
)
from hairgap.utils import Config, ensure_dir, now, FILENAME_PATTERN

logger = logging.getLogger("hairgap")


class Receiver:
    available_attributes = set()  # type: Set[str]

    def __init__(self, config: Config, threading: bool = False, port: int = None):
        """wait for transfer files

        :param config:
        :param threading: run the two main functions in threads.
        :param port: override the configured port
        """
        self.config = config
        self.threading = threading
        self.port = port  # type: int
        self.process_queue = Queue()
        self.process_thread = None
        self.receive_thread = None
        self.continue_loop = True  # type: bool
        self.hairgap_subprocess = None

        self.expected_files = Queue()
        self.transfer_start_time = None  # type: Optional[datetime.datetime]
        # datetime of the last index read
        self.transfer_received_size = 0  # type: int
        # sum of the size of the received files since the last index read (excepting the index)
        self.transfer_success_count = 0  # type: int
        # number of successfully received files (since the last index read)
        self.transfer_error_count = 0  # type: int
        # number of unsuccessfully received files (since the last index read)
        self.transfer_received_count = 0  # type: int
        # number of received files
        # transfer_received_count <= transfer_error_count +  transfer_success_count
        # == 0 if there are errors in hairgap (and no file has been created)
        self.current_attributes = {}  # type: Dict[str, str]
        # attributes of the last index

    def receive_file(self, tmp_path) -> Optional[bool]:
        """receive a single file and returns
        True if hairgap did not raise an error
        False if hairgap did raise an error but Ctrl-C
        None if hairgap was terminated by Ctrl-C
        """
        logger.info("Receiving %s via hairgap…" % tmp_path)
        ensure_dir(tmp_path, parent=True)
        with open(tmp_path, "wb") as fd:
            cmd = [
                self.config.hairgapr_path,
                "-p",
                str(self.port or self.config.destination_port),
            ]
            if self.config.timeout_s:
                cmd += ["-t", str(self.config.timeout_s)]
            if self.config.mem_limit_mb:
                cmd += ["-m", str(self.config.mem_limit_mb)]
            cmd.append(self.config.destination_ip)
            self.hairgap_subprocess = subprocess.Popen(
                cmd, stdout=fd, stderr=subprocess.PIPE
            )
            __, stderr = self.hairgap_subprocess.communicate()
            fd.flush()
        returncode = self.hairgap_subprocess.returncode
        if returncode == 0:
            self.hairgap_subprocess = None
            logger.info("%s received via hairgap." % tmp_path)
            return True
        if returncode == -2:
            logger.info("Exiting hairgap…")
            return None
        else:
            logger.warning(
                "An error %d was encountered by hairgap: \n%s"
                % (returncode, stderr.decode())
            )
        self.hairgap_subprocess = None
        return False

    def receive_loop(self):
        logger.info("Entering receiving loop…")
        while self.continue_loop:
            tmp_abspath = os.path.join(
                self.config.destination_path, "receiving", str(uuid.uuid4())
            )
            try:
                r = self.receive_file(tmp_abspath)
            except Exception as e:
                logger.exception(e)
                time.sleep(1)
                continue
            if r is None:  # Ctrl-C
                if os.path.isfile(tmp_abspath):
                    os.remove(tmp_abspath)
                continue
            elif not r:
                time.sleep(1)
            if self.threading:
                self.process_queue.put((bool(r), tmp_abspath))
            else:
                self.process_received_file(tmp_abspath)
        logger.info("Receiving loop exited.")

    def process_loop(self):
        logger.info("Entering processing loop…")
        while self.continue_loop:
            try:
                valid, tmp_abspath = self.process_queue.get(timeout=1)
                self.process_received_file(tmp_abspath)
            except Empty:
                # the timeout is required to quit the thread when self.continue_loop is False
                continue
            except Exception as e:
                logger.exception(e)
                time.sleep(1)
        logger.info("Processing loop exited.")

    def process_received_file(self, tmp_abspath: str, valid: bool = True):
        """
        process a received file
        the execution time of this method must be small when threading is False (5 seconds between two communications)
        => must be threaded when large files are processed since we compute their sha256.

        :param tmp_abspath:
        :param valid:
        :return:
        """
        empty_prefix = HAIRGAP_MAGIC_NUMBER_EMPTY.encode()
        index_prefix = HAIRGAP_MAGIC_NUMBER_INDEX.encode()
        escape_prefix = HAIRGAP_MAGIC_NUMBER_ESCAPE.encode()
        if os.path.isfile(tmp_abspath):
            with open(tmp_abspath, "rb") as fd:
                prefix = fd.read(len(empty_prefix))
        else:
            prefix = b""
        if prefix == escape_prefix:  # must be done before the sha256
            escaped_tmp_abspath = tmp_abspath + ".b"
            with open(escaped_tmp_abspath, "wb") as fd_out:
                with open(tmp_abspath, "rb") as fd_in:
                    fd_in.read(len(escape_prefix))
                    for data in iter(lambda: fd_in.read(65536), b""):
                        fd_out.write(data)
            os.rename(escaped_tmp_abspath, tmp_abspath)  # no need to use shutil.move
        if prefix == empty_prefix:
            open(tmp_abspath, "w").close()
        if prefix == index_prefix:
            self.read_index(tmp_abspath)
            os.remove(tmp_abspath)
            self.transfer_start()
            if self.expected_files.empty():
                # empty transfer => we mark it as complete
                self.transfer_complete()
        elif self.expected_files.empty():
            if valid:
                self.transfer_file_unexpected(tmp_abspath, prefix=prefix)
            elif os.path.isfile(tmp_abspath):
                os.remove(tmp_abspath)
        else:
            expected_sha256, file_relpath = self.expected_files.get()
            actual_sha256_obj = hashlib.sha256()
            if os.path.isfile(tmp_abspath):
                with open(tmp_abspath, "rb") as in_fd:
                    for data in iter(lambda: in_fd.read(65536), b""):
                        actual_sha256_obj.update(data)
            self.transfer_file_received(
                tmp_abspath,
                file_relpath,
                actual_sha256=actual_sha256_obj.hexdigest(),
                expected_sha256=expected_sha256,
            )
            if self.expected_files.empty():
                # all files of the transfer have been received
                self.transfer_complete()

    def transfer_start(self):
        """called before the first file of a transfer

        the execution time of this method must be small when threading is False (5 seconds between two communications)

        """
        pass

    def transfer_complete(self):
        """called when all files of a transfer are received.

        the execution time of this method must be small when threading is False (5 seconds between two communications)

        """
        pass

    def get_current_transfer_directory(self) -> Optional[str]:
        """return a folder name where all files of a transfer can be moved to.
        This folder will be automatically created.
        If None, all received files will be deleted.
        """
        raise NotImplementedError

    # noinspection PyMethodMayBeStatic
    def transfer_file_unexpected(self, tmp_abspath: str, prefix: bytes = None):
        """called when an unexpected file has been received. Probably an interrupted transfer…

        :param tmp_abspath: absolute path of the received file
        :param prefix: is the first bytes of the received file."""
        if prefix is None:
            logger.error("Unexpected file received")
        else:
            logger.error("Unexpected file received, starting by %r." % prefix)
        if os.path.isfile(tmp_abspath):
            os.remove(tmp_abspath)

    def transfer_file_received(
        self,
        tmp_abspath,
        file_relpath,
        actual_sha256: str = None,
        expected_sha256: str = None,
    ):
        """called when a file is received

        the execution time of this method must be small if threading is False (5 seconds between two communications)

        :param tmp_abspath: the path of the received file
        :param file_relpath: the destination path of the received file
        :param actual_sha256: actual SHA256
        :param expected_sha256: expected SHA256
        :return:
        """
        if os.path.isfile(tmp_abspath):
            size = os.path.getsize(tmp_abspath)
            self.transfer_received_count += 1
            receive_path = self.get_current_transfer_directory()
            if receive_path:
                file_abspath = os.path.join(receive_path, file_relpath)
                ensure_dir(file_abspath, parent=True)
                shutil.move(tmp_abspath, file_abspath)
            else:
                logger.warning("No receive path defined: removing %s." % tmp_abspath)
                os.remove(tmp_abspath)
        else:
            size = 0
        self.transfer_received_size += size
        values = {
            "f": file_relpath,
            "as": actual_sha256,
            "es": expected_sha256,
            "s": size,
        }
        if actual_sha256 == expected_sha256:
            logger.info("Received file %(f)s [sha256=%(es)s, size=%(s)s]." % values)
            self.transfer_success_count += 1
        else:
            logger.warning(
                "Received file %(f)s [sha256=%(as)s instead of sha256=%(es)s, size=%(s)s]."
                % values
            )
            self.transfer_error_count += 1

    def read_index(self, index_abspath):
        self.transfer_start_time = now()
        logger.info("Reading received index…")
        self.current_attributes = {x: None for x in self.available_attributes}

        self.expected_files = Queue()
        expected_count = 0
        with open(index_abspath) as fd:
            for line in fd:
                matcher = re.match(FILENAME_PATTERN, line)
                if matcher:
                    self.expected_files.put((matcher.group(1), matcher.group(2)))
                    expected_count += 1
                    continue
                matcher = re.match(r"^(.+) = (.+)$", line)
                if matcher:
                    key, value = matcher.groups()
                    if key in self.available_attributes:
                        self.current_attributes[key] = value
                    continue
        self.transfer_received_size = os.path.getsize(index_abspath)
        self.transfer_received_count = 1
        self.transfer_success_count = 1
        self.transfer_error_count = 0
        logger.info("Index read: expecting %s file(s)." % expected_count)

    def loop(self):
        if self.threading:
            self.process_thread = Thread(target=self.process_loop)
            self.process_thread.start()
            self.receive_thread = Thread(target=self.receive_loop)
            self.receive_thread.start()
            self.receive_thread.join()
            self.process_thread.join()
        else:
            self.receive_loop()
