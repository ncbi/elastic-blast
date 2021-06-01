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
Unit tests for tuner module

"""

import json
import os
from elb.tuner import get_blastdb_mem_requirements
from elb.filehelper import open_for_read
from elb.base import DBSource
from elb.constants import ELB_BLASTDB_MEMORY_MARGIN
from elb.util import UserReportError
import pytest


TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


@pytest.fixture
def mocked_db_metadata(mocker):
    """A fixture that always opens a fake database metadata file"""
    TEST_METADATA_FILE = f'{TEST_DATA_DIR}/nr-aws.json'
    with open(f'{TEST_DATA_DIR}/latest-dir') as f_latest_dir, open(TEST_METADATA_FILE) as f_db_metadata:

        def mocked_open_for_read(filename):
            """Mocked open_for_read funtion that always opens the same local
            database metadatafile and a fake latest-dir file"""
            if filename.endswith('latest-dir'):
                return f_latest_dir
            else:
                # check that metadata file name was constructed correctly
                if not filename.startswith('s3://') and \
                       not filename.startswith('gs://') and \
                       not filename.startswith('https://'):
                    raise RuntimeError('Incorrect URI for database metadata file')
                if not filename.endswith('.json'):
                    raise RuntimeError('No json extension for database metadata file')
                return f_db_metadata

        mocker.patch('elb.tuner.open_for_read', side_effect=mocked_open_for_read)
        yield TEST_METADATA_FILE


def test_get_blastdb_mem_requirements(mocked_db_metadata):
    """Test getting blast database memory requirements"""
    mem_req = get_blastdb_mem_requirements('nr', DBSource.AWS)
    with open(mocked_db_metadata) as f:
        db_metadata = json.load(f)
    exp_mem_req = int(db_metadata['bytes-to-cache']) / (1024 ** 3) * ELB_BLASTDB_MEMORY_MARGIN
    assert abs(mem_req - exp_mem_req) < 1


def test_get_blastdb_mem_requirements_user_db(mocked_db_metadata):
    """Test getting blast database memory requirements"""
    mem_req = get_blastdb_mem_requirements('s3://some-bucket/userdb', DBSource.AWS)
    with open(mocked_db_metadata) as f:
        db_metadata = json.load(f)
    exp_mem_req = int(db_metadata['bytes-to-cache']) / (1024 ** 3) * ELB_BLASTDB_MEMORY_MARGIN
    assert abs(mem_req - exp_mem_req) < 1


def test_get_blastdb_mem_requirements_missing_db():
    """Test get_blastdb_mem_requirements with a non-exstient database"""
    with pytest.raises(UserReportError):
        get_blastdb_mem_requirements('s3://some-bucket/non-existent-db', DBSource.AWS)

    with pytest.raises(UserReportError):
        get_blastdb_mem_requirements('this-db-does-not-exist', DBSource.GCP)
        
