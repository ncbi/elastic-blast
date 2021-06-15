#                           PUBLIC DOMAIN NOTICE
#              National Center for Biotechnology Information
#
# This software is a "United States Government Work" under the
# terms of the United States Copyright Act.  It was written as part of
# the authors' official duties as United States Government employees and
# thus cannot be copyrighted.  This software is freely available
# to the public for use.  The National Library of Medicine and the U.S.
# Government have not placed any restriction on its use or reproduction.
#
# Although all reasonable efforts have been taken to ensure the accuracy
# and reliability of the software and data, the NLM and the U.S.
# Government do not and cannot warrant the performance or results that
# may be obtained by using this software or data.  The NLM and the U.S.
# Government disclaim all warranties, express or implied, including
# warranties of performance, merchantability or fitness for any particular
# purpose.
#
# Please cite NCBI in any work or product based on this material.

"""
Module filehelper

Facilitates reads and writes of text files to/from remote filesystems and read
compressed/archived text files.

Implemented variants:
  read from local, GS, http(s)/ftp URL
  write to local and GS
  read gzip, tar/tgz/tar.gz/tar.bz2 (all files in archive merged into one)

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""

import subprocess, os, io, gzip, tarfile, re, tempfile, shutil
import logging
import urllib.request
from string import digits
from random import sample
from typing import Dict, IO, Tuple, Iterable, Generator, TextIO

import boto3  # type: ignore
from botocore.exceptions import ClientError  # type: ignore
from .util import safe_exec, SafeExecError


def upload_file_to_gcs(filename: str, gcs_location: str, dry_run: bool = False) -> None:
    """ Function to copy the filename provided to GCS """
    cmd = f'gsutil -qm cp {filename} {gcs_location}'
    if dry_run:
        logging.info(cmd)
    else:
        safe_exec(cmd)

# Write GS files to temp directory, then gsutil -mq cp temp_dir/* gs://chunks_path
# mapping from gs bucket place to temp dir created by open_for_write
bucket_temp_dirs: Dict[str, str] = {}

def copy_to_bucket(dry_run: bool = False):
    """ Copy files open in temp local dirs to corresponding places in gs.
        Works in concert with open_for_write.
        Parameters:
            dry_run - simulate action, don't do anything, default False
    """
    global bucket_temp_dirs # FIXME: remove global variables from library code
    s3 = boto3.resource('s3')
    # NB: Here we need to provide stable list of keys in
    # dictionary while deleting processed keys, hence list(keys())
    for bucket_key in list(bucket_temp_dirs.keys()):
        tempdir = bucket_temp_dirs[bucket_key]
        # gsutil -mq cp tempdir/* bucket_key/
        if bucket_key.startswith('gs:'):
            bucket_dir = bucket_key + ('/' if bucket_key[-1] != '/' else '')
            cmd = ['gsutil', '-mq', 'cp', '-r', "%s/*" % tempdir, bucket_dir]
            if dry_run:
                logging.info(cmd)
            else:
                safe_exec(cmd)
        elif bucket_key.startswith('s3:'):
            if dry_run:
                logging.info(f'Copy to bucket prefix {bucket_key}')
            else:
                bucket_name, prefix = parse_bucket_name_key(bucket_key)
                bucket = s3.Bucket(bucket_name)
                num_files = len(os.listdir(path=tempdir))
                for i, fn in enumerate(os.listdir(path=tempdir)):
                    if prefix:
                        full_name = prefix+'/'+fn
                    else:
                        full_name = fn
                    perc_done = i / num_files * 100.
                    logging.debug(f'Uploading {os.path.join(tempdir, fn)} to s3://{bucket_name}/{full_name} file # {i} of {num_files} {perc_done:.2f}% done')
                    bucket.upload_file(os.path.join(tempdir, fn), full_name)
        else:
            raise ValueError(f'Incorrect bucket prefix {bucket_key}')
        logging.debug(f'Removing temp directory {tempdir}')
        shutil.rmtree(tempdir)
        bucket_temp_dirs.pop(bucket_key)


def cleanup_temp_bucket_dirs(dry_run: bool = False):
    """ Cleanup temp dirs created for bucket open_for_write.
        Safety function in case we didn't call copy_to_bucket
        Parameters:
            dry_run - simulate action, don't do anything, default False
    """
    global bucket_temp_dirs # FIXME: remove global variables from library code
    if dry_run:
        return
    # NB: Here we need to provide stable list of keys in
    # dictionary while deleting processed keys, hence list(keys())
    for bucket_dir in list(bucket_temp_dirs.keys()):
        tempdir = bucket_temp_dirs[bucket_dir]
        logging.debug(f'Cleaning up tempdir {tempdir}')
        shutil.rmtree(tempdir, ignore_errors=True)
        bucket_temp_dirs.pop(bucket_dir)


def random_filename():
    return f'.random-probe-{"".join(sample(digits, 10))}'

def check_dir_for_write(dirname: str, dry_run=False) -> None:
    """ Check that path on local or GS filesystem can be written to.
        raises PermissionError if write is not possible
    """
    # GS
    if dirname.startswith('gs:'):
        test_file_name = os.path.join(dirname, random_filename())
        if dry_run:
            logging.info(f'echo test|gsutil cp - {test_file_name}')
            return
        try:
            proc = subprocess.Popen(['gsutil', 'cp', '-', test_file_name],
                stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            _, err = proc.communicate(b'test')
            if proc.returncode:
                raise PermissionError(proc.returncode, err.decode())
            safe_exec(f'gsutil -q rm {test_file_name}')
        except SafeExecError as e:
            raise PermissionError(e.returncode, e.message)
        return
    # AWS
    elif dirname.startswith('s3:'):
        # TODO: implement the write test, see EB-491
        return
    # Local file system
    test_file_name = os.path.join(dirname, random_filename())
    if dry_run:
        logging.info(f'Trying to write file {test_file_name}')
    try:
        with open(test_file_name, 'w'): pass
        os.remove(test_file_name)
    except:
        raise PermissionError()


def open_for_write(fname):
    """ Open file on either local (no prefix), GS (gs:// prefix), or AWS S3 (s3://)
        filesystem for write in text mode. Postpones actual copy to buckets until
        copy_to_bucket is called.
    """
    global bucket_temp_dirs
    if fname.startswith('gs:') or fname.startswith('s3:'):
        # for the same gs path open files in temp dir and put it into
        # bucket_temp_dirs dictionary, copy through to bucket in copy_to_bucket later
        last_slash = fname.rfind('/')
        if last_slash == -1:
            raise "Incorrect bucket path %s" % fname
        bucket_dir = fname[:last_slash]
        filename = fname[last_slash+1:]
        if bucket_dir in bucket_temp_dirs:
            tempdir = bucket_temp_dirs[bucket_dir]
        else:
            tempdir = tempfile.mkdtemp()
            logging.debug(f'Create tempdir {tempdir} for bucket {bucket_dir}')
            bucket_temp_dirs[bucket_dir] = tempdir
        return open(os.path.join(tempdir, filename), 'wt')
    # file on a regular filesystem
    last_sep = fname.rfind('/')
    if last_sep > 0:
        path = fname[:last_sep]
        os.makedirs(path, exist_ok=True)
    return open(fname, 'wt')


def tar_reader(tar):
    """ Helper generator for reading all files in a tar file as single
    stream of lines.
    """
    for tarinfo in tar:
        if not tarinfo.isfile():
            continue
        f = tar.extractfile(tarinfo)
        # Add missing function for TextIOWrapper
        f.seekable = lambda : False
        f = io.TextIOWrapper(f)
        for line in f:
            yield line


class TarMerge(io.TextIOWrapper):
    """ Wrapper for tar_reader generator, implements
    - iterator for reading as if it is a file, and
    - context manager so it can release resources when
      used in 'with' construct
    """
    def __init__(self, tar):
        self.tar = tar
        self.reader = tar_reader(tar)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.reader)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.tar.close()
        return False

    def read(self):
        return ''.join(list(self))

    def readline(self):
        return next(self.reader)


# FIXME: this function returns object of three possible classes and there
# are typing problems, which may indicate incompatibility between classes.
# We need tests checking downstream logic for these different return types.
# (EB-340)
def unpack_stream(s:IO, gzipped:bool, tarred:bool) -> IO:
    """ Helper function which inserts uncompressing/unarchiving
    transformers as needed depending on detected file type
    """
    if tarred:
        tar = tarfile.open(fileobj=s, mode='r|*')
        return TarMerge(tar)
    # type checking in the line below is ignored because io.TextIOWrapper
    # conflicts with gzip.GzipFile, but duck-typing-wise everthing seems fine
    return io.TextIOWrapper(gzip.GzipFile(fileobj=s)) if gzipped else s   #type: ignore


def check_for_read(fname: str, dry_run=False) -> None:
    """ Check that path on local, GS, or URL-available filesystem can be read from.
    raises FileNotFoundErrror if there is no such file
    """
    if fname.startswith('gs:'):
        cmd = f'gsutil -q stat {fname}'
        if dry_run:
            logging.info(cmd)
            return
        try:
            safe_exec(cmd)
        except SafeExecError as e:
            raise FileNotFoundError(e.returncode, e.message)
        return
    if fname.startswith('s3:'):
        if dry_run:
            logging.info(f'Open S3 file {fname}')
            return
        s3 = boto3.resource('s3')
        bucket, key = parse_bucket_name_key(fname)
        try:
            obj = s3.Object(bucket, key)
            obj.load()
        except ClientError as exn:
            raise FileNotFoundError(1, str(exn))
        return
    if fname.startswith('http') or fname.startswith('ftp:'):
        if dry_run:
            logging.info(f'Open URL request for {fname}')
            return
        req = urllib.request.Request(fname, method='HEAD')
        try:
            urllib.request.urlopen(req)
        except:
            raise FileNotFoundError()
        return
    open(fname, 'r')


error_report_funcs = {}

def open_for_read(fname):
    """ Open path for read on local, GS, or URL-available filesystem defined by prefix.
    File can be gzipped, and archived with tar.
    """
    global error_report_funcs
    gzipped = fname[-3:] == ".gz"
    tarred = re.match(r'^.*\.(tar(|\.gz|\.bz2)|tgz)$', fname)
    binary = gzipped or tarred
    mode = 'rb' if binary else 'rt'
    if fname.startswith('gs:'):
        proc = subprocess.Popen(['gsutil', 'cat', fname],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=not binary)
        fileobj = unpack_stream(proc.stdout, gzipped, tarred)
        error_report_funcs[fileobj] = proc.stderr.read
        return fileobj
    if fname.startswith('s3'):
        s3 = boto3.client('s3')
        bucket, key = parse_bucket_name_key(fname)
        resp = s3.get_object(Bucket=bucket, Key=key)
        body = resp['Body']
        body.readable = lambda: True
        body.writable = lambda: False
        body.seekable = lambda: False
        body.closed = False
        body.flush = lambda: None
        if tarred or gzipped:
            fileobj = unpack_stream(body, gzipped, tarred)
        else:
            fileobj = io.TextIOWrapper(body)
        return fileobj
    if fname.startswith('http') or fname.startswith('ftp:'):
        response = urllib.request.urlopen(fname)
        return unpack_stream(response, gzipped, tarred)
    # regular file
    f = open(fname, mode)
    return unpack_stream(f, gzipped, tarred)


def open_for_read_iter(fnames: Iterable[str]) -> Generator[TextIO, None, None]:
    """Generator function that Iterates over paths/uris and open them for
    reading.

    Arguments:
        An iterable with paths to open

    Returns:
        Generator of files open for reading"""
    for fname in fnames:
        with open_for_read(fname) as f:
            yield f


def get_error(fileobj):
    global error_report_funcs
    func = error_report_funcs.get(fileobj)
    if func: return func()
    return ''


def parse_bucket_name_key(fname: str) -> Tuple[str, str]:
    """ Parse S3 or GS uri name into bucket and key.
    Parameters:
        fname - S3 or GS full name with possible s3:// or gs:// prefix,
                i.e. both names s3://test-bucket/file_name.ext and
                test-bucket/file_name.ext are valid
    Returns:
        tuple of bucket name and the rest of the name (key in AWS parlance), e.g.
        for example above ('test-bucket', 'file_name.ext')
    """
    bare_name = fname
    if fname.startswith('s3://') or fname.startswith('gs://'):
        bare_name = fname[5:]
    parts = bare_name.split('/')
    bucket = parts[0]
    key = '/'.join(parts[1:])
    return bucket, key
