#!/usr/bin/env python3
"""replace the hairgaps binary with a simple TCP transfer"""
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
import argparse
import logging
import socket
import sys

logger = logging.getLogger("hairgaps")


def main():
    """emulate the hairgaps behaviour but ignores most arguments"""
    logging.basicConfig(level=logging.DEBUG)
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", type=int, default=8008)
    parser.add_argument("-r", type=float)  # unused
    parser.add_argument("-N", type=int)  # unused
    parser.add_argument("-b", type=int)  # unused
    parser.add_argument("-M", type=int)  # unused
    parser.add_argument("-k", type=int)  # unused
    parser.add_argument("ip")
    args = parser.parse_args()
    size = 0
    logger.debug(
        "waiting for data to send to %s:%s on buffer fileno %s"
        % (args.ip, args.p, sys.stdin.buffer.fileno())
    )
    with socket.create_connection((args.ip, args.p)) as sock:
        for data in iter(lambda: sys.stdin.buffer.read(4096), b""):
            sock.send(data)
            size += len(data)
    logger.debug("%s bytes sent" % size)


if __name__ == "__main__":
    main()
