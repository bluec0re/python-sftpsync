from __future__ import print_function, absolute_import

from binascii import hexlify
import getpass
import os

import paramiko

__author__ = 'bluec0re'



def agent_auth(transport, username):
    """
    Attempt to authenticate to the given transport using any of the private
    keys available from an SSH agent.
    """

    agent = paramiko.Agent()
    agent_keys = agent.get_keys()
    if len(agent_keys) == 0:
        return

    for key in agent_keys:
        print('[\033[34m*\033[0m] Trying ssh-agent key %s' %
              hexlify(key.get_fingerprint()), end="")
        try:
            transport.auth_publickey(username, key)
            print('... \033[32msuccess!\033[0m')
            return
        except paramiko.SSHException:
            print('... \033[31mnope.\033[0m')

def manual_auth(username, hostname, t):
    """
    Attempt to authenticate manually

    Keyword arguments:
    username --
    hostname --
    t -- paramiko.Transport

    """
    default_auth = 'p'
    auth = raw_input('[\033[36m?\033[0m] Auth by (p)assword, (r)sa key, or (d)sa key? [%s] ' % default_auth)
    if len(auth) == 0:
        auth = default_auth

    if auth == 'r':
        default_path = os.path.join(os.environ['HOME'], '.ssh', 'id_rsa')
        path = raw_input('RSA key [%s]: ' % default_path)
        if len(path) == 0:
            path = default_path
        try:
            key = paramiko.RSAKey.from_private_key_file(path)
        except paramiko.PasswordRequiredException:
            password = getpass.getpass('RSA key password: ')
            key = paramiko.RSAKey.from_private_key_file(path, password)
        t.auth_publickey(username, key)
    elif auth == 'd':
        default_path = os.path.join(os.environ['HOME'], '.ssh', 'id_dsa')
        path = raw_input('DSA/DSS key [%s]: ' % default_path)
        if len(path) == 0:
            path = default_path
        try:
            key = paramiko.DSSKey.from_private_key_file(path)
        except paramiko.PasswordRequiredException:
            password = getpass.getpass('DSA/DSS key password: ')
            key = paramiko.DSSKey.from_private_key_file(path, password)
        t.auth_publickey(username, key)
    else:
        pw = getpass.getpass('Password for %s@%s: ' % (username, hostname))
        t.auth_password(username, pw)


def connect(hostname, port, username):
    """
    Connect to the given host and port, first attempt is by using
    a ssh agent, second attempt is manual auth

    Keyword arguments:
    hostname --
    port --
    username --
    hostkey --

    """
    t = paramiko.Transport((hostname, port))
    t.use_compression()
    t.start_client()
    #t.connect(username=username, password=password, hostkey=hostkey)
    agent_auth(t, username)
    if not t.is_authenticated():
        t.close()
        t = paramiko.Transport((hostname, port))
        t.use_compression()
        t.start_client()
        manual_auth(username, hostname, t)
    return t
