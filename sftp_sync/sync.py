from datetime import timedelta
import sys
import os
import stat
import time

import paramiko

__author__ = 'bluec0re'


MTIME = 0
SIZE = 1
MODE = 2

def to_unicode(s):
    try:
        return s.decode('ascii')
    except UnicodeError:
        try:
            return s.decode('utf-8')
        except UnicodeError:
            return s

def load_rev_file(fname):
    files = {}
    try:
        with open(fname, "r") as fp:
            for line in fp:
                parts = line.strip().split("\t")
                fn = to_unicode(parts[0])
                files[fn] = (int(parts[MTIME+1]), int(parts[SIZE+1]), int(parts[MODE+1]) if len(parts) > 3 else -1)
    except IOError:
        pass
    print("[\033[32m+\033[0m] Loaded %d files from %s" % (len(files), fname))
    return files


def save_rev_file(fname, files):
    with open(fname, "w") as fp:
        for f, data in files.iteritems():
            try:
                f = f.encode('utf-8')
            except UnicodeDecodeError:
                pass
            line = ("%s\t%d\t%d\t%d\n" % (
                f,
                data[MTIME],
                data[SIZE],
                data[MODE]))
            fp.write(line)
    print("[\033[32m+\033[0m] Saved %d files to %s" % (len(files), fname))


def build_rev_file(sftp, remoteroot, localroot, exclude, dry_run, *args, **kwargs):
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
               or filename[-1] == '~' or filename.endswith('.swp') or filename.endswith('.swo') or \
               f.filename.startswith('.~'):
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
        root = to_unicode(root)
        relroot = os.path.relpath(root, localroot)
        for f in files:
            f = to_unicode(f)
            filename = os.path.join(relroot, f)
            s = os.lstat(os.path.join(root, f))
            local_files[filename] = (
                    int(s.st_mtime),
                    int(s.st_size),
                    int(s.st_mode)
                    )

    sys.stdout.write("\n")
    files = dict([(k, v) for k, v in remote_files.iteritems() if k in local_files])
    save_rev_file(fname, files)


def check_dir(sftp, root, path, dryrun=False):
    curpath = root
    for segment in path.split('/'):
        curpath = os.path.join(curpath, segment)
        s = None
        try:
            s = sftp.lstat(curpath)
        except KeyboardInterrupt:
            raise
        except:
            pass

        if not s:
            print("  Creating directory %s" % curpath)
            if not dryrun:
                sftp.mkdir(curpath)


def sync(sftp, remote, local, direction='down', exclude=None, dry_run=False, skip_on_error=False, subdir=None):
    if direction == 'check':
        check_revision_against_remote(sftp, remote, local)
        return
    elif direction == 'list':
        list_local_changes(sftp, remote, local, exclude, dry_run)
        return

    if subdir:
        print ("[\033[34m*\033[0m] Syncing %s <-> %s with subdir %s" % (remote, local, subdir))
    else:
        print ("[\033[34m*\033[0m] Syncing %s <-> %s" % (remote, local))
    c = raw_input("Continue?[y/n]").lower()
    if c != 'y':
        return False
    cmds = {'down' : sync_down, 'up' :sync_up, 'init' : build_rev_file}
    if direction == 'both':
        cmds['down'](sftp, remote, local, exclude, dry_run, skip_on_error, subdir)
        cmds['up'](sftp, remote, local, exclude, dry_run, skip_on_error, subdir)
    else:
        return cmds[direction](sftp, remote, local, exclude, dry_run, skip_on_error, subdir)


def print_file_info(filename, f):
    print("\n[\033[32m+\033[0m] New file: %s" % filename)
    print("  Size: %d\n  UID: %d\n  GID: %d\n  Mode: %o\n  Accesstime: %d\n  Modtime: %d" %(
                    f.st_size, f.st_uid, f.st_gid, f.st_mode, f.st_atime, f.st_mtime))
def print_file_info2(filename, f):
    print("\n[\033[32m+\033[0m] File: %s" % filename)
    print("  Size: %d\n  Mode: %o\n  Modtime: %d" %(
                    f[SIZE], f[MODE], f[MTIME]))

def different(sftp, filename, other, current, local, remote):
    if other[MODE] & 0o777000 != current[MODE] & 0o777000 and other[MODE] != -1:
        print("\n[\033[32m+\033[0m] Differencees in %s" % filename)
        print("         dst vs src")
        print("    Mode: %o vs %o" % (other[MODE], current[MODE]))
        return True
    elif stat.S_ISLNK(other[MODE]): # symlink
        rtarget = sftp.readlink(os.path.join(remote, filename))
        ltarget = os.readlink(os.path.join(local, filename))
        if ltarget != rtarget:
            print("\n[\033[32m+\033[0m] Differencees in %s" % filename)
            print("         dst vs src")
            print("    Target: %s vs %s" % (ltarget, rtarget))
            return True

    elif (other[MTIME] < current[MTIME] or
        (other[MTIME] == current[MTIME] and other[SIZE] != current[SIZE])):
        print("\n[\033[32m+\033[0m] Differencees in %s" % filename)
        print("         dst vs src")
        print("    Time: %r vs %r" % (other[MTIME], current[MTIME]))
        print("    Size: %r vs %r" % (other[SIZE], current[SIZE]))
        return True
    return False


def sync_down(sftp, remote, local, exclude, dry_run, skip_on_error, subdir=None):
    if not subdir:
        subdir = ''

    if not os.path.lexists(local):
        os.mkdir(local)
    local_files = load_rev_file(os.path.join(local, '.files'))
    remote_files = {}
    newlocal = os.path.join(local, subdir)
    newremote = os.path.join(remote, subdir)

    for root, dirs, files in walk(sftp, newremote):
        lroot = os.path.join(newlocal, root)
        if exclude and exclude.match(lroot):
            sys.stdout.write("\r[\033[33m#\033[0m] Skipping {0}".format(lroot))
            continue

        if not os.path.lexists(lroot) and not dry_run:
            os.mkdir(lroot)

        for f in files:
            filename = os.path.join(root, f.filename)
            if subdir:
                filename = os.path.join(subdir, filename)

            if exclude and exclude.match(filename) \
               or filename[-1] == '~' or filename.endswith('.swp') or filename.endswith('.swo') \
               or f.filename.startswith('.~') or f.filename.startswith("~$"):
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
                download = different(sftp, filename, lfile, rfile, local, remote)

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
                        try:
                            os.unlink(lfile)
                        except:
                            pass
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
        if subdir:
            if not filename.startswith(subdir):
                continue
        if filename not in remote_files and not (exclude and exclude.match(filename)):
            print("[\033[31m-\033[0m] Deleted file: %s" % filename)
            print(" Last mod time: %d\n Size: %d\n Mode: %o" % local_files[filename])
            if not dry_run:
                if not os.path.lexists(os.path.join(local, filename)):
                    print("[\033[36m?\033[0m] Already deleted?")
                    del local_files[filename]
                    continue

                answer = raw_input("[\033[36m?\033[0m] Delete it locally?[y/n]")
                if answer == 'y':
                    os.unlink(os.path.join(local, filename))
                    del local_files[filename]

    remote_files.update(local_files)

    if not dry_run:
        save_rev_file(os.path.join(local, '.files'), remote_files)


def sync_up(sftp, remote, local, exclude, dry_run, skip_on_error, subdir=None):
    if subdir:
        newlocal = os.path.join(local, subdir)
        newremote = os.path.join(remote, subdir)
    else:
        newlocal = local
        newremote = remote

    sftp.lstat(newremote)

    remote_files = load_rev_file(os.path.join(local, '.files'))
    local_files = {}
    for root, dirs, files in os.walk(newlocal):
        root = to_unicode(root)
        if exclude and exclude.match(root):
            #print("[\033[33m#\033[0m] Skipping {0}".format(root))
            continue

        for d in dirs:
            d = to_unicode(d)
            path = os.path.relpath(os.path.join(root, d), newlocal)
            if exclude and exclude.match(path):
                continue
            check_dir(sftp, newremote, path, dry_run)

        for f in files:
            f = to_unicode(f)
            if f in ('.files',):
                continue

            lfile = os.path.join(root, f)
            filename = os.path.relpath(lfile, local)
            if filename.split(os.path.sep)[0] == os.path.curdir:
                filename = filename[2:]

            if exclude and exclude.match(lfile) \
               or filename[-1] == '~' or filename.endswith('.swp') or filename.endswith('.swo') \
               or f.startswith('.~') or f.startswith("~$"):
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
                upload = different(sftp, filename, rf, lf, local, remote)

            if upload:
                print("\n[\033[34m*\033[0m] Uploading: %s" % filename)
                try:
                    try:
                        rstat = sftp.lstat(rfile)
                    except KeyboardInterrupt:
                        raise
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
        if subdir:
            if not filename.startswith(subdir):
                continue
        if filename not in local_files and not (exclude and exclude.match(filename)):
            print("[\033[31m-\033[0m] Deleted file locally: %s" % filename)
            print(" Last mod time: %d\n Size: %d\n Mode: %o" % remote_files[filename])
            if not dry_run:
                try:
                    sftp.lstat(os.path.join(remote, filename))
                except KeyboardInterrupt:
                    raise
                except:
                    print("Can't stat remote file. Maybe already deleted?")
                    del remote_files[filename]
                    continue
                answer = raw_input("[\033[36m?\033[0m] Delete it on remote?[y/n]")
                if answer == 'y':
                    sftp.unlink(os.path.join(remote, filename))
                    del remote_files[filename]

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


def check_revision_against_remote(sftp, remote, local):
    local_files = load_rev_file(os.path.join(local, '.files'))

    for root, dirs, files in walk(sftp, remote):
        for f in files:
            filename = os.path.join(root, f.filename)
            rfile = os.path.join(remote, filename)

            rdata = (
                    int(f.st_mtime),
                    int(f.st_size),
                    int(f.st_mode)
                    )

            if filename not in local_files:
                print("[\033[33m!\033[0m] File only on remote")
                print_file_info2(filename, rdata)
            elif different(sftp, filename, rdata, local_files[filename], local, remote):
                del local_files[filename]
            else:
                del local_files[filename]

    for filename, ldata in local_files.items():
        print("[\033[33m!\033[0m] File only in revision file")
        print_file_info2(filename, ldata)


def list_local_changes(sftp, remote, local, exclude, dry_run):
    remote_files = load_rev_file(os.path.join(local, '.files'))
    local_files = {}
    for root, dirs, files in os.walk(local):
        root = to_unicode(root)
        if exclude and exclude.match(root):
            #print("[\033[33m#\033[0m] Skipping {0}".format(root))
            continue

        for d in dirs:
            d = to_unicode(d)
            path = os.path.relpath(os.path.join(root, d), local)
            if exclude and exclude.match(path):
                continue

        for f in files:
            f = to_unicode(f)
            if f in ('.files',):
                continue

            lfile = os.path.join(root, f)
            filename = os.path.relpath(lfile, local)
            if filename.split(os.path.sep)[0] == os.path.curdir:
                filename = filename[2:]

            if exclude and exclude.match(lfile) \
               or filename[-1] == '~' or filename.endswith('.swp') or filename.endswith('.swo') \
               or f.startswith('.~') or f.startswith("~$"):
                continue

            rfile = os.path.join(remote, filename)
            s = os.lstat(lfile)
            sys.stdout.flush()
            local_files[filename] = (int(s.st_mtime), int(s.st_size), int(s.st_mode))

            upload = False
            if filename not in remote_files:
                upload = True
                print("New: {}".format(filename))
            else:
                lf = local_files[filename]
                rf = remote_files[filename]
                upload = different(sftp, filename, rf, lf, local, remote)
                if upload:
                    print("Changed: {}".format(filename))
