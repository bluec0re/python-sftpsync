#!/usr/bin/env python2
# encoding: utf-8

from __future__ import print_function, absolute_import

import paramiko
import sys
import os
import getpass
import argparse
import re

from .sftp import connect
from .sync import sync

def setup_sftp(args):
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


    # get host key, if we know one
    hostkeytype = None
    hostkey = None
    try:
        host_keys = paramiko.util.load_host_keys(os.path.expanduser('~/.ssh/known_hosts'))
    except IOError:
        try:
            # try ~/ssh/ too, because windows can't have a folder named ~/.ssh/
            host_keys = paramiko.util.load_host_keys(os.path.expanduser('~/ssh/known_hosts'))
        except IOError:
            print('*** Unable to open host keys file')
            host_keys = {}
    if host_keys.has_key(hostname):
        hostkeytype = host_keys[hostname].keys()[0]
        hostkey = host_keys[hostname][hostkeytype]
        print('Using host key of type %s' % hostkeytype)

    return connect(hostname, port, username, hostkey)

def main():
    # setup logging
#    paramiko.util.log_to_file('demo_sftp.log')
    
    parser = argparse.ArgumentParser()
    parser.add_argument('COMMAND', choices=('up', 'down', 'both', 'init', 'check', 'list'))
    parser.add_argument('HOST')
    parser.add_argument('PATH')
    parser.add_argument('-e', '--exclude', help='exclude files based on regex')
    parser.add_argument('-n', '--dry-run', help='dry run', action="store_true")
    parser.add_argument('-s', '--skip-on-error', help='skip file on error', action="store_true")

    args = parser.parse_args()

    excludes = None
    if args.exclude:
        excludes = re.compile(args.exclude)
        print("Excluding: {0}".format(excludes.pattern))

    if args.COMMAND != 'list':
        t = setup_sftp(args)
    else:
        t = None

    try:
        if args.COMMAND != 'list':
            sftp = paramiko.SFTPClient.from_transport(t)
        else:
            sftp = None
        sync(sftp, args.PATH, os.path.join(os.getcwd(), os.path.basename(args.PATH)), args.COMMAND, excludes, args.dry_run, args.skip_on_error)
    finally:
        if t:
            t.close()

if __name__ == '__main__':
    try:
        main()
    except:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        if exc_type is KeyboardInterrupt:
            sys.exit(1)
        if exc_type is SystemExit:
            sys.exit(exc_value)
        print("\n[\033[31m!\033[0m] Exception: %s (%s)" % (str(exc_value), exc_type.__name__))
        import traceback
        traceback.print_exc()#limit=3)
