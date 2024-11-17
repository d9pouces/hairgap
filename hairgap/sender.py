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

import hashlib
import logging
import os
import random
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid
from typing import Dict, Optional, Tuple

from hairgap.constants import (
    HAIRGAP_MAGIC_NUMBER_EMPTY,
    HAIRGAP_MAGIC_NUMBER_ESCAPE,
    HAIRGAP_MAGIC_NUMBER_INDEX,
)
from hairgap.utils import FILENAME_PATTERN, Config, ensure_dir

logger = logging.getLogger(__name__)

HAIRGAP_PREFIXES = {
    HAIRGAP_MAGIC_NUMBER_INDEX.encode(),
    HAIRGAP_MAGIC_NUMBER_EMPTY.encode(),
    HAIRGAP_MAGIC_NUMBER_ESCAPE.encode(),
}


class DirectorySender:
    """
    Send the content of a directory. Must be subclassed to implement `transfer_abspath` and `index_abspath`.

    .. code-block:: python

        sender = DirectorySender(Config())
        sender.prepare_directory()
        # modify in-place the data directory! generate the index file
        sender.send_directory()


    """

    def __init__(self, config: Config):
        self.config = config

    def get_attributes(self) -> Dict[str, str]:
        """return a dict of attributes to add in the index file (like unique IDs to track transfers on the receiver side)
        keys and values must be simple strings (no new-lines symbols and not contains the " = " substring).
        Available keys must be added to the used :attr:`Receiver.available_attributes`.
        """
        return {}

    @property
    def transfer_abspath(self) -> str:
        """returns the absolute path of directory to send"""
        raise NotImplementedError

    @property
    def index_abspath(self):
        """returns the absolute path of the index file to create"""
        raise NotImplementedError

    @property
    def use_tar_archives(self):
        if self.config.use_tar_archives is None:
            return True
        return self.config.use_tar_archives

    def prepare_directory(self) -> Tuple[int, int]:
        """create an index file and return the number of files and the total size (including the index file).

        **can modify in-place some files (those empty or beginning by `# *-* HAIRGAP-`)** when not `config.use_tar_archives`

        result is always (1, 0) when `config.use_tar_archives` and not `config.always_compute_size` to speed up

        """
        start = time.time()
        if self.use_tar_archives:
            r = self.prepare_directory_tar()
        else:
            r = self.prepare_directory_no_tar()
        end = time.time()
        logger.info(
            "%s files, %s bytes in %s seconds (%s B/s)",
            r[0],
            r[1],
            (end - start),
            r[1] / (end - start),
        )
        return r

    def prepare_directory_tar(self) -> Tuple[int, int]:
        logger.info("preparing '%s' as a single tar archive…", self.transfer_abspath)
        ensure_dir(self.index_abspath)
        with open(self.index_abspath, "w") as fd:
            fd.write(HAIRGAP_MAGIC_NUMBER_INDEX)
            fd.write("[hairgap]\n")
            for k, v in sorted(self.get_attributes().items()):
                fd.write("%s = %s\n" % (k, v.replace("\n", "")))
        total_size = 0
        total_files = 1
        if self.config.always_compute_size:
            total_size += os.path.getsize(self.index_abspath)
            for root, dirnames, filenames in os.walk(self.transfer_abspath):
                for filename in filenames:
                    file_abspath = os.path.join(root, filename)
                    if os.path.isfile(file_abspath):
                        total_files += 1
                        total_size += os.path.getsize(file_abspath)
        logger.info(
            "%s file(s), %s byte(s), prepared in '%s'.",
            total_files,
            total_size,
            self.transfer_abspath,
        )
        return total_files, total_size

    def prepare_directory_no_tar(self) -> Tuple[int, int]:
        logger.info("preparing '%s' as multiple files…", self.transfer_abspath)
        dir_abspath = self.transfer_abspath
        index_path = self.index_abspath
        if self.config.split_size:
            self.split_source_files(dir_abspath, self.config.split_size)

        total_files, total_size = 1, 0
        ensure_dir(index_path)
        with open(index_path, "w") as fd:
            fd.write(HAIRGAP_MAGIC_NUMBER_INDEX)
            fd.write("[hairgap]\n")
            for k, v in sorted(self.get_attributes().items()):
                fd.write("%s = %s\n" % (k, v.replace("\n", "")))
            if self.config.split_size:
                fd.write("[splitted_content]\n")
            fd.write("[files]\n")
            for root, dirnames, filenames in os.walk(dir_abspath):
                dirnames.sort()
                filenames.sort()
                for filename in filenames:
                    file_abspath = os.path.join(root, filename)
                    expected_sha256 = hashlib.sha256()
                    if not os.path.isfile(file_abspath):
                        continue
                    filesize = os.path.getsize(file_abspath)
                    with open(file_abspath, "rb") as in_fd:
                        # start by checking special contents
                        prefix = in_fd.read(len(HAIRGAP_MAGIC_NUMBER_INDEX.encode()))
                        expected_sha256.update(prefix)
                        for data in iter(lambda: in_fd.read(65536), b""):
                            expected_sha256.update(data)
                    # if the file starts with a special value, we must rewrite it entirely
                    # to escape by HAIRGAP_MAGIC_NUMBER_ESCAPE
                    # maybe not very efficient, but such files are expected to be small
                    if prefix in HAIRGAP_PREFIXES:
                        suffix = random.randint(100000, 1000000 - 1)  # nosec
                        escaped_file_abspath = f"{file_abspath}.{suffix}"
                        with open(escaped_file_abspath, "wb") as fd_out:
                            fd_out.write(HAIRGAP_MAGIC_NUMBER_ESCAPE.encode())
                            with open(file_abspath, "rb") as fd_in:
                                for data in iter(lambda: fd_in.read(65536), b""):
                                    fd_out.write(data)
                        os.rename(escaped_file_abspath, file_abspath)

                    total_size += filesize
                    file_relpath = os.path.relpath(file_abspath, dir_abspath)
                    fd.write("%s = %s\n" % (expected_sha256.hexdigest(), file_relpath))
                    total_files += 1
        total_size += os.path.getsize(index_path)
        logger.info(
            "%s file(s), %s byte(s), prepared in '%s'.",
            total_files,
            total_size,
            self.transfer_abspath,
        )
        return total_files, total_size

    @staticmethod
    def archive_and_split_directory(
        config: Config,
        original_path: str,
        splitted_path: str,
        split_size: int = 100 * 1000 * 1000,
        prefix: str = "content.tar.gz.",
    ):
        ensure_dir(splitted_path, parent=False)
        tar_cmd = [config.tar, "czf", "-", "-C", original_path, "."]
        split_cmd = [
            config.split,
            "-b",
            str(split_size),
            "-",
            prefix,
        ]
        esc_tar_cmd = [shlex.quote(x) for x in tar_cmd]
        esc_split_cmd = [shlex.quote(x) for x in split_cmd]
        cmd = "%s | %s" % (" ".join(esc_tar_cmd), " ".join(esc_split_cmd))
        logger.info("archive and split '%s' to '%s'…", original_path, splitted_path)
        p = subprocess.Popen(
            cmd,  # nosec
            shell=True,  # nosec
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            cwd=splitted_path,
        )
        stdout, stderr = p.communicate(b"")
        if p.returncode:
            logger.error("command = %s , return code = %s", cmd, p.returncode)
            logger.error("stdout = %s\nstderr = %s", stdout.decode(), stderr.decode())

    def split_source_files(self, dir_abspath: str, split_size: int):
        """transform some files into a single, splitted, archive

        move the content of the source folder in a subfolder
        create another folder in the same source folder
        create a tar.gz file with the first subfolder and split it into chunks into the second subfolder
        remove the first subfolder
        move the content of the second subfolder to its parent
        remove the second subfolder"""
        logger.info("split '%s' into %s-bytes chunks", dir_abspath, split_size)
        names = os.listdir(dir_abspath)
        if not names:
            return
        folder_1 = os.path.join(dir_abspath, str(uuid.uuid4()))
        folder_2 = os.path.join(dir_abspath, str(uuid.uuid4()))
        ensure_dir(folder_1, parent=False)
        for name in names:
            os.rename(os.path.join(dir_abspath, name), os.path.join(folder_1, name))
        self.archive_and_split_directory(
            self.config, folder_1, folder_2, split_size=split_size
        )
        names = os.listdir(folder_2)
        shutil.rmtree(folder_1)
        for name in names:
            os.rename(os.path.join(folder_2, name), os.path.join(dir_abspath, name))
        shutil.rmtree(folder_2)

    def send_directory(self, port: Optional[int] = None):
        """send all files using hairgap.

        :param port: the port to send to, overriding the default config

        raise ValueError in case of error on the index or the directory to send"""
        dir_abspath = self.transfer_abspath
        index_path = self.index_abspath
        if not os.path.isdir(dir_abspath):
            logger.warning(
                "cannot send '%s' (missing directory).", self.transfer_abspath
            )
            raise ValueError("missing directory '%s'" % dir_abspath)
        elif not os.path.isfile(index_path):
            logger.warning(
                "cannot send '%s': missing index file '%s'.",
                self.transfer_abspath,
                self.index_abspath,
            )
            raise ValueError("missing index '%s'.", index_path)
        logger.info("sending '%s'…", self.transfer_abspath)
        start = time.time()
        if self.use_tar_archives:
            self.send_directory_tar(port=port)
        else:
            self.send_directory_no_tar(port=port)
        end = time.time()
        logger.info(
            "directory '%s' sent in %s seconds.", self.transfer_abspath, (end - start)
        )

    def send_directory_tar(self, port: Optional[int] = None):
        """send all files using hairgap, using the tar method.

        :param port: the port to send to, overriding the default config
        """
        dir_abspath = self.transfer_abspath
        index_path = self.index_abspath
        tar_cmd = [
            self.config.tar,
            "czf",
            "-",
            "-C",
            os.path.dirname(index_path),
            os.path.basename(index_path),
            "-C",
            os.path.dirname(dir_abspath),
            os.path.basename(dir_abspath),
        ]
        # we use gzip, not for compression (most files are probably already compressed) but for the CRC checksum
        # we cannot use more efficient algorithms like xz/bz2 (they cannot compress streams)
        logger.info("sending %s via hairgap …", dir_abspath)
        hairgap_cmd = self.get_hairgap_command(self.config, port)
        logger.debug("hairgaps command: '%s'.", " ".join(hairgap_cmd))
        logger.debug("tar command: '%s'.", " ".join(tar_cmd))
        esc_tar_cmd = [shlex.quote(x) for x in tar_cmd]
        esc_hairgap_cmd = [shlex.quote(x) for x in hairgap_cmd]
        cmd = "%s|%s" % (" ".join(esc_tar_cmd), " ".join(esc_hairgap_cmd))
        p = subprocess.Popen(
            cmd,
            shell=True,  # nosec
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
        )
        stdout, stderr = p.communicate(b"")
        time.sleep(self.config.end_delay_s)
        if p.returncode:
            logger.error(
                "unable to run '%s'.\nreturncode=%s\nstdout=%r\nstderr=%r\n",
                " ".join(cmd),
                p.returncode,
                stdout.decode(),
                stderr.decode(),
            )
            raise ValueError("Unable to send '%s'" % dir_abspath)

    def send_directory_no_tar(self, port: Optional[int] = None):
        """send all files using hairgap"""
        dir_abspath = self.transfer_abspath
        index_path = self.index_abspath
        self.send_file(self.config, index_path, port=port)
        with open(index_path) as fd:
            for line in fd:
                matcher = re.match(FILENAME_PATTERN, line)
                if not matcher:
                    continue
                file_relpath = matcher.group(2)
                actual_sha256 = matcher.group(1)
                file_abspath = os.path.join(dir_abspath, file_relpath)
                self.send_file(
                    self.config, file_abspath, sha256=actual_sha256, port=port
                )

    @classmethod
    def send_file(
        cls,
        config: Config,
        file_abspath: str,
        sha256: Optional[str] = None,
        port: Optional[int] = None,
    ):
        if not os.path.isfile(file_abspath):
            logger.warning("missing file '%s'.", file_abspath)
            raise ValueError("Missing file '%s'." % file_abspath)
        empty_file_fd = None
        file_size = os.path.getsize(file_abspath)
        if file_size == 0:
            # we cannot send empty files
            empty_file_fd = tempfile.NamedTemporaryFile(delete=True)
            empty_file_fd.write(HAIRGAP_MAGIC_NUMBER_EMPTY.encode())
            empty_file_fd.flush()
            file_abspath = empty_file_fd.name
        if sha256:
            msg = "Sending %s via hairgap [sha526=%s, size=%s]…" % (
                file_abspath,
                sha256,
                file_size,
            )
        else:
            msg = "Sending %s via hairgap to port %s…" % (
                file_abspath,
                port or config.destination_port,
            )
        logger.info(msg)
        cmd = cls.get_hairgap_command(config, port)
        logger.info(" ".join(cmd))
        with open(file_abspath, "rb") as tmp_fd:
            p = subprocess.Popen(
                cmd, stdin=tmp_fd, stderr=subprocess.PIPE, stdout=subprocess.PIPE
            )
            stdout, stderr = p.communicate()
            if p.returncode:
                logger.error(
                    "unable to run '%s'.\nreturncode=%s\nstdout=%r\nstderr=%r\n",
                    " ".join(cmd),
                    p.returncode,
                    stdout.decode(),
                    stderr.decode(),
                )
                raise ValueError("Unable to send '%s'" % file_abspath)
        logger.info(
            "file '%s' sent; sleeping for %ss.", file_abspath, config.end_delay_s
        )
        if empty_file_fd is not None:
            empty_file_fd.close()
        time.sleep(config.end_delay_s)

    @staticmethod
    def get_hairgap_command(config: Config, port: Optional[int]):
        cmd = [
            config.hairgaps_path,
            "-p",
            str(port or config.destination_port),
        ]
        if config.redundancy:
            cmd += [
                "-r",
                str(config.redundancy),
            ]
        if config.error_chunk_size:
            cmd += [
                "-N",
                str(config.error_chunk_size),
            ]
        if config.max_rate_mbps:
            cmd += ["-b", str(config.max_rate_mbps)]
        if config.mtu_b:
            cmd += ["-M", str(config.mtu_b)]
        if config.keepalive_ms:
            cmd += ["-k", str(config.keepalive_ms)]
        cmd.append(config.destination_ip)
        return cmd
