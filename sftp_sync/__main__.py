#!/usr/bin/env python2
# encoding: utf-8

from __future__ import print_function, absolute_import
from helperlib.exception import install_hook
from helperlib.logging import ColorFormatter

import os
import argparse
import re

from .sftp import setup_sftp
from .sync import sync
import logging





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

    sftp = None
    client = None
    if args.COMMAND != 'list':
        client = setup_sftp(args)
        sftp = client.open_sftp()

    try:
        if sftp is False:
            exit(1)

        sync(sftp,
             args.PATH,
             os.path.join(os.getcwd(), os.path.basename(args.PATH)),
             args.COMMAND,
             excludes,
             args.dry_run,
             args.skip_on_error,
             args.subdir)
    finally:
        if client:
            client.close()

if __name__ == '__main__':
    install_hook()
    main()
