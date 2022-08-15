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
from elastic_blast import filehelper
from tempfile import TemporaryDirectory
import pytest

TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
WRITEABLE_BUCKET = 'gs://blast-test'

GCP_PRJ = "ncbi-sandbox-blast"

def test_check_for_read_success():
    filehelper.check_for_read('gs://blast-db/latest-dir', gcp_prj=GCP_PRJ)
    #filehelper.check_for_read('s3://ncbi-blast-databases/latest-dir')
    filehelper.check_for_read(os.path.join(TEST_DATA_DIR, 'test.tar'))


def test_check_for_read_failure():
    with pytest.raises(FileNotFoundError):
        filehelper.check_for_read('gs://blast-db/non-existent-file', gcp_prj=GCP_PRJ)
    with pytest.raises(FileNotFoundError):
        filehelper.check_for_read(os.path.join(TEST_DATA_DIR, 'non-existent-file'))
    with pytest.raises(FileNotFoundError):
        filehelper.check_for_read('https://storage.googleapis.com/blast-db/invalid-file')


def test_check_for_write_success():
    filehelper.check_dir_for_write(WRITEABLE_BUCKET)
    with TemporaryDirectory() as d:
        filehelper.check_dir_for_write(d)


def test_check_for_write_failure():
    with pytest.raises(PermissionError):
        filehelper.check_dir_for_write('gs://arbitrary-non-existent-bucket-test')
    with pytest.raises(PermissionError):
        filehelper.check_dir_for_write('/home/')
