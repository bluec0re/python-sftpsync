#  vim: set ts=8 sw=4 tw=0 fileencoding=utf-8 filetype=python expandtab:
from __future__ import print_function, absolute_import, division, unicode_literals

from datetime import timedelta
import sys
import os
import stat
import time
from collections import namedtuple
import logging
from helperlib import prompt, info, success, error, warning, spinner
from helperlib.logging import scope_logger

import paramiko
import re

__author__ = 'bluec0re'


MTIME = 0
SIZE = 1
MODE = 2

File = namedtuple('File', ('mtime', 'size', 'mode'))


def to_unicode(s):
    if sys.version_info >= (3, 0, 0):
        if isinstance(s, str):
            return s
    else:
        if isinstance(s, unicode):
            return s

    try:
        return s.decode('ascii')
    except UnicodeError:
        try:
            return s.decode('utf-8')
        except UnicodeError:
            return s


def string_shortener(string, max_len=50):
    if len(string) <= max_len:
        return string

    return string[:max_len//2-2] + '...' + string[-max_len//2-1:]


def print_file_info(filename, f):
    print()
    success("New file: %s" % filename)
    print("  Size: %d\n  UID: %d\n  GID: %d\n  Mode: %o\n  Accesstime: %d\n  Modtime: %d" %(
          f.st_size, f.st_uid, f.st_gid, f.st_mode, f.st_atime, f.st_mtime))


def print_file_info2(filename, f):
    print()
    success("File: %s" % filename)
    print("  Size: %d\n  Mode: %o\n  Modtime: %d" %(
          f[SIZE], f[MODE], f[MTIME]))


def different(sftp, filename, other, current, local, remote):
    if (other[MODE] & 0o777000) != (current[MODE] & 0o777000) and \
       other[MODE] != -1:
        print()
        success("Differences in %s" % filename)
        print("         dst vs src")
        print("    Mode: %o vs %o" % (other[MODE], current[MODE]))
        return True
    elif stat.S_ISLNK(other[MODE]): # symlink
        rtarget = sftp.readlink(os.path.join(remote, filename))
        ltarget = os.readlink(os.path.join(local, filename))
        if ltarget != rtarget:
            print()
            success("Differences in %s" % filename)
            print("         dst vs src")
            print("    Target: %s vs %s" % (ltarget, rtarget))
            return True

    elif (other[MTIME] < current[MTIME] or
        (other[MTIME] == current[MTIME] and other[SIZE] != current[SIZE])):
        print()
        success("Differences in %s" % filename)
        print("         dst vs src")
        print("    Time: %r vs %r" % (other[MTIME], current[MTIME]))
        print("    Size: %r vs %r" % (other[SIZE], current[SIZE]))
        return True
    return False


@scope_logger
class RevisionFile(dict):

    def __init__(self, fname):
        super(RevisionFile, self).__init__()
        self.fname = fname

    def add(self, fn, *args):
        args = [int(arg) for arg in args[:3]]
        if len(args) < 3:
            args.append(-1)

        self[fn] = File(*args)

    def load(self):
        if not os.path.exists(self.fname):
            self.log.warning('Revisionfile %s does not exist', self.fname)
            return

        with open(self.fname, "r") as fp:
            for line in fp:
                parts = line.strip().split("\t")
                fn = to_unicode(parts[0])
                self.add(fn, *parts[1:])
        self.log.info('Loaded %d files from %s', len(self), self.fname)

    def save(self):
        with open(self.fname, "w") as fp:
            for f, data in self.iteritems():
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
        self.log.info('Saved %d files to %s', len(self), self.fname)


def load_rev_file(fname):
    files = RevisionFile(fname)
    files.load()
    return files


def save_rev_file(fname, files):
    if not isinstance(files, RevisionFile):
        tmp = RevisionFile(fname)
        tmp.update(files)
        files = tmp
    else:
        files.fname = fname
    files.save()


class Sync(object):
    def __init__(self, sftp, remote, local, exclude=None, skip_on_error=False, subdir=None, dry_run=False):
        self.sftp = sftp
        self.subdir = subdir or ''
        self.remote_root = remote
        self.local_root = local
        self.local = os.path.join(local, self.subdir)
        self.remote = os.path.join(remote, self.subdir)
        self.exclude = exclude
        if isinstance(self.exclude, str):
            self.exclude = re.compile(self.exclude)
        self.skip_on_error = skip_on_error
        self.dry_run = dry_run

        fname = os.path.join(self.local_root, '.files')
        self.revision_file = RevisionFile(fname)
        self.revision_file.load()

    def build_rev_file(self, *args, **kwargs):
        if not os.path.lexists(self.local_root):
            os.mkdir(self.local_root)

        if self.revision_file:
            c = prompt("File already exists. Override?[y/n]").lower()
            if c != 'y':
                return False
        remote_files = {}
        local_files = {}
        spinner.waitfor('Searching remote')
        for root, dirs, files in self.walk():
            for f in files:
                filename = os.path.join(root, f.filename)
                if self._exclude(filename):
                    continue

                remote_files[filename] = File(
                    int(f.st_mtime),
                    int(f.st_size),
                    int(f.st_mode)
                )

                spinner.status(string_shortener(filename))
        spinner.succeeded()

        spinner.waitfor('Searching local')
        for root, dirs, files in os.walk(self.local):
            root = to_unicode(root)
            relroot = os.path.relpath(root, self.local)
            for f in files:
                f = to_unicode(f)
                filename = os.path.join(relroot, f)
                s = os.lstat(os.path.join(root, f))
                local_files[filename] = File(
                                             int(s.st_mtime),
                                             int(s.st_size),
                                             int(s.st_mode)
                                            )
                spinner.status(string_shortener(filename))
        spinner.succeeded()

        files = dict([(k, v) for k, v in remote_files.iteritems() if k in local_files])
        self.revision_file = RevisionFile(os.path.join(self.local_root, '.files'))
        self.revision_file.update(files)
        self.revision_file.save()

    def _exclude(self, path):
        if self.exclude and self.exclude.match(path):
            return True

        basename = os.path.basename(path)
        if path[-1] == '~' or path.endswith('.swp') or path.endswith('.swo') \
           or basename.startswith('.~') or basename.startswith("~$"):
            return True

        return False

    def check_dir(self, path):
        current_path = self.remote
        for segment in path.split('/'):
            current_path = os.path.join(current_path, segment)
            s = None
            try:
                s = self.sftp.lstat(current_path)
            except KeyboardInterrupt:
                raise
            except:
                pass

            if not s:
                print("  Creating directory %s" % current_path)
                if not self.dry_run:
                    self.sftp.mkdir(current_path)

    def walk(self):
        directory_stack = [self.remote]
        while directory_stack:
            directory = directory_stack.pop()
            if self._exclude(directory):
                continue

            entries = self.sftp.listdir_attr(directory)
            files = []
            directories = []
            for entry in entries:
                if stat.S_IFMT(entry.st_mode) == stat.S_IFDIR:
                    directories.append(entry)
                else:
                    files.append(entry)

            relative_dir = os.path.relpath(directory, self.remote)

            segments = relative_dir.split(os.path.sep, 1)
            if segments[0] == os.path.curdir:
                if len(segments) > 1:
                    relative_dir = segments[1]
                else:
                    relative_dir = ''

            yield relative_dir, directories, files

            for current_dir in directories:
                directory_stack.append(os.path.join(directory, current_dir.filename))

    def check_revision_against_remote(self):
        for root, dirs, files in self.walk():
            for f in files:
                filename = os.path.join(root, f.filename)
                rfile = os.path.join(self.remote, filename)

                rdata = File(
                        int(f.st_mtime),
                        int(f.st_size),
                        int(f.st_mode)
                )

                if filename not in self.revision_file:
                    error("File only on remote")
                    print_file_info2(filename, rdata)
                elif different(self.sftp, filename, rdata, self.revision_file[filename], self.local, self.remote):
                    del self.revision_file[filename]
                else:
                    del self.revision_file[filename]

        for filename, ldata in self.revision_file.items():
            error("File only in revision file\n")
            print_file_info2(filename, ldata)

    def list_local_changes(self, *args, **kwargs):
        local_files = {}
        for root, dirs, files in os.walk(self.local):
            root = to_unicode(root)
            if self._exclude(root):
                continue

            for d in dirs:
                d = to_unicode(d)
                path = os.path.relpath(os.path.join(root, d), self.local)
                if self._exclude(path):
                    continue

            for f in files:
                f = to_unicode(f)
                if f in ('.files',):
                    continue

                lfile = os.path.join(root, f)
                filename = os.path.relpath(lfile, self.local)
                if filename.split(os.path.sep)[0] == os.path.curdir:
                    filename = filename[2:]

                if self._exclude(lfile):
                    continue

                rfile = os.path.join(self.remote, filename)
                s = os.lstat(lfile)
                sys.stdout.flush()
                local_files[filename] = File(int(s.st_mtime),
                                             int(s.st_size),
                                             int(s.st_mode))

                if filename not in self.revision_file:
                    print("New: {}".format(filename))
                else:
                    lf = local_files[filename]
                    rf = self.revision_file[filename]
                    if different(self.sftp, filename, rf, lf, self.local, self.remote):
                        print("Changed: {}".format(filename))

    def _check_local(self, lfile, lfilename, rfile, rfilename):
        if os.path.lexists(lfilename):
            stat = os.lstat(lfilename)
            mtime, size = map(int, (stat.st_mtime, stat.st_size))
            if lfile and mtime != lfile.mtime:
                if lfile.mtime != rfile.mtime and mtime != rfile.mtime:
                    raise ValueError("Conflict with file %s (Both modified (different timestamp))" % rfilename)
            if mtime > rfile.mtime:
                raise ValueError("Conflict with file %s (local file is newer)" % rfilename)

            if (size != rfile.size and
                mtime == rfile.mtime):
                raise ValueError("Conflict with file %s (size differs)" % rfilename)

            if (mtime == rfile.mtime and
                size == rfile.size):
                print()
                success("Already downloaded\n")
                return False
        return True

    def down(self):
        if not os.path.lexists(self.local_root):
            os.mkdir(self.local_root)

        self.revision_file.load()
        revision_file = self.revision_file
        remote_files = {}

        spinner.waitfor('Testing')
        for root, dirs, files in self.walk():
            lroot = os.path.join(self.local, root)
            if self._exclude(lroot):
                sys.stdout.write("\r[\033[33m#\033[0m] Skipping {0}".format(lroot))
                continue

            if not os.path.lexists(lroot) and not self.dry_run:
                os.mkdir(lroot)

            if self.subdir:
                root = os.path.join(self.subdir, root)

            for f in files:
                filename = os.path.join(root, f.filename)

                if self._exclude(filename):
                    continue

                spinner.status(string_shortener(filename))

                remote_files[filename] = File(
                                              int(f.st_mtime),
                                              int(f.st_size),
                                              int(f.st_mode)
                                             )

                if filename not in revision_file:
                    print_file_info(filename, f)
                    download = True
                else:
                    lfile = revision_file[filename]
                    rfile = remote_files[filename]
                    download = different(self.sftp, filename, lfile, rfile, self.local_root, self.remote_root)

                if download:
                    spinner.succeeded()
                    info("Downloading: %s\n" % filename)
                    mtime = remote_files[filename][0]
                    lfilename = os.path.join(self.local_root, filename)

                    try:

                        if not self._check_local(revision_file.get(filename), lfilename, remote_files[filename], filename):
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

                        if not self.dry_run:
                            rfilename = os.path.join(self.remote_root, filename)
                            if stat.S_ISLNK(f.st_mode):
                                target = self.sftp.readlink(rfilename)
                                info("Creating local symlink %s -> %s\n" % (lfilename, target))
                                try:
                                    os.symlink(target, lfilename)
                                except OSError as e:
                                    error("Failed: %s\n" % (e))
                            else:
                                self.sftp.get(rfilename, lfilename, status)
                                os.utime(lfilename, (mtime, mtime))
                        spinner.waitfor('Testing')
                    except ValueError:
                        del remote_files[filename]
                        revision_file.update(remote_files)
                        if not self.dry_run:
                            revision_file.save()
                        raise
                    except KeyboardInterrupt:
                        del remote_files[filename]
                        revision_file.update(remote_files)
                        if not self.dry_run:
                            os.unlink(lfile)
                            revision_file.save()
                        exit(1)
                    except Exception as e:
                        del remote_files[filename]
                        if not self.dry_run and filename not in revision_file:
                            try:
                                os.unlink(lfile)
                            except:
                                pass
                        if not self.skip_on_error:
                            revision_file.update(remote_files)
                            if not self.dry_run:
                                revision_file.save()
                            raise
                        else:
                            if filename in revision_file: # prevent deletion
                                remote_files[filename] = revision_file[filename]
                            error("Error during downloading %s: %s\n" % (filename, str(e)))
        spinner.succeeded()

        for filename in revision_file.keys():
            if self.subdir:
                if not filename.startswith(self.subdir):
                    continue
            if filename not in remote_files and not self._exclude(filename):
                warning("Deleted file: %s\n" % filename)
                print(" Last mod time: %d\n Size: %d\n Mode: %o" % revision_file[filename])
                if not self.dry_run:
                    if not os.path.lexists(os.path.join(self.local_root, filename)):
                        warning("Already deleted?\n")
                        del revision_file[filename]
                        continue

                    answer = prompt("Delete it locally?[y/n]")
                    if answer == 'y':
                        os.unlink(os.path.join(self.local_root, filename))
                        del revision_file[filename]

        revision_file.update(remote_files)

        if not self.dry_run:
            revision_file.save()

    def up(self):

        self.sftp.lstat(self.remote)

        local_files = {}
        spinner.waitfor('Testing')
        for root, dirs, files in os.walk(self.local):
            root = to_unicode(root)
            if self._exclude(root):
                continue

            for d in dirs:
                d = to_unicode(d)
                path = os.path.relpath(os.path.join(root, d), self.local)
                if self._exclude(path):
                    continue
                self.check_dir(path)

            if self.subdir:
                root = os.path.join(self.subdir, root)

            for f in files:
                f = to_unicode(f)
                if f in ('.files',):
                    continue

                lfile = os.path.join(root, f)
                filename = os.path.relpath(lfile, self.local_root)
                if filename.split(os.path.sep)[0] == os.path.curdir:
                    filename = filename[2:]

                if self._exclude(lfile):
                    continue

                rfile = os.path.join(self.remote_root, filename)
                s = os.lstat(lfile)
                spinner.status(string_shortener(filename))

                local_files[filename] = File(int(s.st_mtime), int(s.st_size), int(s.st_mode))

                upload = False
                if filename not in self.revision_file:
                    print_file_info(filename, s)
                    upload = True
                else:
                    lf = local_files[filename]
                    rf = self.revision_file[filename]
                    upload = different(self.sftp, filename, rf, lf, self.local_root, self.remote_root)

                if upload:
                    spinner.succeeded()
                    info(" Uploading: %s\n" % filename)
                    try:
                        try:
                            rstat = self.sftp.lstat(rfile)
                        except KeyboardInterrupt:
                            raise
                        except:
                            pass
                        else:
                            if rstat.st_mtime > s.st_mtime:
                                raise ValueError("Conflict with file %s (remote file is newer)" % filename)

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

                        if not self.dry_run:
                            if stat.S_ISLNK(s.st_mode):
                                target = os.readlink(lfile)
                                print()
                                info("Creating remote symlink %s -> %s\n" % (rfile, target))
                                try:
                                    self.sftp.symlink(target, rfile)
                                except paramiko.SSHException as e:
                                    error("Failed: %s\n" % (e,))
                                except IOError:
                                    pass

                            else:
                                self.sftp.put(lfile, rfile, status)
                                f = self.sftp.file(rfile)
                                f.utime((s.st_atime, s.st_mtime))
                                f.close()
                        spinner.waitfor('Testing')
                    except ValueError:
                        del local_files[filename]
                        self.revision_file.update(local_files)
                        if not self.dry_run:
                            self.revision_file.save()
                        raise
                    except KeyboardInterrupt:
                        del local_files[filename]
                        if not self.dry_run:
                            self.sftp.unlink(rfile)
                        self.revision_file.update(local_files)
                        if not self.dry_run:
                            self.revision_file.save()
                        exit(1)
                    except Exception as e:
                        del local_files[filename]
                        if not self.dry_run and filename not in self.revision_file:
                            self.sftp.unlink(rfile)
                        if not self.skip_on_error:
                            self.revision_file.update(local_files)
                            if not self.dry_run:
                                self.revision_file.save()
                            raise
                        else:
                            if filename in self.revision_file: # prevent deletion
                                local_files[filename] = self.revision_file[filename]
                            error("Error during upload of %s: %s\n" % (filename, str(e)))
        spinner.succeeded()

        for filename in self.revision_file.keys():
            if self.subdir:
                if not filename.startswith(self.subdir):
                    continue
            if filename not in local_files and not self._exclude(filename):
                warning("Deleted file locally: %s\n" % filename)
                print(" Last mod time: %d\n Size: %d\n Mode: %o" % self.revision_file[filename])
                if not self.dry_run:
                    try:
                        self.sftp.lstat(os.path.join(self.remote_root, filename))
                    except KeyboardInterrupt:
                        raise
                    except:
                        warning("Can't stat remote file. Maybe already deleted?\n")
                        del self.revision_file[filename]
                        continue
                    answer = prompt("Delete it on remote?[y/n]")
                    if answer == 'y':
                        self.sftp.unlink(os.path.join(self.remote_root, filename))
                        del self.revision_file[filename]

        self.revision_file.update(local_files)
        if not self.dry_run:
            self.revision_file.save()


def sync(sftp, remote, local, direction='down', exclude=None, dry_run=False, skip_on_error=False, subdir=None):
    sync = Sync(sftp, remote, local, exclude, skip_on_error, subdir, dry_run)
    if direction == 'check':
        sync.check_revision_against_remote()
        return
    elif direction == 'list':
        sync.list_local_changes()
        return

    if subdir:
        info("Syncing %s <-> %s with subdir %s\n" % (remote, local, subdir))
    else:
        info("Syncing %s <-> %s\n" % (remote, local))
    c = prompt("Continue?[y/n]").lower()
    if c != 'y':
        return False

    if direction == 'both':
        sync.down()
        sync.up()
    elif direction == 'down':
        return sync.down()
    elif direction == 'up':
        return sync.up()
    elif direction == 'init':
        return sync.build_rev_file()

