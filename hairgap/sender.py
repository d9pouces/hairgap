# ##############################################################################
#  This file is part of Interdiode                                             #
#                                                                              #
#  Copyright (C) 2020 Matthieu Gallet <matthieu.gallet@19pouces.net>           #
#  All Rights Reserved                                                         #
#                                                                              #
# ##############################################################################

import hashlib
import logging
import os
import random
import re
import subprocess
import tempfile
import time
from typing import Dict, Tuple

from hairgap.constants import (
    HAIRGAP_MAGIC_NUMBER_EMPTY,
    HAIRGAP_MAGIC_NUMBER_ESCAPE,
    HAIRGAP_MAGIC_NUMBER_INDEX,
)
from hairgap.utils import Config, FILENAME_PATTERN

logger = logging.getLogger("hairgap")

HAIRGAP_PREFIXES = {
    HAIRGAP_MAGIC_NUMBER_INDEX.encode(),
    HAIRGAP_MAGIC_NUMBER_EMPTY.encode(),
    HAIRGAP_MAGIC_NUMBER_ESCAPE.encode(),
}


class DirectorySender:
    def __init__(self, config: Config):
        self.config = config

    def get_attributes(self) -> Dict[str, str]:
        return {}

    @property
    def transfer_abspath(self):
        raise NotImplementedError

    @property
    def index_abspath(self):
        raise NotImplementedError

    def prepare_directory(self) -> Tuple[int, int]:
        """create an index file and return the number of files and the total size.

        **can modify in-place some files (those beginning by `# *-* HAIRGAP-`)**
        """
        logger.info("Preparing '%s'…" % self.transfer_abspath)
        dir_abspath = self.transfer_abspath
        index_path = self.index_abspath
        total_files, total_size = 1, 0
        with open(index_path, "w") as fd:
            fd.write(HAIRGAP_MAGIC_NUMBER_INDEX)
            fd.write("[hairgap]\n")
            for k, v in sorted(self.get_attributes().items()):
                fd.write("%s = %s\n" % (k, v.replace("\n", "")))
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
                        escaped_file_abspath = file_abspath + ".%s" % random.randint(
                            100000, 1000000 - 1
                        )
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
            "%s file(s), %s byte(s), prepared in '%s'."
            % (total_files, total_size, self.transfer_abspath)
        )
        return total_files, total_size

    def send_directory(self, port: int = None):
        dir_abspath = self.transfer_abspath
        index_path = self.index_abspath
        if not os.path.isdir(dir_abspath):
            logger.warning(
                "Cannot send '%s' (missing directory)." % self.transfer_abspath
            )
            raise ValueError("missing directory '%s'" % dir_abspath)
        elif not os.path.isfile(index_path):
            logger.warning(
                "Cannot send '%s' (missing index file '%s')."
                % (self.transfer_abspath, self.index_abspath)
            )
            raise ValueError("Missing index '%s'" % index_path)
        logger.info("Sending '%s'…" % self.transfer_abspath)
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
        logger.info("Directory '%s' sent." % self.transfer_abspath)

    @staticmethod
    def send_file(
        config: Config, file_abspath: str, sha256: str = None, port: int = None
    ):
        # FIXME: vérifier avec arp -n que l'IP est connue dans le cache ARP (via un check Django)
        if not os.path.isfile(file_abspath):
            logger.warning("Missing file '%s'." % file_abspath)
            raise ValueError("Missing file '%s'" % file_abspath)
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
        logger.info(" ".join(cmd))
        with open(file_abspath, "rb") as tmp_fd:
            p = subprocess.Popen(
                cmd, stdin=tmp_fd, stderr=subprocess.PIPE, stdout=subprocess.PIPE
            )
            stdout, stderr = p.communicate()
            if p.returncode:
                logger.error(
                    "Unable to run '%s' \nreturncode=%s\nstdout=%r\nstderr=%r\n"
                    % (" ".join(cmd), p.returncode, stdout.decode(), stderr.decode())
                )
                raise ValueError("Unable to send '%s'" % file_abspath)
        logger.info(
            "File '%s' sent; sleeping for %ss." % (file_abspath, config.end_delay_s)
        )
        if empty_file_fd is not None:
            empty_file_fd.close()
        time.sleep(config.end_delay_s)
