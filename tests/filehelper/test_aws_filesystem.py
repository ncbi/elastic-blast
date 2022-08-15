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
Unit tests for filehelper module

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""

import pytest
import os
import subprocess
import boto3
import botocore.errorfactory
from elastic_blast import filehelper
from elastic_blast.object_storage_utils import write_to_s3, delete_from_s3
from tempfile import mktemp, NamedTemporaryFile
from contextlib import contextmanager

TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
READABLE_S3_FILE = 's3://elasticblast-test/queries/MANE.GRCh38.v0.8.select_refseq_rna.fna'
S3_FILE_FIRST_LINE = '>NM_000014.6 Homo sapiens alpha-2-macroglobulin (A2M), transcript variant 1, mRNA\n'
READABLE_S3_TAR_FILE = 's3://elasticblast-test/testdata/test.tar'
READABLE_S3_TAR_GZ_FILE = 's3://elasticblast-test/testdata/test.tar.gz'
READABLE_S3_GZ_FILE = 's3://elasticblast-test/testdata/hepa_batch_016.gz'
WRITEABLE_BUCKET = 's3://elasticblast-test'
PREFIX = 'test'
WRONG_BUCKET = 's3://some-arbitrary-bucket-for-test'


@contextmanager
def bucket_object_name_to_delete(obj_name: str):
    """ Context manager to automatically delete the S3 object named as its first argument
    This is to make it easy to write python with statements to delete testing objects
    """
    try:
        yield obj_name
    finally:
        delete_from_s3(obj_name)


@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='AWS credentials not set in TC')
def test_write_to_s3():
    text_to_write = 'hello world from ElasticBLAST'
    text_from_bucket = ''
    with NamedTemporaryFile() as tmpname:
        object_name = os.path.join(WRITEABLE_BUCKET, PREFIX, os.path.basename(tmpname.name))
        with bucket_object_name_to_delete(object_name):
            print(object_name)
            write_to_s3(object_name, text_to_write)
            with filehelper.open_for_read(object_name) as s3_object:
                text_from_bucket = s3_object.read()
            assert text_to_write == text_from_bucket


@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='AWS credentials not set in TC')
def test_check_aws_for_read_success():
    fn = READABLE_S3_FILE
    with filehelper.open_for_read(fn) as f:
        line = f.readline()
        for n, line1 in enumerate(f):
            if n > 20:
                break
    assert(line==S3_FILE_FIRST_LINE)
    fn = READABLE_S3_TAR_FILE
    with filehelper.open_for_read(fn) as f:
        line = f.readline()
        for line in f:
            pass
    fn = READABLE_S3_GZ_FILE
    with filehelper.open_for_read(fn) as f:
        line = f.readline()
        for line in f:
            pass
    fn = READABLE_S3_TAR_GZ_FILE
    with filehelper.open_for_read(fn) as f:
        line = f.readline()
        for line in f:
            pass


@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='AWS credentials not set in TC')
def test_check_aws_for_write_success():
    for prefix in ['', PREFIX]:
        tn = os.path.join(WRITEABLE_BUCKET, prefix, mktemp(prefix='', dir=''))
        with bucket_object_name_to_delete(tn):
            with filehelper.open_for_write(tn) as f:
                f.write('Test')
            filehelper.copy_to_bucket()
            local_fn = mktemp()
            subprocess.run(['aws', 's3', 'cp', tn, local_fn], check=True)
            with open(local_fn) as f:
                test_text = f.read()
            assert test_text == 'Test'
    

@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='AWS credentials not set in TC')
def test_check_aws_for_write_failure():
    tn = os.path.join(WRONG_BUCKET, mktemp(prefix='', dir=''))
    try:
        with filehelper.open_for_write(tn) as f:
            f.write('Test')
    except:
        assert(True)
    else:
        assert(False)
