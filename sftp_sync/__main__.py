#!/usr/bin/env python2
# encoding: utf-8

from __future__ import print_function, absolute_import
from helperlib.exception import install_hook
from helperlib.logging import ColorFormatter

import paramiko
import sys
import os
import getpass
import argparse
import re

from .sftp import connect
from .sync import sync
import logging

def setup_sftp(args):
    """
    Creates a sftp transport
    """
    # get hostname
    username = ''
    hostname = args.HOST
    if hostname.find('@') >= 0:
        username, hostname = hostname.split('@')
    port = 22
    if hostname.find(':') >= 0:
        hostname, portstr = hostname.split(':')
        port = int(portstr)



    # get username
    if username == '':
        default_username = getpass.getuser()
        username = raw_input('Username [%s]: ' % default_username)
        if len(username) == 0:
            username = default_username

    return connect(hostname, port, username)


def main():
    """
    main program
    """
    # setup logging
#    paramiko.util.log_to_file('demo_sftp.log')
    logging.basicConfig(level='INFO')
    logging.getLogger().handlers[0].setFormatter(ColorFormatter('[%(levelname)s] %(message)s'))
    logging.getLogger('paramiko').setLevel('WARNING')

    parser = argparse.ArgumentParser()
    parser.add_argument('COMMAND',
                        choices=('up', 'down', 'both',
                                 'init', 'check', 'list'))
    parser.add_argument('HOST')
    parser.add_argument('PATH')
    parser.add_argument('-e', '--exclude', help='exclude files based on regex')
    parser.add_argument('-n', '--dry-run', help='dry run', action="store_true")
    parser.add_argument('-s', '--skip-on-error', help='skip file on error',
                        action="store_true")
    parser.add_argument('-S', '--subdir', help='restrict to subdir')

    args = parser.parse_args()

    excludes = None
    if args.exclude:
        excludes = re.compile(args.exclude)
        print("Excluding: {0}".format(excludes.pattern))

    if args.COMMAND != 'list':
        transport = setup_sftp(args)
    else:
        transport = None

    try:
        if args.COMMAND != 'list':
            sftp = paramiko.SFTPClient.from_transport(transport)
        else:
            sftp = None
        sync(sftp,
             args.PATH,
             os.path.join(os.getcwd(), os.path.basename(args.PATH)),
             args.COMMAND,
             excludes,
             args.dry_run,
             args.skip_on_error,
             args.subdir)
    finally:
        if transport:
            transport.close()

if __name__ == '__main__':
    install_hook()
    main()
