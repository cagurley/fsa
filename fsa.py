# -*- coding: utf-8 -*-
"""
Created on Mon Apr  8 13:51:10 2019

@author: cagurl01
"""

import csv
import datetime as dt
import os
import pysftp
import re
import shutil
from time import sleep


class ConnDirectives:
    def __init__(self, ref, protocol, host, username, password, port):
        self.ref = ref
        self.protocol = protocol
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.ops = []
        self.access_time = None
        self.previous_time = None
        self.set_prev_time()

    def add_op(self, op):
        if op.conn_ref == self.ref:
            self.ops.append(op)
        return None

    def cycle_times(self):
        try:
            if self.access_time:
                rows = []
                with open('ref/TIMES.csv', newline='') as file:
                    reader = csv.reader(file)
                    for row in reader:
                        rows.append(row)
                for index, row in enumerate(rows):
                    if len(row) != 2 or row[0] == str(self.ref):
                        rows.pop(index)
                rows.append([str(self.ref), self.access_time.strftime('%c')])
                self.previous_time = self.access_time
                self.access_time = None
                with open('ref/TIMES.csv', 'w', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerows(rows)
        except IOError:
            log("IOError encountered attempting to open reference file `./ref/TIMES.csv`!")
            print("Error encountered attempting to open reference files; check to ensure they are located at `./ref`.")
        return None

    def set_access_time(self):
        self.access_time = dt.datetime.today()
        return None

    def set_prev_time(self):
        with open('ref/TIMES.csv', newline='') as file:
            reader = csv.reader(file)
            for row in reader:
                if len(row) == 2 and row[0] == str(self.ref):
                    try:
                        self.previous_time = dt.datetime.strptime(row[1], '%c')
                        return None
                    except ValueError:
                        self.previous_time = dt.datetime.today()
            self.previous_time = dt.datetime.today()
            return None


class OpDirectives:
    def __init__(self, conn_ref, target_type, target_path, operation, pattern, *args):
        self.conn_ref = conn_ref
        self.target_type = target_type
        self.target_path = target_path
        self.operation = operation
        if pattern:
            self.pattern = re.compile(pattern)
        else:
            self.pattern = None
        self.args = [*args]

    def validate(self):
        if ((self.target_type == 'dir'
                and ((self.operation == 'rename_files'
                        and len(self.args) == 1)
                    or (self.operation in ('copy_to', 'move_to', 'copy_from', 'move_from')
                        and len(self.args) == 2)))
            or (self.target_type == 'file'
                and (self.operation == 'rename_files'
                        and len(self.args) == 1)
                    or (self.operation == 'ren_copy'
                        and len(self.args) == 2))):
            return True
        else:
            return False


def dummy(path):
    pass


def format_args(args, dtime):
    try:
        for i, arg in enumerate(args):
            fvals = list(set(re.findall(r'(\{(.+?)\})', arg)))
            for j, pair in enumerate(fvals):
                args[i] = arg.replace(pair[0], dtime.strftime(pair[1]))
    except ValueError:
        print('INVALID DATETIME FORMAT STRING PROVIDED; CHECK AND REPAIR STRINGS IN OPERATION ARGUMENTS.')
    finally:
        return args


def log(line):
    try:
        with open('fsa.log', 'a') as log:
            line += '\n'
            log.write(line)
    except IOError:
        print('LOG FILE SHOULD NOT BE IN USE WHILE AGENT IS RUNNING. OPERATION HAS NOT BEEN LOGGED. TERMINATE AGENT BEFORE VIEWING.')


### Command functions
# Command selection
def choose_func(conn, conndir, opdir):
    funcname = (conndir.protocol + '_'
                + opdir.target_type + '_'
                + opdir.operation)
    if funcname == 'local_file_ren_copy':
        local_file_ren_copy(conndir, opdir)
    if funcname == 'local_file_rename_files':
        local_file_rename_files(conndir, opdir)
    if funcname == 'sftp_dir_rename_files':
        sftp_dir_rename_files(conn, opdir)
    elif funcname == 'sftp_dir_copy_to':
        sftp_dir_copy_to(conn, conndir, opdir)
    elif funcname == 'sftp_dir_move_to':
        sftp_dir_move_to(conn, conndir, opdir)
    elif funcname == 'sftp_dir_copy_from':
        sftp_dir_copy_from(conn, conndir, opdir)
    elif funcname == 'sftp_dir_move_from':
        sftp_dir_move_from(conn, conndir, opdir)
    return None


# Local commands
def local_file_ren_copy(conndir, opdir):
    local_file = None
    with os.scandir(opdir.target_path) as local:
        for file in local:
            if opdir.pattern and not re.match(opdir.pattern, file.name):
                continue
            else:
                fdt = dt.datetime.fromtimestamp(file.stat().st_ctime)
                if (fdt > conndir.previous_time and fdt <= conndir.access_time):
                    if opdir.args[1].lower() == 'yes':
                        if (not local_file
                                or fdt > dt.datetime.fromtimestamp(local_file.stat().st_ctime)):
                            local_file = file
                    else:
                        local_file = file
    if local_file:
        shutil.copy(local_file, opdir.args[0])
        log("Local file '{}' copied to '{}' locally".format(local_file.path, opdir.args[0]))
    return None


def local_file_rename_files(conndir, opdir):
    with os.scandir(opdir.target_path) as local:
        for file in local:
            currdir, currname = os.path.split(file.path)
            if opdir.pattern and not re.match(opdir.pattern, currname):
                continue
            newpath = os.path.join(opdir.args[0], currname)
            if os.path.exists(newpath):
                os.remove(newpath)
            shutil.copy(file.path, newpath)
            os.remove(file.path)
            log("Local file '{}' renamed to '{}'".format(file.path, newpath))
    return None


# SFTP commands
def sftp_dir_rename_files(pysftp_conn, opdir):
    paths = []
    pysftp_conn.walktree(opdir.target_path,
                         fcallback=paths.append,
                         dcallback=dummy,
                         ucallback=dummy,
                         recurse=False)
    for path in paths:
        currdir, currname = path.rsplit('/', 1)
        if opdir.pattern and not re.match(opdir.pattern, currname):
            continue
        newpath = '/'.join([opdir.args[0], currname])
        conn.rename(path, newpath)
        log("File '{}' on host renamed to '{}'".format(path, newpath))
    return None


def sftp_dir_copy_to(pysftp_conn, conndir, opdir):
    files = []
    with os.scandir(opdir.args[0]) as local:
        for file in local:
            if opdir.pattern and not re.match(opdir.pattern, file.name):
                continue
            if opdir.args[1].lower() == 'yes':
                fdt = dt.datetime.fromtimestamp(file.stat().st_ctime)
                if fdt > conndir.previous_time and fdt <= conndir.access_time:
                    files.append(file)
            else:
                files.append(file)
    for file in files:
        newpath = '/'.join([opdir.target_path, file.name])
        if pysftp_conn.exists(newpath):
            pysftp_conn.remove(newpath)
            log("File {} already existing on host was deleted".format(newpath))
        pysftp_conn.put(file.path, newpath, preserve_mtime=True)
        log("Local file '{}' copied to '{}' on host".format(file.path, newpath))
    return files


def sftp_dir_move_to(pysftp_conn, conndir, opdir):
    files = sftp_dir_copy_to(pysftp_conn, conndir, opdir)
    for file in files:
        os.remove(file.path)
        log("Remaining local file '{}' deleted".format(file.path))
    return None


def sftp_dir_copy_from(pysftp_conn, conndir, opdir):
    paths = []
    matched_paths = []
    pysftp_conn.walktree(opdir.target_path,
                         fcallback=paths.append,
                         dcallback=dummy,
                         ucallback=dummy,
                         recurse=False)
    if opdir.pattern:
        for path in paths:
            currdir, currname = path.rsplit('/', 1)
            if re.match(opdir.pattern, currname):
                matched_paths.append(path)
    else:
        matched_paths = paths
    if opdir.args[1].lower() == 'yes':
        paths = matched_paths
        matched_paths = []
        for path in paths:
            fdt = dt.datetime.fromtimestamp(pysftp_conn.stat(path).st_mtime)
            if fdt > conndir.previous_time and fdt <= conndir.access_time:
                matched_paths.append(path)
    for path in matched_paths:
        currdir, currname = path.rsplit('/', 1)
        if not os.path.exists(opdir.args[0]):
            os.makedirs(opdir.args[0])
        newpath = os.sep.join([opdir.args[0], currname])
        conn.get(path, newpath, preserve_mtime=True)
        log("File '{}' on host copied to '{}' locally".format(path, newpath))
    return matched_paths


def sftp_dir_move_from(pysftp_conn, conndir, opdir):
    paths = sftp_dir_copy_from(pysftp_conn, conndir, opdir)
    for path in paths:
        pysftp_conn.remove(path)
        log("Remaining file '{}' on host deleted".format(path))
    return None


# Main try clause for infinite loop
# Should be terminated with keyboard interrupt
try:
    log('Agent booted from disk at {}'.format(str(dt.datetime.now())))
    while True:
        _conndir = []
        _join = []
        _opdir = []
        start = dt.datetime.now()
        next_start = start + dt.timedelta(minutes=30)

        log('Cycle started at {}'.format(str(start)))
        print('\nScanning initiated! Timestamp: {}'.format(str(start)))
        try:
            with open('./ref/CONNS.csv', newline='') as connfile:
                reader = csv.reader(connfile)
                print('Examining connections...')
                for index, row in enumerate(reader):
                    if len(row) != 5:
                        print('Incorrect number of arguments for row {}! Discarded!'.format(index + 1))
                    else:
                        row[0] = row[0].lower()
                        row[1] = row[1].lower()
                        if row[0] not in ('local', 'sftp'):
                            print('Invalid protocol for row {}! Discarded!'.format(index + 1))
                        elif not row[4].isdigit():
                            print('Invalid port number for row {}! Discarded!'.format(index + 1))
                        else:
                            row[4] = int(row[4])
                            _join.append(index + 1)
                            _conndir.append(ConnDirectives(index + 1, *row))
            with open('./ref/OPS.csv', newline='') as opfile:
                reader = csv.reader(opfile)
                print('Examining operations...')
                for index, row in enumerate(reader):
                    if len(row) < 5:
                        print('Insufficient number of arguments for row {}! Discarded!'.format(index + 1))
                    elif not row[0].isdigit():
                        print('Invalid connection reference for row {}! Discarded!'.format(index + 1))
                    elif row[1].lower() not in ('dir', 'file'):
                        print('Invalid target type for row {}! Discarded!'.format(index + 1))
                    else:
                        row[0] = int(row[0])
                        row[1] = row[1].lower()
                        row[3] = row[3].lower()
                        if row[0] not in _join:
                            print('Cannot find referenced connection for row {}! Discarded!'.format(index + 1))
                        else:
                            opdir = OpDirectives(*row)
                            if not opdir.validate():
                                print('Specified operation is invalid for row {}! Discarded!'.format(index + 1))
                            else:
                                _opdir.append(opdir)
        except IOError:
            log("IOError encountered attempting to open reference files `./ref/CONNS.csv` and `./ref/OPS.csv`!")
            print("Error encountered attempting to open reference files; check to ensure they are located at `./ref`.")

        if not _opdir:
            print('No valid operations found! Operation aborted!')
        else:
            for conndir in _conndir:
                for opdir in _opdir:
                    if conndir.ref == opdir.conn_ref:
                        conndir.add_op(opdir)
            _opdir = []
            conns_with_ops = []
            for conndir in _conndir:
                if conndir.ops:
                    conns_with_ops.append(conndir)
            _conndir = conns_with_ops

            for conndir in _conndir:
                try:
                    if conndir.protocol == 'sftp':
                        with pysftp.Connection(
                                host=conndir.host,
                                username=conndir.username,
                                password=conndir.password,
                                port=conndir.port) as conn:
                            conndir.set_access_time()
                            log("Connection with host '{}' established at {}".format(conndir.host, conndir.access_time))
                            for opdir in conndir.ops:
                                opdir.args = format_args(opdir.args, start)
                                choose_func(conn, conndir, opdir)
                            log("Connection with host '{}' terminated at {}".format(conndir.host, str(dt.datetime.now())))
                    elif conndir.protocol == 'local':
                            conndir.set_access_time()
                            log("Local host operations begun at at {}".format(conndir.access_time))
                            for opdir in conndir.ops:
                                opdir.args = format_args(opdir.args, start)
                                choose_func(conn, conndir, opdir)
                            log("Local host operations completed at {}".format(str(dt.datetime.now())))
                    conndir.cycle_times()
                except pysftp.SSHException:
                    # Note that this doesn't handle subsequent AttributeError
                    # thrown by context manager. Needs future fix.
                    print('SSH exception for host {} raised! Check for incorrect connection directives or missing key in `~./.ssh/known_hosts`.'.format(conndir.host))
                    continue
                except pysftp.ConnectionException as ce:
                    log("ConnectionException encountered during connection: " + str(ce))
                    print("ConnectionException encountered during connection; see log for details.")
                except IOError as ioe:
                    log("IOError encountered during connection: " + str(ioe))
                    print("IOError encountered during connection; see log for details.")
                except EOFError as eofe:
                    log("EOFError encountered during connection: " + str(eofe))
                    print("EOFError encountered during connection; see log for details.")

        sleep_interval = (next_start - dt.datetime.now()).seconds
        if sleep_interval > 0:
            print('Operations completed! Next scan will initiate at {}.'.format(str(next_start)))
            log('Cycle ended and sleep begun at {}'.format(str(dt.datetime.now())))
            sleep(sleep_interval)
        else:
            print('Operations have taken longer than 30 minutes to complete! Review directives or source.')
        if os.name == 'nt':
            os.system('cls')
        else:
            os.system('clear')
except KeyboardInterrupt:
    log('Agent terminated via keyboard interrupt at {}'.format(str(dt.datetime.now())))
    print('Agent activity interrupted! Resume when ready.')
