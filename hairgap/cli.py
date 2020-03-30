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
import os
import shutil
import tempfile
import uuid
from typing import Dict, Optional

from hairgap.receiver import Receiver
from hairgap.sender import DirectorySender
from hairgap.utils import Config, now, ensure_dir


class SingleDirSender(DirectorySender):
    def __init__(self, config: Config, data_path: str, index_path: str):
        super().__init__(config)
        self.data_path = data_path
        self.index_path = index_path
        self.creation_date = now()
        self.uid = uuid.uuid4()

    def get_attributes(self) -> Dict[str, str]:
        return {
            "uid": str(self.uid),
            "creation": self.creation_date.strftime("%Y-%m-%dT%H:%M:%s"),
        }

    @property
    def transfer_abspath(self):
        return self.data_path

    @property
    def index_abspath(self):
        return self.index_path


class SimpleDirReceiver(Receiver):
    available_attributes = {"uid", "creation"}

    def __init__(
        self,
        config: Config,
        after_reception_path: str,
        threading: bool = False,
        port: int = None,
    ):
        super().__init__(config, threading=threading, port=port)
        self.after_reception_path = after_reception_path

    def transfer_complete(self):
        super().transfer_complete()
        print(os.path.join(self.after_reception_path, self.current_attributes["uid"]))

    def get_current_transfer_directory(self) -> Optional[str]:
        if not self.current_attributes["uid"]:
            return None
        return os.path.join(self.after_reception_path, self.current_attributes["uid"])


# noinspection PyUnusedLocal
def missing_command(args):
    return main(["-h"])


def send_directory(args):
    with tempfile.TemporaryDirectory(dir=args.tmp_path) as dirname:
        config = Config(
            destination_ip=args.ip,
            destination_port=args.port,
            redundancy=args.redundancy,
            error_chunk_size=args.error_chunk_size,
            max_rate_mbps=args.max_rate_mbps,
            mtu_b=args.mtu_b,
            keepalive_ms=args.keepalive_ms,
            end_delay_s=args.delay_s,
            hairgaps=args.bin_path,
        )
        copy_path = os.path.join(dirname, "data")
        index_path = os.path.join(dirname, "index.txt")
        source = args.source
        if os.path.isfile(source):
            ensure_dir(copy_path)
            shutil.copy(source, os.path.join(copy_path, os.path.basename(source)))
        else:
            shutil.copytree(source, copy_path)
        sender = SingleDirSender(config, data_path=copy_path, index_path=index_path)
        sender.prepare_directory()
        sender.send_directory()


def receive_directory(args):
    with tempfile.TemporaryDirectory(dir=args.tmp_path) as dirname:
        config = Config(
            destination_ip=args.ip,
            destination_port=args.port,
            destination_path=dirname,
            timeout_s=args.timeout_s,
            mem_limit_mb=args.mem_limit_mb,
            hairgapr=args.bin_path,
        )
        receiver = SimpleDirReceiver(
            config, args.destination, threading=not args.no_threading
        )
        try:
            receiver.loop()
        except KeyboardInterrupt:
            pass


def populate_receive_parser(receive_parser):
    tmp_dir = tempfile.gettempdir()
    receive_parser.add_argument(
        "ip",
        help="destination IP address (cannot be localhost, even for testing purposes)",
    )
    receive_parser.add_argument(
        "destination", help="root directory, where received directory are written"
    )
    receive_parser.add_argument("--port", "-p", type=int, default=8008, help="UDP port")
    receive_parser.add_argument("--bin-path", help="path of the hairgapr binary")
    receive_parser.add_argument("--timeout-s", "-t", type=float)
    receive_parser.add_argument(
        "--no-threading",
        action="store_true",
        default=False,
        help="avoid multithreading. Only if small files are expected!",
    )
    receive_parser.add_argument(
        "--mem-limit-mb", "-m", type=float,
    )
    receive_parser.add_argument(
        "--tmp-path",
        help="temporary path, used during reception [%s]" % tmp_dir,
        default=tmp_dir,
    )
    receive_parser.set_defaults(func=receive_directory)


def populate_send_parser(send_parser):
    tmp_dir = tempfile.gettempdir()
    send_parser.add_argument(
        "ip",
        help="destination IP address (cannot be localhost, even for testing purposes)",
    )
    send_parser.add_argument("source", help="the directory to send")
    send_parser.add_argument("--port", "-p", type=int, default=8008, help="UDP port")
    send_parser.add_argument(
        "--bin-path", help="path of the hairgaps binary", default="hairgaps"
    )
    send_parser.add_argument("--redundancy", "-r", type=float, default=3.0)
    send_parser.add_argument("--error-chunk-size", "-N", type=int)
    send_parser.add_argument("--max-rate-mbps", "-b", type=int)
    send_parser.add_argument("--mtu-b", "-M", type=int)
    send_parser.add_argument("--keepalive-ms", "-k", type=int, default=500)
    send_parser.add_argument(
        "--delay-s",
        "-d",
        type=float,
        help="delay between two successive files",
        default=3.0,
    )
    send_parser.add_argument(
        "--tmp-path",
        help="temporary path, where the whole directory to send is copied [%s]"
        % tmp_dir,
        default=tmp_dir,
    )
    send_parser.set_defaults(func=send_directory)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.set_defaults(func=missing_command)
    subparsers = parser.add_subparsers()
    send_parser = subparsers.add_parser("send")
    populate_send_parser(send_parser)
    receive_parser = subparsers.add_parser("receive")
    populate_receive_parser(receive_parser)
    args = parser.parse_args(argv)
    args.func(args)
