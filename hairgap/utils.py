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
import itertools
import os
import re
import subprocess
from typing import Dict, Optional, Tuple

try:
    from hairgap_binaries import get_hairgapr, get_hairgaps
except ImportError:

    def get_hairgapr():
        return None

    def get_hairgaps():
        return None


DEFAULT_HAIRGAPR = get_hairgapr() or "hairgapr"
DEFAULT_HAIRGAPS = get_hairgaps() or "hairgaps"

FILENAME_PATTERN = r"([a-fA-F\d]{64}) = (.*)$"

ZERO = datetime.timedelta(0)
HOUR = datetime.timedelta(hours=1)


class UTC(datetime.tzinfo):
    """UTC

    Optimized UTC implementation. It unpickles using the single module global
    instance defined beneath this class declaration.
    """

    zone = "UTC"

    _utcoffset = ZERO
    _dst = ZERO
    _tzname = zone

    def fromutc(self, dt):
        if dt.tzinfo is None:
            return self.localize(dt)
        return super(utc.__class__, self).fromutc(dt)

    def utcoffset(self, dt):
        return ZERO

    def tzname(self, dt):
        return "UTC"

    def dst(self, dt):
        return ZERO

    def __reduce__(self):
        return _UTC, ()

    # noinspection PyUnusedLocal
    def localize(self, dt, is_dst=False):
        """Convert naive time to local time"""
        if dt.tzinfo is not None:
            raise ValueError("Not naive datetime (tzinfo is already set)")
        return dt.replace(tzinfo=self)

    # noinspection PyUnusedLocal
    def normalize(self, dt, is_dst=False):
        """Correct the timezone information on the given datetime"""
        if dt.tzinfo is self:
            return dt
        if dt.tzinfo is None:
            raise ValueError("Naive time - no tzinfo set")
        return dt.astimezone(self)

    def __repr__(self):
        return "<UTC>"

    def __str__(self):
        return "UTC"


UTC = utc = UTC()


# noinspection PyPep8Naming
def _UTC():
    """Factory function for utc unpickling.

    Makes sure that unpickling a utc instance always returns the same
    module global.

    These examples belong in the UTC class above, but it is obscured; or in
    the README.txt, but we are not depending on Python 2.4 so integrating
    the README.txt examples with the unit tests is not trivial.
    """
    return utc


_UTC.__safe_for_unpickling__ = True


def ensure_dir(path, parent=True):
    """Ensure that the given directory exists

    :param path: the path to check
    :param parent: only ensure the existence of the parent directory

    """
    dirname = os.path.dirname(path) if parent else path
    if not os.path.isdir(dirname):
        os.makedirs(dirname, exist_ok=True)
    return path


def now():
    return datetime.datetime.now(utc)


def get_arp_cache(content=None) -> Dict[str, Tuple[Optional[str], Optional[str]]]:
    if content is None:
        env = {**os.environ, **{"LC_ALL": "en_US.UTF-8"}}
        cmd = ["arp", "-n"]
        content = subprocess.check_output(cmd, env=env, encoding="utf-8")  # nosec
    r = {}
    lines = content.splitlines()
    matcher = re.match(
        r"^([\w\s]+\s{2,})([^\s][\w\s]+\s{2,})([^\s][\w\s]+\s{2,})([^\s][\w\s]+\s{2,})([^\s]+)$",
        lines[0],
    )
    sizes = list(itertools.accumulate([len(x) - 1 for x in matcher.groups()]))
    for line in lines[1:]:
        ip_address = line[: sizes[0]].strip() or None
        mac_address = line[sizes[1] : sizes[2]].strip() or None
        if not re.match(r"\w{2}:\w{2}:\w{2}:\w{2}:\w{2}:\w{2}", mac_address):
            mac_address = None
        iface = line[sizes[4] :].strip() or None
        r[ip_address] = (mac_address, iface)
    return r


class Config:
    """
    Stores hairgap command-line options, delay between successive sends, and temporary directory.
    Every parameter is accessed through a property decorator, so it can easily overriden.
    You should check https://github.com/cea-sec/hairgap for hairgap options.
    """

    def __init__(
        self,
        destination_ip=None,
        destination_port: int = 15124,
        destination_path=None,
        end_delay_s: Optional[float] = 3.0,
        error_chunk_size: Optional[int] = None,
        keepalive_ms: Optional[int] = 500,
        max_rate_mbps: Optional[int] = None,
        mem_limit_mb: Optional[int] = None,
        mtu_b: Optional[int] = None,
        timeout_s: float = 3.0,
        redundancy: float = 3.0,
        hairgapr: str = DEFAULT_HAIRGAPR,
        hairgaps: str = DEFAULT_HAIRGAPS,
        tar: str = None,
        split: str = None,
        cat: str = None,
        use_tar_archives: Optional[bool] = None,
        always_compute_size: bool = True,
        split_size: Optional[int] = None,
    ):
        """

        :param destination_ip: CEA's hairgap option
        :param destination_port: CEA's hairgap option
        :param destination_path: where received files are stored
        :param end_delay_s: delay between successive sends (in seconds)
        :param error_chunk_size: CEA's hairgap option
        :param keepalive_ms: CEA's hairgap option
        :param max_rate_mbps: CEA's hairgap option
        :param mem_limit_mb: CEA's hairgap option
        :param mtu_b: CEA's hairgap option
        :param timeout_s: CEA's hairgap option
        :param redundancy: CEA's hairgap option
        :param hairgapr: path of the 'hairgapr' binary
        :param hairgaps: path of the 'hairgaps' binary
        :param tar: path of the 'tar' binary
        :param split: path of the 'split' binary
        :param cat: path of the 'cat' binary
        :param use_tar_archives: send files as a single tar archive
            can be `None` for the reception (guess the mode using the file headers)
        :param always_compute_size: always compute the total size of sent files
        :param split_size: if not None, archive all files in a .tar.gz, split it into chunks of the given size
            useless if `use_tar_archives`
        """
        self._destination_ip = destination_ip
        self._destination_port = destination_port
        self._end_delay_s = end_delay_s
        self._error_chunk_size = error_chunk_size
        self._keepalive_ms = keepalive_ms
        self._max_rate_mbps = max_rate_mbps
        self._mem_limit_mb = mem_limit_mb
        self._mtu_b = mtu_b
        self._destination_path = destination_path
        self._timeout_s = timeout_s
        self._redundancy = redundancy
        self._use_tar_archives = use_tar_archives
        self._split_size = split_size
        self._always_compute_size = always_compute_size

        self._path_hairgapr = self.get_bin_prefix("hairgapr", hairgapr)
        self._path_hairgaps = self.get_bin_prefix("hairgaps", hairgaps)
        self._path_tar = self.get_bin_prefix("tar", tar)
        self._path_cat = self.get_bin_prefix("cat", cat)
        self._path_split = self.get_bin_prefix("split", split)

    @staticmethod
    def get_bin_prefix(name, path: Optional[str] = None):
        """search a binary in standard paths. $PATH may be not set, but we only use it for basic UNIX tools (tar/cat/split)"""
        if path is not None:
            return path
        for prefix in ["/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]:
            path = "%s/%s" % (prefix, name)
            if os.path.isfile(path):
                return path
        return None

    @property
    def destination_ip(self):
        return self._destination_ip

    @property
    def destination_port(self):
        return self._destination_port

    @property
    def end_delay_s(self):
        return self._end_delay_s

    @property
    def error_chunk_size(self):
        return self._error_chunk_size

    @property
    def keepalive_ms(self):
        return self._keepalive_ms

    @property
    def max_rate_mbps(self):
        return self._max_rate_mbps

    @property
    def mem_limit_mb(self):
        return self._mem_limit_mb

    @property
    def mtu_b(self):
        return self._mtu_b

    @property
    def destination_path(self):
        return self._destination_path

    @property
    def timeout_s(self):
        return self._timeout_s

    @property
    def redundancy(self):
        return self._redundancy

    @property
    def hairgapr_path(self):
        return self._path_hairgapr

    @property
    def hairgaps_path(self):
        return self._path_hairgaps

    @property
    def use_tar_archives(self):
        return self._use_tar_archives

    @property
    def always_compute_size(self):
        return self._always_compute_size

    @property
    def tar(self):
        return self._path_tar

    @property
    def cat(self):
        return self._path_cat

    @property
    def split(self):
        return self._path_split

    @property
    def split_size(self):
        return self._split_size
