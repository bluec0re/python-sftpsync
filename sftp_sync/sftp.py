from __future__ import print_function, absolute_import

from binascii import hexlify
import getpass
import os
import paramiko
import logging

__author__ = 'bluec0re'


log = logging.getLogger(__name__)


def connect(hostname, port, username, pkey=None, sock=None):
    """
    Connect to the given host and port, first attempt is by using
    a ssh agent, second attempt is manual auth

    Keyword arguments:
    hostname --
    port --
    username --
    hostkey --

    """
    client = paramiko.SSHClient()
    client.load_system_host_keys()

    # auto add hostkey
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    password = None

    while True:
        try:
            logging.getLogger('paramiko.transport').setLevel(logging.INFO)
            client.connect(hostname, port, username, password, allow_agent=password is None, pkey=pkey, sock=sock)
            break
        except paramiko.BadHostKeyException as e:
            log.critical("Host sends wrong hostkey. Got %s, expected %s",
                         ':'.join("%02x" % ord(c) for c in e.args[1].get_fingerprint()),
                         ':'.join("%02x" % ord(c) for c in e.args[2].get_fingerprint()))
            return False
        except paramiko.PasswordRequiredException as e:
            log.error("Password required for %s@%s", username, hostname)
            password = getpass.getpass("Password: ")
            continue
        except paramiko.SSHException as e:
            if 'not found in known_hosts' in e.message:
                log.critical("Host %s was not found in known_hosts file. Connect via ssh first", hostname)
                return False
            raise e
        finally:
            logging.getLogger('paramiko.transport').setLevel(logging.WARNING)
    return client


def setup_sftp(args):
    """
    Creates a sftp transport
    """

    # get hostname
    username = None
    port = None
    pkey = None
    sock = None
    hostname = args.HOST
    if hostname.find('@') >= 0:
        username, hostname = hostname.split('@')
    if hostname.find(':') >= 0:
        hostname, portstr = hostname.split(':')
        port = int(portstr)

    if os.path.exists(os.path.expanduser('~/.ssh/config')):
        with open(os.path.expanduser('~/.ssh/config')) as fp:
            config = paramiko.SSHConfig()
            config.parse(fp)

            entry = config.lookup(hostname)
            if entry:
                if not port:
                   port = entry.get('port', 22)
                hostname = entry.get('hostname', hostname)
                if username is None:
                    username = entry.get('user')
                pkeys = entry.get('identityfile')
                if pkeys:
                    for pk in pkeys:
                        pkey = None
                        for cls in (paramiko.RSAKey, paramiko.ECDSAKey, paramiko.DSSKey):
                            try:
                                pkey = cls.from_private_key_file(pk)
                            except paramiko.PasswordRequiredException:
                                log.error("Password required for key %s", pk)
                                pkey = cls.from_private_key_file(pk, getpass.getpass("Key Password: "))
                            except (paramiko.SSHException, IOError):
                                log.warning("Can't read pkey %s as %s", pk, cls.__name__)
                                continue
                            break
                        if isinstance(pkey, paramiko.PKey):
                            break
                sock = entry.get('proxycommand')

    # get username
    if username is None:
        default_username = getpass.getuser()
        username = raw_input('Username [%s]: ' % default_username)
        if len(username) == 0:
            username = default_username

    client = connect(hostname, port, username, pkey, sock)
    return client
