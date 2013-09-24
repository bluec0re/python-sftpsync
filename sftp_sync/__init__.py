#!/usr/bin/env python2
# encoding: utf-8

from __future__ import print_function

import paramiko
import sys
import os
import getpass
from binascii import hexlify
import stat
import time
import argparse
import re
from datetime import timedelta


def main():
    # setup logging
#    paramiko.util.log_to_file('demo_sftp.log')
    
    parser = argparse.ArgumentParser()
    parser.add_argument('COMMAND', choices=('up', 'down', 'both', 'init'))
    parser.add_argument('HOST')
    parser.add_argument('PATH')
    parser.add_argument('-e', '--exclude', help='exclude files based on regex')
    parser.add_argument('-n', '--dry-run', help='dry run', action="store_true")
    parser.add_argument('-s', '--skip-on-error', help='skip file on error', action="store_true")

    args = parser.parse_args()

    # get hostname
    username = ''
    hostname = args.HOST
    if hostname.find('@') >= 0:
        username, hostname = hostname.split('@')
    port = 22
    if hostname.find(':') >= 0:
        hostname, portstr = hostname.split(':')
        port = int(portstr)

    path = args.PATH
    cmd = args.COMMAND
    excludes = None
    if args.exclude:
        excludes = re.compile(args.exclude)
    
    
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

    t = connect(hostname, port, username, hostkey)
    try:
        sftp = paramiko.SFTPClient.from_transport(t)
        sync(sftp, path, os.path.join(os.getcwd(), os.path.basename(path)), cmd, excludes, args.dry_run, args.skip_on_error)
    finally:
        t.close()

def load_rev_file(fname):
    files = {}
    try:
        with open(fname, "r") as fp:
            for line in fp:
                parts = line.strip().split("\t")
                files[parts[0]] = (int(parts[1]), int(parts[2]), int(parts[3]) if len(parts) > 3 else -1)
    except:
        pass
    print("[\033[32m+\033[0m] Loaded %d files from %s" % (len(files), fname))
    return files

def save_rev_file(fname, files):
    with open(fname, "w") as fp:
        for f, data in files.iteritems():
            fp.write("%s\t%d\t%d\t%d\n" % (
                f,
                data[0],
                data[1],
                data[2]))
    print("[\033[32m+\033[0m] Saved %d files to %s" % (len(files), fname))

def build_rev_file(sftp, remoteroot, localroot, exclude, dry_run):
    fname = os.path.join(localroot, '.files')
    if os.path.lexists(fname):
        c = raw_input("[\033[33m?\033[0m] File already exists. Override?[y/n]").lower()
        if c != 'y':
            return False
    remote_files = {}
    local_files = {}
    for root, dirs, files in walk(sftp, remoteroot):
        for f in files:
            filename = os.path.join(root, f.filename)
            if exclude and exclude.match(filename) \
               or filename[-1] == '~' or filename.endswith('.swp') or filename.endswith('.swo'):
                continue
            
            remote_files[filename] = (
                int(f.st_mtime),
                int(f.st_size),
                int(f.st_mode)
                )

            sys.stdout.write("\r\x1b[K[\033[34m*\033[0m] \033[33mTesting\033[0m %s" % (
                filename
                    if len(filename) < 50
                    else
                        filename[:25] + '...' + filename[-25:],))

            sys.stdout.flush()
    for root, dirs, files in os.walk(localroot):
        relroot = os.path.relpath(root, localroot)
        for f in files:
            filename = os.path.join(relroot, f)
            s = os.lstat(os.path.join(root, f))
            local_files[filename] = (
                    int(s.st_mtime),
                    int(s.st_size),
                    int(s.st_mode)
                    )

    sys.stdout.write("\n")
    files = dict([(k,v) for k,v in remote_files.iteritems() if k in local_files])
    save_rev_file(fname, files)


def check_dir(sftp, root, path, dryrun=False):
    curpath = root
    for segment in path.split('/'):
        curpath = os.path.join(curpath, segment)
        s = None
        try:
            s = sftp.lstat(curpath)
        except:
            pass

        if not s:
            print("  Creating directory %s" % curpath)
            if not dryrun:
                sftp.mkdir(curpath)

def sync(sftp, remote, local, direction='down', exclude=None, dry_run=False, skip_on_error=False):
    print ("[\033[34m*\033[0m] Syncing %s <-> %s" % (remote, local))
    c = raw_input("Continue?[y/n]").lower()
    if c != 'y':
        return False
    cmds = {'down' : sync_down, 'up' :sync_up, 'init' : build_rev_file}
    if direction == 'both':
        cmds['down'](sftp, remote, local, exclude, dry_run, skip_on_error)
        cmds['up'](sftp, remote, local, exclude, dry_run, skip_on_error)
    else:
        return cmds[direction](sftp, remote, local, exclude, dry_run, skip_on_error)

def print_file_info(filename, f):
    print("\n[\033[32m+\033[0m] New file: %s" % filename)
    print("  Size: %d\n  UID: %d\n  GID: %d\n  Mode: %o\n  Accesstime: %d\n  Modtime: %d" %(
                    f.st_size, f.st_uid, f.st_gid, f.st_mode, f.st_atime, f.st_mtime))

def different(sftp, filename, filea, fileb):
    if filea[2] & 0o777000 != fileb[2] & 0o777000 and filea[2] != -1:
        print("\n[\033[32m+\033[0m] Differencees in %s" % filename)
        print("    Mode: %o vs %o" % (filea[2], fileb[2]))
        return True
    elif stat.S_ISLNK(filea[2]): # symlink
        rtarget = sftp.readlink(os.path.join(remote, filename))
        ltarget = os.readlink(os.path.join(local, filename))
        if ltarget != rtarget:
            print("\n[\033[32m+\033[0m] Differencees in %s" % filename)
            print("    Target: %s vs %s" % (ltarget, rtarget))
            return True

    elif (filea[0] < fileb[0] or
        filea[0] == fileb[0] and filea[1] != fileb[1]):
        print("\n[\033[32m+\033[0m] Differencees in %s" % filename)
        print("    Time: %r vs %r" % (filea[0], fileb[0]))
        print("    Size: %r vs %r" % (filea[1], fileb[1]))
        return True
    return False

def sync_down(sftp, remote, local, exclude, dry_run, skip_on_error):
    if not os.path.lexists(local):
        os.mkdir(local)
    local_files = load_rev_file(os.path.join(local, '.files'))
    remote_files = {}
    
    for root, dirs, files in walk(sftp, remote):
        lroot = os.path.join(local, root)
        if not os.path.lexists(lroot) and not dry_run:
            os.mkdir(lroot)

        for f in files:
            filename = os.path.join(root, f.filename)

            if exclude and exclude.match(filename) \
               or filename[-1] == '~' or filename.endswith('.swp') or filename.endswith('.swo'):
                continue
            
            sys.stdout.write("\r\x1b[K[\033[34m*\033[0m] \033[33mTesting\033[0m %s" % (
                filename
                    if len(filename) < 50
                    else
                        filename[:25] + '...' + filename[-25:],))

            sys.stdout.flush()
            remote_files[filename] = (
                    int(f.st_mtime),
                    int(f.st_size),
                    int(f.st_mode)
                    )

            download = False
            if filename not in local_files:
                print_file_info(filename, f)
                download = True
            else:
                lfile = local_files[filename]
                rfile = remote_files[filename]
                download = different(sftp, filename, lfile, rfile)

            if download:
                print("\n[\033[34m*\033[0m] Downloading: %s" % filename)
                total = 0
                size = remote_files[filename][1]
                mtime = remote_files[filename][0]
                lfile = os.path.join(local, filename)

                try:

                    if os.path.lexists(lfile):
                        if (int(os.lstat(lfile).st_mtime) > mtime or
                            int(os.lstat(lfile).st_size) != size and
                            int(os.lstat(lfile).st_mtime) == mtime):
                            raise ValueError("Conflict with file %s" % filename)
                        if (int(os.lstat(lfile).st_mtime) == mtime and
                            int(os.lstat(lfile).st_size) == size):
                            print("\n[\033[34m+\033[0m] Already downloaded")
                            continue
    
                    #with sftp.open(os.path.join(remote, filename), 'rb') as fr:
                    #    with open(lfile, 'wb') as fl:
                    #        while True:
                    #            start = time.time()
                    #            data = fr.read(4096*100)
                    #            elapsed = time.time() - start
                    #            if not data:
                    #                break
                    #            total += len(data)
                    #            fl.write(data)

                    #            speed = len(data) / elapsed * 8.0
                    #            if speed > 1024**2:
                    #                speed = "%.2f Mb/s" % (speed / 1024**2,)
                    #            elif speed > 1024:
                    #                speed = "%.2f kb/s" % (speed / 1024,)
                    #            else:
                    #                speed = "%f b/s" % speed
                    #            sys.stdout.write("\r%02d%% %d/%d %s" % (
                    #                total * 100/size, total, size, speed))
                    #            sys.stdout.flush()
                    start = time.time()
                    def status(total, size):
                        if size == 0:
                            return

                        speed = total / (time.time() - start) * 1.0
                        if speed > 1024**2:
                            speed = "%.2f MiByte/s" % (speed / 1024**2,)
                        elif speed > 1024:
                            speed = "%.2f KiByte/s" % (speed / 1024,)
                        else:
                            speed = "%f Byte/s" % speed

                        sys.stdout.write("\r%02d%% %d/%d %s" % (
                            total * 100/size, total, size, speed))
                        sys.stdout.flush()

                    if not dry_run:
                        rfile = os.path.join(remote, filename)
                        if stat.S_ISLNK(f.st_mode):
                            target = sftp.readlink(rfile)
                            print("[\033[34m*\033[0m] Creating local symlink %s -> %s" % (lfile, target))
                            try:
                                os.symlink(target, lfile)
                            except OSError as e:
                                print("[\033[31m!\033[0m] Failed: %s" % (e))
                        else:
                            sftp.get(rfile, lfile, status)
                            os.utime(lfile, (mtime,mtime))
                    sys.stdout.write("\n")
                except ValueError:
                    del remote_files[filename]
                    local_files.update(remote_files)
                    if not dry_run:
                        save_rev_file(os.path.join(local, '.files'), local_files)
                    raise
                except KeyboardInterrupt:
                    del remote_files[filename]
                    local_files.update(remote_files)
                    if not dry_run:
                        os.unlink(lfile)
                        save_rev_file(os.path.join(local, '.files'), local_files)
                    exit(1)
                except Exception as e:
                    del remote_files[filename]
                    if not dry_run and filename not in local_files:
                        os.unlink(lfile)
                    if not skip_on_error:
                        local_files.update(remote_files)
                        if not dry_run:
                            save_rev_file(os.path.join(local, '.files'), local_files)
                        raise
                    else:
                        if filename in local_files: # prevent deletion
                            remote_files[filename] = local_files[filename]
                        print("[\033[31m!\033[0m Error during downloading %s: %s" % (filename, str(e)))
    sys.stdout.write("\n")


    for filename in local_files.keys():
        if filename not in remote_files:
            print("[\033[31m-\033[0m] Deleted file: %s" % filename)
            print(" Last mod time: %d\n Size: %d\n Mode: %o" % local_files[filename])
            if not dry_run and os.path.lexists(os.path.join(local, filename)):
                answer = raw_input("[\033[36m?\033[0m] Delete it locally?[y/n]")
                if answer == 'y':
                    os.unlink(os.path.join(local, filename))

    if not dry_run:
        save_rev_file(os.path.join(local, '.files'), remote_files)

def sync_up(sftp, remote, local, exclude, dry_run, skip_on_error):
    sftp.lstat(remote)

    remote_files = load_rev_file(os.path.join(local, '.files'))
    local_files = {}
    for root, dirs, files in os.walk(local):
        for d in dirs:
            path = os.path.relpath(os.path.join(root, d), local)
            check_dir(sftp, remote, path, dry_run)

        for f in files:
            if f in ('.files',):
                continue

            lfile = os.path.join(root,f)
            filename = os.path.relpath(lfile, local)
            if filename.split(os.path.sep)[0] == os.path.curdir:
                filename = filename[2:]

            if exclude and exclude.match(filename) \
               or filename[-1] == '~' or filename.endswith('.swp') or filename.endswith('.swo'):
                continue

            rfile = os.path.join(remote, filename)
            s = os.lstat(lfile)
            sys.stdout.write("\r\x1b[K[\033[34m*\033[0m] \033[33mTesting\033[0m %s" % (filename if len(filename) < 50 else
                    filename[:25] + '...' + filename[-25:],))
            sys.stdout.flush()
            local_files[filename] = (int(s.st_mtime), int(s.st_size), int(s.st_mode))

            upload = False
            if filename not in remote_files:
                print_file_info(filename, s)
                upload = True
            else:
                lf = local_files[filename]
                rf = remote_files[filename]
                upload = different(sftp, filename, lf, rf)

            if upload:
                print("\n[\033[34m*\033[0m] Uploading: %s" % filename)
                try:
                    try:
                        rstat = sftp.lstat(rfile)
                    except:
                        pass
                    else:
                        if rstat.st_mtime > s.st_mtime:
                            raise ValueError("Conflict with file %s" % filename)

                    start = time.time()
                    def status(total, size):
                        if size == 0:
                            return

                        speed = total / (time.time() - start) * 1.0
                        if speed > 1024**2:
                            speeds = "%.2f MiByte/s" % (speed / 1024**2,)
                        elif speed > 1024:
                            speeds = "%.2f KiByte/s" % (speed / 1024,)
                        else:
                            speeds = "%f Byte/s" % speed
                        remaining = timedelta(seconds=int((size - total) / speed))

                        sys.stdout.write("\r%02d%% %d/%d %s %s" % (
                            total * 100/size, total, size, speeds, remaining))
                        sys.stdout.flush()

                    if not dry_run:
                        if stat.S_ISLNK(s.st_mode):
                            target = os.readlink(lfile)
                            print("[\033[34m*\033[0m] Creating remote symlink %s -> %s" % (rfile, target))
                            try:
                                sftp.symlink(target, rfile)
                            except paramiko.SSHException as e:
                                print("[\033[31m!\033[0m] Failed: %s" % (e))
                            except IOError:
                                pass

                        else:
                            sftp.put(lfile, rfile, status)
                            f = sftp.file(rfile)
                            f.utime((s.st_atime,s.st_mtime))
                            f.close()
                    sys.stdout.write("\n")
                except ValueError:
                    del local_files[filename]
                    remote_files.update(local_files)
                    if not dry_run:
                        save_rev_file(os.path.join(local, '.files'), remote_files)
                    raise
                except KeyboardInterrupt:
                    del local_files[filename]
                    if not dry_run:
                        sftp.unlink(rfile)
                    remote_files.update(local_files)
                    if not dry_run:
                        save_rev_file(os.path.join(local, '.files'), remote_files)
                    exit(1)
                except Exception as e:
                    del local_files[filename]
                    if not dry_run and filename not in remote_files:
                        sftp.unlink(rfile)
                    if not skip_on_error:
                        remote_files.update(local_files)
                        if not dry_run:
                            save_rev_file(os.path.join(local, '.files'), remote_files)
                        raise
                    else:
                        if filename in remote_files: # prevent deletion
                            local_files[filename] = remote_files[filename]
                        print("[\033[31m!\033[0m] Error during upload of %s: %s" % (filename, str(e)))
    sys.stdout.write("\n")

    for filename in remote_files.keys():
        if filename not in local_files:
            print("[\033[31m-\033[0m] Deleted file locally: %s" % filename)
            print(" Last mod time: %d\n Size: %d\n Mode: %o" % remote_files[filename])
            if not dry_run:
                try:
                    sftp.lstat(os.path.join(remote, filename))
                except:
                    print("Can't stat remote file. Maybe already deleted?")
                    continue
                answer = raw_input("[\033[36m?\033[0m] Delete it on remote?[y/n]")
                if answer == 'y':
                    sftp.unlink(os.path.join(remote, filename))

    remote_files.update(local_files)
    if not dry_run:
        save_rev_file(os.path.join(local, '.files'), remote_files)



def walk(sftp, root_directory):
    dirs = [root_directory]
    while dirs:
        directory = dirs.pop()
        entries = sftp.listdir_attr(directory)
        files = []
        directories = []
        for entry in entries:
            if stat.S_IFMT(entry.st_mode) == stat.S_IFDIR:
                directories.append(entry)
            else:
                files.append(entry)
        reldir = os.path.relpath(directory, root_directory)
        segments = reldir.split(os.path.sep)
        if segments[0] == os.path.curdir:
            reldir = os.path.sep.join(segments[1:])
        yield reldir, directories, files
        for dir in directories:
            dirs.append(os.path.join(directory, dir.filename))


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
        print('[\033[34m*\033[0m] Trying ssh-agent key %s' % hexlify(key.get_fingerprint()), end="")
        try:
            transport.auth_publickey(username, key)
            print('... \033[32msuccess!\033[0m')
            return
        except paramiko.SSHException:
            print('... \033[31mnope.\033[0m')

def manual_auth(username, hostname, t):
    default_auth = 'p'
    auth = raw_input('[\033[36m?\033[0m] Auth by (p)assword, (r)sa key, or (d)ss key? [%s] ' % default_auth)
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
        path = raw_input('DSS key [%s]: ' % default_path)
        if len(path) == 0:
            path = default_path
        try:
            key = paramiko.DSSKey.from_private_key_file(path)
        except paramiko.PasswordRequiredException:
            password = getpass.getpass('DSS key password: ')
            key = paramiko.DSSKey.from_private_key_file(path, password)
        t.auth_publickey(username, key)
    else:
        pw = getpass.getpass('Password for %s@%s: ' % (username, hostname))
        t.auth_password(username, pw)


def connect(hostname, port, username, hostkey):
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
