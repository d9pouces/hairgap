.. Hairgap documentation master file, created by
   sphinx-quickstart on Wed Feb 13 11:51:12 2013.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Hairgap's documentation
=======================

Basic protocol to send files using the [hairgap binary](https://github.com/cea-sec/hairgap).
The goal is to send random files through a unidirectionnal data-diode using UDP connections.

.. image:: https://travis-ci.org/d9pouces/hairgap.svg?branch=master
   :target: https://travis-ci.org/d9pouces/hairgap
   :alt: Build Status

.. image:: https://readthedocs.org/projects/hairgap/badge/?version=latest
   :target: https://hairgap.readthedocs.io/en/latest/?badge=latest
   :alt: Documentation Status

.. image:: https://badge.fury.io/py/hairgap.svg
   :target: https://pypi.org/project/hairgap/
   :alt: Pypi Status

By default, hairgap can only send a file, without its name. This library implements a basic protocol to send complete directories
and checksum transfered files.

This protocol is customizable and the sender side can add some attributes to each transfer.


* We assume that the hairgap binary is installed and in the PATH environment variable.
* The MAC adress of the destination must be known from the sender machine. You can inject this information into the ARP cache of the sender machine:


..code-block: bash

   DESTINATION_IP="the IP address of the destination machine"
   DESTINATION_MAC="the MAC address of the destination machine"
   arp -s ${DESTINATION_IP} ${DESTINATION_MAC}


First, you must start the receiver on the destination side:


..code-block: bash

   pip3 install hairgap
   pyhairgap receive ${DESTINATION_IP} directory/


Then you can send directories:

..code-block: bash

   pip3 install hairgap
   pyhairgap send ${DESTINATION_IP} directory/



Overview:

:doc:`api/index`
    The complete API documentation, organized by modules
