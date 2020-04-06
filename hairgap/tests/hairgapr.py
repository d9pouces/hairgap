#!/usr/bin/env python3
"""replace the hairgapr binary with a simple TCP transfer"""
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

logger = logging.getLogger("hairgapr")


def main():
    """emulate the hairgapr behaviour but ignores most arguments"""
    logging.basicConfig(level=logging.DEBUG)
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", type=int, default=8008)
    parser.add_argument("-t", type=float)  # unused
    parser.add_argument("-m", type=float)  # unused
    parser.add_argument("ip")
    args = parser.parse_args()
    size = 0
    logger.debug("waiting for receiving data from %s:%s" % (args.ip, args.p))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((args.ip, args.p))
        sock.listen(0)
        conn, __ = sock.accept()
        for data in iter(lambda: conn.recv(4096), b""):
            size += len(data)
            sys.stdout.buffer.write(data)
    logger.debug("%s bytes received" % size)


if __name__ == "__main__":
    main()
