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
import math
from unittest.mock import MagicMock, patch
from elastic_blast.tuner import MolType, DbData, SeqData, get_mt_mode
from elastic_blast.tuner import MTMode, get_num_cpus, get_batch_length
from elastic_blast.tuner import aws_get_mem_limit, gcp_get_mem_limit
from elastic_blast.tuner import aws_get_machine_type, gcp_get_machine_type
from elastic_blast.tuner import get_mem_limit, get_machine_type
from elastic_blast.tuner import MAX_NUM_THREADS_AWS, MAX_NUM_THREADS_GCP
from elastic_blast.filehelper import open_for_read
from elastic_blast.base import DBSource
from elastic_blast.constants import ELB_BLASTDB_MEMORY_MARGIN, SYSTEM_MEMORY_RESERVE
from elastic_blast.constants import CSP, INPUT_ERROR, MEMORY_FOR_BLAST_HITS
from elastic_blast.constants import ELB_DFLT_AWS_NUM_CPUS, ELB_DFLT_GCP_NUM_CPUS
from elastic_blast.util import UserReportError, get_query_batch_size
from elastic_blast.base import MemoryStr, InstanceProperties
from elastic_blast.db_metadata import DbMetadata
from elastic_blast.gcp_traits import get_machine_properties as gcp_get_machine_properties
from elastic_blast.aws_traits import get_machine_properties as aws_get_machine_properties
import pytest


TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


def test_db_data_from_db_metadata():
    """Test creation of an DbData object"""
    db_metadata = DbMetadata(version = '1',
                             dbname = 'testdb',
                             dbtype = 'Nucleotide',
                             description = 'A test database',
                             number_of_letters = 25,
                             number_of_sequences = 5,
                             files = [],
                             last_updated = 'a date',
                             bytes_total = 125,
                             bytes_to_cache = 100,
                             number_of_volumes = 1)
    db_data = DbData.from_metadata(db_metadata)


def test_get_mt_mode():
    """Test computing BLAST search MT mode"""
    db_metadata = DbMetadata(version = '1',
                             dbname = 'testdb',
                             dbtype = 'Protein',
                             description = 'A test database',
                             number_of_letters = 10000000,
                             number_of_sequences = 5,
                             files = [],
                             last_updated = 'a date',
                             bytes_total = 125,
                             bytes_to_cache = 100,
                             number_of_volumes = 1)

    query = SeqData(length = 20000, moltype = MolType.PROTEIN)
    assert get_mt_mode(program = 'blastp', options = '', db_metadata = db_metadata, query = query) == MTMode.ONE


    db_metadata.dbtype = 'Protein'
    db_metadata.number_of_letters = 50000000000
    query = SeqData(length = 20000, moltype = MolType.PROTEIN)
    assert get_mt_mode(program = 'blastp', options = '', db_metadata = db_metadata, query = query) == MTMode.ZERO

    db_metadata.dbtype = 'Protein'
    db_metadata.number_of_letters = 50000000000
    query = SeqData(length = 20000, moltype = MolType.PROTEIN)
    assert get_mt_mode(program = 'blastp', options = '-taxidlist list', db_metadata = db_metadata, query = query) == MTMode.ONE

    db_metadata.dbtype = 'Nucleotide'
    db_metadata.number_of_letters = 1000
    query = SeqData(length = 5000000, moltype = MolType.PROTEIN)
    assert get_mt_mode(program = 'blastp', options = '', db_metadata = db_metadata, query = query) == MTMode.ONE

    db_metadata.dbtype = 'Nucleotide'
    db_metadata.number_of_letters = 20000000000
    query = SeqData(length = 5000000, moltype = MolType.PROTEIN)
    assert get_mt_mode(program = 'blastp', options = '', db_metadata = db_metadata, query = query) == MTMode.ZERO

    db_metadata.dbtype = 'Nucleotide'
    db_metadata.number_of_letters = 500
    query = SeqData(length = 5000000, moltype = MolType.PROTEIN)
    assert get_mt_mode(program = 'tblastn', options = '', db_metadata = db_metadata, query = query) == MTMode.ZERO

    db_metadata.dbtype = 'Nucleotide'
    db_metadata.number_of_letters = 500
    query = SeqData(length = 5000000, moltype = MolType.PROTEIN)
    assert get_mt_mode(program = 'tblastx', options = '', db_metadata = db_metadata, query = query) == MTMode.ZERO


def test_MTMode():
    """Test MTMode conversions"""
    assert MTMode(0) == MTMode.ZERO
    assert MTMode(1) == MTMode.ONE
    assert str(MTMode.ZERO) == ''
    assert str(MTMode.ONE) == '-mt_mode 1'


def test_get_num_cpus():
    """Test computing number of cpus for a BLAST search"""
    query = SeqData(length = 85000, moltype = MolType.PROTEIN)
    assert get_num_cpus(cloud_provider = CSP.AWS, program = 'blastp', mt_mode = MTMode.ZERO, query = query) == MAX_NUM_THREADS_AWS
    assert get_num_cpus(cloud_provider = CSP.GCP, program = 'blastp', mt_mode = MTMode.ZERO, query = query) == MAX_NUM_THREADS_GCP
    assert get_num_cpus(cloud_provider = CSP.AWS, program = 'blastx', mt_mode = MTMode.ONE, query = query) == 9
    query = SeqData(length = 50000000, moltype = MolType.NUCLEOTIDE)
    assert get_num_cpus(cloud_provider = CSP.AWS, program = 'tblastn', mt_mode = MTMode.ONE, query = query) == MAX_NUM_THREADS_AWS
    assert get_num_cpus(cloud_provider = CSP.GCP, program = 'tblastn', mt_mode = MTMode.ONE, query = query) == MAX_NUM_THREADS_GCP


def test_get_batch_length():
    """Test computing batch length"""
    PROGRAM = 'blastx'
    NUM_CPUS = 16
    assert get_batch_length(CSP.AWS, program = PROGRAM, mt_mode = MTMode.ZERO,
                            num_cpus = NUM_CPUS) == get_query_batch_size(PROGRAM)

    PROGRAM = 'blastp'
    assert get_batch_length(CSP.AWS, program = PROGRAM, mt_mode = MTMode.ONE,
                            num_cpus = NUM_CPUS) == get_query_batch_size(PROGRAM) * NUM_CPUS * 2

    PROGRAM = 'rpsblast'
    NUM_CPUS = 16
    assert get_batch_length(CSP.AWS, program = PROGRAM, mt_mode = MTMode.ONE,
                            num_cpus = NUM_CPUS) == get_query_batch_size(PROGRAM) * NUM_CPUS * 2

    PROGRAM = 'rpsblast'
    NUM_CPUS = 100
    assert get_batch_length(CSP.GCP, program = PROGRAM, mt_mode = MTMode.ONE,
                            num_cpus = NUM_CPUS) == get_query_batch_size(PROGRAM) * MAX_NUM_THREADS_GCP * 2


@patch(target='elastic_blast.tuner.aws_get_machine_properties', new=MagicMock(return_value=InstanceProperties(32, 128)))
def test_aws_get_mem_limit():
    """Test getting search job memory limit for AWS"""
    NUM_CPUS=2
    db = DbData(length=20000, moltype=MolType.PROTEIN, bytes_to_cache_gb=60)

    # in the simplest invocation memory is divided equally between all jobs
    # running on an instance type
    assert aws_get_mem_limit(num_cpus=NUM_CPUS, machine_type='some-instance-type') == 7.8

    # when db_factor > 0.0 db.bytes_to_cache * db_factor is returned
    DB_FACTOR = 1.2
    assert abs(aws_get_mem_limit(num_cpus=NUM_CPUS, machine_type='some-instance-type', db=db, db_factor=DB_FACTOR) - db.bytes_to_cache_gb * DB_FACTOR) < 1

    # db must be provided, if db_factor > 0.0
    with pytest.raises(ValueError):
        aws_get_mem_limit(num_cpus=NUM_CPUS, machine_type='some-instance-type', db_factor=DB_FACTOR)

    # when machine_type == 'optimal' 60G is returned if db.bytes_to_cache >= 60G,
    # otherwise db.bytes_to_cache_gb + MEMORY_FOR_BLAST_HITS
    db.bytes_to_cache_gb = 60
    assert aws_get_mem_limit(num_cpus=NUM_CPUS, machine_type='optimal', db=db, db_factor=0.0) == 60

    db.bytes_to_cache_gb = 20
    assert aws_get_mem_limit(num_cpus=NUM_CPUS, machine_type='optimal', db=db, db_factor=0.0) == db.bytes_to_cache_gb + MEMORY_FOR_BLAST_HITS

    # db must be provided when machine_type == 'optimal'
    with pytest.raises(ValueError):
        aws_get_mem_limit(num_cpus=NUM_CPUS, machine_type='optimal')


def test_gcp_get_mem_limit():
    """Test getting search job memory limit for GCP"""
    MACHINE_TYPE = 'n1-standard-32'
    props = gcp_get_machine_properties(MACHINE_TYPE)
    assert gcp_get_mem_limit(MACHINE_TYPE) == props.memory - SYSTEM_MEMORY_RESERVE


@patch(target='elastic_blast.tuner.aws_get_machine_properties', new=MagicMock(return_value=InstanceProperties(32, 128)))
@patch(target=__name__ + '.aws_get_machine_properties', new=MagicMock(return_value=InstanceProperties(32, 128)))
def test_get_mem_limit():
    """Test get_mem_limit wrapper"""
    NUM_CPUS = 4

    # for GCP
    machine_type = 'n1-standard-32'
    props = gcp_get_machine_properties(machine_type)
    assert get_mem_limit(CSP.GCP, machine_type, NUM_CPUS).asGB() == props.memory - SYSTEM_MEMORY_RESERVE

    #for AWS
    machine_type = 'm5.x8large'
    props = aws_get_machine_properties(machine_type)
    assert abs(get_mem_limit(CSP.AWS, machine_type, NUM_CPUS).asGB() - \
        (props.memory - SYSTEM_MEMORY_RESERVE) / math.floor(props.ncpus / NUM_CPUS)) < 0.1


def test_get_mem_limit_instance_too_small():
    """Test that getting memory limit for an instance that has too little RAM
    for elastic-blast results in an exception"""
    # for GCP
    with pytest.raises(UserReportError) as err:
        get_mem_limit(CSP.GCP, 'n1-highcpu-2', 1)
    assert err.value.returncode == INPUT_ERROR
    assert 'does not have enough memory' in err.value.message

    # for AWS
    with patch(target='elastic_blast.tuner.aws_get_machine_properties', new=MagicMock(return_value=InstanceProperties(1, 0.5))):
        with pytest.raises(UserReportError) as err:
            get_mem_limit(CSP.AWS, 'some-instance-with-small-memory', 1)
    assert err.value.returncode == INPUT_ERROR
    assert 'does not have enough memory' in err.value.message


class MockedEc2Client:
    """Mocked boto3 ec2 client"""
    def describe_instance_type_offerings(LocationType, Filters):
        """Mocked function to to get AWS instance type offerings"""
        return {'InstanceTypeOfferings': [{'InstanceType': 'm5.8xlarge'},
                                          {'InstanceType': 'm5.4xlarge'},
                                          {'InstanceType': 'r5.4xlarge'}]}

    def describe_instance_types(InstanceTypes, Filters):
        """Mocked function to get description of AWS instance types"""
        return {'InstanceTypes': [{'InstanceType': 'm5.8xlarge',
                                   'MemoryInfo': {'SizeInMiB': 131072},
                                   'VCpuInfo': {'DefaultVCpus': 32}
                                  },
                                  {'InstanceType': 'm5.4xlarge',
                                   'MemoryInfo': {'SizeInMiB': 65536},
                                   'VCpuInfo': {'DefaultVCpus': 16}
                                  },
                                  {'InstanceType': 'r5.4xlarge',
                                   'MemoryInfo': {'SizeInMiB': 131072},
                                   'VCpuInfo': {'DefaultVCpus': 16}
                                  }]}


@patch(target='boto3.client', new=MagicMock(return_value=MockedEc2Client))
def test_aws_get_machine_type():
    """Test selecting machine type for AWS"""
    MIN_CPUS = 8
    result = aws_get_machine_type(memory=MemoryStr('70G'), num_cpus=MIN_CPUS, region='test-region')
    # m5.8xlarge should be selected here because it has the least memory out of
    # instance types that satisfy the memory requirement
    assert result == 'm5.8xlarge'

    with pytest.raises(UserReportError):
        aws_get_machine_type(memory=MemoryStr('1026G'), num_cpus=MIN_CPUS, region='test-region')


def test_gcp_get_machine_type():
    """Test selecting machine type for GCP"""
    NUM_CPUS = 14
    result = gcp_get_machine_type(memory=MemoryStr('120G'), num_cpus=NUM_CPUS)
    assert result == 'n1-standard-32'

    NUM_CPUS = 14
    result = gcp_get_machine_type(memory=MemoryStr('42G'), num_cpus=NUM_CPUS)
    assert result == 'e2-standard-16'

    NUM_CPUS = 256
    with pytest.raises(UserReportError):
        gcp_get_machine_type(memory=MemoryStr('42G'), num_cpus=NUM_CPUS)

    NUM_CPUS = 32
    with pytest.raises(UserReportError):
        gcp_get_machine_type(memory=MemoryStr('1026G'), num_cpus=NUM_CPUS)


@patch(target='boto3.client', new=MagicMock(return_value=MockedEc2Client))
def test_get_machine_type():
    """Test selecting machine type"""
    db_metadata = DbMetadata(version = '1.1',
                             dbname = 'testdb',
                             dbtype = 'PROTEIN',
                             description = 'Test database',
                             number_of_letters = 123,
                             number_of_sequences = 123,
                             files = [],
                             last_updated = 'A date',
                             bytes_total = 789,
                             bytes_to_cache = 789,
                             number_of_volumes = 1)

    db_metadata.bytes_to_cache = 26 * (1024 ** 3)

    # AWS
    result = get_machine_type(cloud_provider = CSP.AWS,
                              db = db_metadata,
                              num_cpus = ELB_DFLT_AWS_NUM_CPUS,
                              mt_mode = MTMode.ZERO,
                              db_mem_margin = ELB_BLASTDB_MEMORY_MARGIN,
                              region = 'test-region')
    assert result == 'm5.4xlarge'

    result = get_machine_type(cloud_provider = CSP.AWS,
                              db = db_metadata,
                              num_cpus = ELB_DFLT_AWS_NUM_CPUS,
                              mt_mode = MTMode.ONE,
                              db_mem_margin = ELB_BLASTDB_MEMORY_MARGIN,
                              region = 'test-region')
    assert result == 'm5.8xlarge'

    # GCP
    result = get_machine_type(cloud_provider = CSP.GCP,
                              db = db_metadata,
                              num_cpus = ELB_DFLT_GCP_NUM_CPUS,
                              mt_mode = MTMode.ZERO,
                              db_mem_margin = ELB_BLASTDB_MEMORY_MARGIN,
                              region = 'test-region')
    assert result == 'e2-standard-16'

    result = get_machine_type(cloud_provider = CSP.GCP,
                              db = db_metadata,
                              num_cpus = ELB_DFLT_AWS_NUM_CPUS,
                              mt_mode = MTMode.ONE,
                              db_mem_margin = ELB_BLASTDB_MEMORY_MARGIN,
                              region = 'test-region')
    assert result == 'e2-standard-32'

