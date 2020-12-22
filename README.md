Hairgap
=======

Basic protocol to send files using the [hairgap binary](https://github.com/cea-sec/hairgap).
The goal is to send random files through a unidirectionnal data-diode using UDP connections.

[![Build Status](https://travis-ci.com/d9pouces/hairgap.svg?branch=master)](https://travis-ci.com/d9pouces/hairgap)
[![Documentation Status](https://readthedocs.org/projects/hairgap/badge/?version=latest)](https://hairgap.readthedocs.io/en/latest/?badge=latest)
[![PyPI version](https://badge.fury.io/py/hairgap.svg)](https://pypi.org/project/hairgap/)
[![LGTM Grade](https://img.shields.io/lgtm/grade/python/github/d9pouces/hairgap)](https://lgtm.com/projects/g/d9pouces/hairgap/?mode=list)

By default, hairgap can only send a file, without its name nor metadata. This Python library implements a basic protocol to send complete directories
with checksums. 

This protocol is customizable and the sender can add some attributes (a `Dict[str, str]`) to each transfer.


* We assume that the hairgap binary is installed and in the PATH environment variable.
* The MAC adress of the destination must be known from the sender machine. You can inject this information into the ARP cache of the sender machine: 

```bash
DESTINATION_IP="the IP address of the destination machine"
DESTINATION_MAC="the MAC address of the destination machine"
arp -s ${DESTINATION_IP} ${DESTINATION_MAC}
```
First, you must start the receiver on the destination side:
```bash
python3 -m pip install hairgap

DESTINATION_IP="the IP address of the destination machine"
pyhairgap receive ${DESTINATION_IP} directory/

```

Then you can send directories:
```bash
python3 -m pip install hairgap

DESTINATION_IP="the IP address of the destination machine"
pyhairgap send ${DESTINATION_IP} directory/

```

Hairgap binaries
----------------

You need to compile hairgap binaires yourself since no official package exists.
However, a Python package (`hairgap-binaries`) has been created to distribute precompiled binaries for Linux x86_64.
This package is automatically detected and used.

```bash
python3 -m pip install hairgap-binaries
```
