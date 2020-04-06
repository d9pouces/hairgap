# ##############################################################################
#  This file is part of Interdiode                                             #
#                                                                              #
#  Copyright (C) 2020 Matthieu Gallet <matthieu.gallet@19pouces.net>           #
#  All Rights Reserved                                                         #
#                                                                              #
# ##############################################################################

import datetime
import os
from typing import Optional

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
        os.makedirs(dirname)
    return path


def now():
    return datetime.datetime.utcnow().replace(tzinfo=utc)


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
        hairgapr: str = "hairgapr",
        hairgaps: str = "hairgaps",
        tar: str = None,
        use_tar_archives: bool = False,
        always_compute_size: bool = True,
    ):
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
        self._hairgapr_path = hairgapr
        self._hairgaps_path = hairgaps
        self._use_tar_archives = use_tar_archives
        self._always_compute_size = always_compute_size
        if tar is None and os.path.isfile("/usr/bin/tar"):
            tar = "/usr/bin/tar"
        elif tar is None:
            tar = "/bin/tar"
        self._tar = tar

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
        return self._hairgapr_path

    @property
    def hairgaps_path(self):
        return self._hairgaps_path

    @property
    def use_tar_archives(self):
        return self._use_tar_archives

    @property
    def always_compute_size(self):
        return self._always_compute_size

    @property
    def tar(self):
        return self._tar
