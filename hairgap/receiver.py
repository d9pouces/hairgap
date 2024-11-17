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

import datetime
import hashlib
import io
import logging
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
from queue import Empty, Queue
from threading import Thread
from typing import Dict, Optional, Set, List

from hairgap.constants import (
    HAIRGAP_MAGIC_NUMBER_EMPTY,
    HAIRGAP_MAGIC_NUMBER_ESCAPE,
    HAIRGAP_MAGIC_NUMBER_INDEX,
)
from hairgap.utils import FILENAME_PATTERN, Config, ensure_dir, now

logger = logging.getLogger(__name__)


class Receiver:
    """
    define the reception process. Can be split into two threads or can be serialize operations when files are small enough.
    You just have to call the `loop` method to start the reception process.
    Basically, the algorithm is:

    .. code-block:: python

        while True:
            receive_file(temporary_filepath)
            if is_index_file(temporary_filepath):
                read_list_of_expected_filenames()
            else:
                filename = expected_filenames.pop()
                os.rename(temporary_filepath, filename)


    """

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
        self.current_split_status = False
        # is the last transfer split into chunks?

    def receive_file(self, tmp_path) -> Optional[bool]:
        """receive a single file and returns
        True if hairgap did not raise an error
        False if hairgap did raise an error but Ctrl-C
        None if hairgap was terminated by Ctrl-C
        """
        logger.info("receiving '%s' via hairgap…", tmp_path)
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
            logger.debug("hairgapr command: '%s'.", " ".join(cmd))
            __, stderr = self.hairgap_subprocess.communicate()
            fd.flush()
        returncode = self.hairgap_subprocess.returncode
        if returncode == 0:
            self.hairgap_subprocess = None
            logger.info("'%s' received via hairgap.", tmp_path)
            return True
        if returncode == -2:
            logger.info("exiting hairgap…")
            return None
        else:
            logger.warning(
                "an error %d was encountered by hairgap: \n%s",
                returncode,
                stderr.decode(),
            )
        self.hairgap_subprocess = None
        return False

    def receive_loop(self):
        logger.info("entering receiving loop…")
        while self.continue_loop:
            tmp_abspath = self.get_reception_filepath()
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
        logger.info("receiving loop exited.")

    def get_reception_filepath(self):
        return os.path.join(
            self.config.destination_path, "receiving", str(uuid.uuid4())
        )

    def process_loop(self):
        logger.info("entering processing loop…")
        while self.continue_loop:
            try:
                valid, tmp_abspath = self.process_queue.get(timeout=1)
                self.process_received_file(tmp_abspath, valid=valid)
            except Empty:
                # the timeout is required to quit the thread when self.continue_loop is False
                continue
            except Exception as e:
                logger.exception("an error has been encountered: %s", e)
                time.sleep(1)
        logger.info("processing loop exited.")

    @staticmethod
    def is_gz_file(tmp_abspath: str):
        if not os.path.isfile(tmp_abspath):
            return False
        with open(tmp_abspath, "rb") as fd:
            header = fd.read(4)
        return header[:4] == b"\x1f\x8b\x08\x00"

    def process_received_file(self, tmp_abspath: str, valid: bool = True):
        """
        process a received file
        the execution time of this method must be small when threading is False (5 seconds between two communications)
        => must be threaded when large files are processed since we compute their sha256.

        :param tmp_abspath: the temporary absolute path
        :param valid: the file has been correctly received by hairgap
        :return:
        """
        if self.config.use_tar_archives or (
            self.config.use_tar_archives is None  # auto-detect mode
            and self.expected_files.empty()
            and self.is_gz_file(tmp_abspath)
        ):
            try:
                self.process_received_file_tar(tmp_abspath, valid=valid)
            except Exception as e:
                logger.exception(
                    "invalid tar.gz  '%s' file (removed): %s.", tmp_abspath, e
                )
                if os.path.isfile(tmp_abspath):
                    os.remove(tmp_abspath)
        else:
            self.process_received_file_no_tar(tmp_abspath, valid=valid)

    def process_received_file_tar(self, tmp_abspath: str, valid: bool = True):
        """
        process a tar.gz archive.
        a single file and a single directory are expected at the root of the received archive

        :param tmp_abspath:
        :param valid:

        :return:
        """
        if not valid:
            if os.path.isfile(tmp_abspath):
                os.remove(tmp_abspath)
            return
        with tarfile.open(name=tmp_abspath, mode="r:gz") as tar_fd:
            index_member = None
            for member in tar_fd.getmembers():  # type: tarfile.TarInfo
                if "/" not in member.name and member.isfile():
                    index_member = member
                    break
            if index_member is None:
                logger.error("index file not found in '%s'.", tmp_abspath)
                return
            # /!\ the index file must be read before extracting other files
            with tempfile.NamedTemporaryFile() as dst_fd:
                src_fd = tar_fd.extractfile(index_member)
                for data in iter(lambda: src_fd.read(8192), b""):
                    dst_fd.write(data)
                src_fd.close()
                dst_fd.flush()
                self.read_index(dst_fd.name)
            self.transfer_start()
            count = 0
            for member in tar_fd.getmembers():  # type: tarfile.TarInfo
                if not member.isfile() or member.issym():
                    continue
                root, sep, rel_path = member.name.partition("/")
                if sep != "/":  # the index file => we ignore it
                    continue
                self.transfer_file_received(
                    tmp_abspath,
                    rel_path,
                    expected_sha256=None,
                    actual_sha256=None,
                    tmp_fd=tar_fd.extractfile(member),
                )
                count += 1
            if count == 0:
                ensure_dir(self.get_current_transfer_directory(), parent=False)
            self.transfer_complete()
        os.remove(tmp_abspath)

    def process_received_file_no_tar(self, tmp_abspath: str, valid: bool = True):
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
                ensure_dir(self.get_current_transfer_directory(), parent=False)
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
                if self.current_split_status:
                    self.unsplit_received_files(
                        self.config, self.get_current_transfer_directory()
                    )
                self.transfer_complete()

    def transfer_start(self):
        """called before the first file of a transfer

        the execution time of this method must be small when threading is False (5 seconds between two communications)

        """
        pass

    def transfer_complete(self):
        """called when all files of a transfer are received.

        the execution time of this method must be small when threading is False (5 seconds between two communications)
        You can read :attr:`current_attributes` to retrieve the attributes defined by the sender (set to `None` by default).

        """
        pass

    def get_current_transfer_directory(self) -> Optional[str]:
        """return a folder name where all files of a transfer can be moved to.

        The index file has been read and the attributes are set.
        This folder will be automatically created.
        If None, all received files will be deleted.
        """
        raise NotImplementedError

    @staticmethod
    def unsplit_received_files(config: Config, dir_abspath):
        names: List[str] = os.listdir(dir_abspath)
        if not names:
            return
        folder_1 = os.path.join(dir_abspath, str(uuid.uuid4()))
        folder_2 = os.path.join(dir_abspath, str(uuid.uuid4()))
        ensure_dir(folder_1, parent=False)
        ensure_dir(folder_2, parent=False)
        for name in names:
            os.rename(os.path.join(dir_abspath, name), os.path.join(folder_1, name))
        names.sort()
        cat_cmd = [config.cat] + names
        tar_cmd = [config.tar, "xz", "-C", folder_2]
        esc_tar_cmd = [shlex.quote(x) for x in tar_cmd]
        esc_cat_cmd = [shlex.quote(x) for x in cat_cmd]
        cmd = "%s | %s" % (" ".join(esc_cat_cmd), " ".join(esc_tar_cmd))
        p = subprocess.Popen(
            cmd,  # nosec
            shell=True,  # nosec
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            cwd=folder_1,
        )
        stdout, stderr = p.communicate(b"")
        if p.returncode:
            logger.error("command = %s , return code = %s", cmd, p.returncode)
            logger.error("stdout = %s\nstderr = %s", stdout.decode(), stderr.decode())
        names = os.listdir(folder_2)
        for name in names:
            os.rename(os.path.join(folder_2, name), os.path.join(dir_abspath, name))
        shutil.rmtree(folder_1)
        shutil.rmtree(folder_2)

    # noinspection PyMethodMayBeStatic
    def transfer_file_unexpected(self, tmp_abspath: str, prefix: bytes = None):
        """called when an unexpected file has been received. Probably an interrupted transfer…

        :param tmp_abspath: absolute path of the received file
        :param prefix: is the first bytes of the received file."""
        if prefix is None:
            logger.error("unexpected file received")
        else:
            logger.error("unexpected file received, starting by %r.", prefix)
        if os.path.isfile(tmp_abspath):
            os.remove(tmp_abspath)

    def transfer_file_received(
        self,
        tmp_abspath,
        file_relpath,
        actual_sha256: Optional[str] = None,
        expected_sha256: Optional[str] = None,
        tmp_fd: io.BytesIO = None,
    ):
        """called when a file is received

        the execution time of this method must be small if threading is False (5 seconds between two communications)

        :param tmp_abspath: the path of the received file
        :param file_relpath: the destination path of the received file
        :param actual_sha256: actual SHA256 (not provided in case of tar archives)
        :param expected_sha256: expected SHA256 (not provided in case of tar archives)
        :param tmp_fd: provided when tmp_abspath is not given
        :return:
        """
        if tmp_fd:
            receive_path = self.get_current_transfer_directory()
            self.transfer_received_count += 1
            size = 0
            if receive_path:
                file_abspath = os.path.join(receive_path, file_relpath)
                ensure_dir(file_abspath, parent=True)
                with open(file_abspath, "wb") as dst_fd:
                    for data in iter(lambda: tmp_fd.read(8192), b""):
                        dst_fd.write(data)
                        size += len(data)
                    tmp_fd.close()
            else:
                logger.warning("no receive path defined: ignoring '%s'.", file_relpath)
        elif os.path.isfile(tmp_abspath):
            size = os.path.getsize(tmp_abspath)
            self.transfer_received_count += 1
            receive_path = self.get_current_transfer_directory()
            if receive_path:
                file_abspath = os.path.join(receive_path, file_relpath)
                ensure_dir(file_abspath, parent=True)
                shutil.move(tmp_abspath, file_abspath)
            else:
                logger.warning("no receive path defined: removing '%s'.", tmp_abspath)
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
            logger.info("received file %(f)s [sha256=%(es)s, size=%(s)s]." % values)
            self.transfer_success_count += 1
        else:
            logger.warning(
                "received file %(f)s [sha256=%(as)s instead of sha256=%(es)s, size=%(s)s]."
                % values
            )
            self.transfer_error_count += 1

    def read_index(self, index_abspath):
        self.transfer_start_time = now()
        logger.info("reading received index…")
        self.current_attributes = {x: None for x in self.available_attributes}

        self.expected_files = Queue()
        expected_count = 0
        self.current_split_status = False
        with open(index_abspath) as fd:
            for line in fd:
                if line == "[splitted_content]\n":
                    self.current_split_status = True
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
        logger.info("index read: expecting %s file(s).", expected_count)

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
