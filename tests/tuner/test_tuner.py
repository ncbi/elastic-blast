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
from elb.tuner import get_db_data, MolType, DbData, SeqData, get_mt_mode
from elb.tuner import MTMode, get_num_cpus, get_batch_length
from elb.filehelper import open_for_read
from elb.base import DBSource
from elb.constants import ELB_BLASTDB_MEMORY_MARGIN
from elb.util import UserReportError, get_query_batch_size
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


def test_get_db_data(mocked_db_metadata):
    """Test getting blast database memory requirements"""
    db = get_db_data('nr', DBSource.AWS)
    with open(mocked_db_metadata) as f:
        db_metadata = json.load(f)
    assert db.length == int(db_metadata['number-of-letters'])
    assert db.moltype == MolType(db_metadata['dbtype'].lower()[:4])


def test_get_db_data_user_db(mocked_db_metadata):
    """Test getting blast database memory requirements"""
    db = get_db_data('s3://some-bucket/userdb', DBSource.AWS)
    with open(mocked_db_metadata) as f:
        db_metadata = json.load(f)
    assert db.length == int(db_metadata['number-of-letters'])
    assert db.moltype == MolType(db_metadata['dbtype'].lower()[:4])


def test_get_db_data_missing_db():
    """Test get_blastdb_mem_requirements with a non-exstient database"""
    with pytest.raises(UserReportError):
        get_db_data('s3://some-bucket/non-existent-db', DBSource.AWS)

    with pytest.raises(UserReportError):
        get_db_data('this-db-does-not-exist', DBSource.GCP)
        
def test_get_mt_mode():
    """Test computing BLAST search MT mode"""
    db = DbData(length = 10000000, moltype = MolType.PROTEIN, bytes_to_cache_gb = 1)
    query = SeqData(length = 20000, moltype = MolType.PROTEIN)
    assert get_mt_mode(program = 'blastp', options = '', db = db, query = query) == MTMode.ONE

    db = DbData(length = 50000000000, moltype = MolType.PROTEIN, bytes_to_cache_gb = 1)
    query = SeqData(length = 20000, moltype = MolType.PROTEIN)
    assert get_mt_mode(program = 'blastp', options = '', db = db, query = query) == MTMode.ZERO

    db = DbData(length = 50000000000, moltype = MolType.PROTEIN, bytes_to_cache_gb = 1)
    query = SeqData(length = 20000, moltype = MolType.PROTEIN)
    assert get_mt_mode(program = 'blastp', options = '-taxidlist list', db = db, query = query) == MTMode.ONE

    db = DbData(length = 1000, moltype = MolType.NUCLEOTIDE, bytes_to_cache_gb = 1)
    query = SeqData(length = 5000000, moltype = MolType.PROTEIN)
    assert get_mt_mode(program = 'blastp', options = '', db = db, query = query) == MTMode.ONE

    db = DbData(length = 20000000000, moltype = MolType.NUCLEOTIDE, bytes_to_cache_gb = 1)
    query = SeqData(length = 5000000, moltype = MolType.PROTEIN)
    assert get_mt_mode(program = 'blastp', options = '', db = db, query = query) == MTMode.ZERO


def test_MTMode():
    """Test MTMode conversions"""
    assert MTMode(0) == MTMode.ZERO
    assert MTMode(1) == MTMode.ONE
    assert str(MTMode.ZERO) == ''
    assert str(MTMode.ONE) == '-mt_mode 1'


def test_get_num_cpus():
    """Test computing number of cpus for a BLAST search"""
    query = SeqData(length = 21000, moltype = MolType.PROTEIN)
    assert get_num_cpus(mt_mode = MTMode.ZERO, query = query) == 16
    assert get_num_cpus(mt_mode = MTMode.ONE, query = query) == 3


def test_get_batch_length():
    """Test computing batch length"""
    PROGRAM = 'blastp'
    NUM_CPUS = 16
    assert get_batch_length(program = 'blastp', mt_mode = MTMode.ZERO,
                            num_cpus = NUM_CPUS) == get_query_batch_size(PROGRAM)

    assert get_batch_length(program = 'blastp', mt_mode = MTMode.ONE,
                            num_cpus = NUM_CPUS) == get_query_batch_size(PROGRAM) * NUM_CPUS
