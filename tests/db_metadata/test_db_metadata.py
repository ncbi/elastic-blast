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
Unit tests for reading database metadata

Author: Greg Boratyn (boratyng@ncbi.nlm.nih.gov)
Created: Mon 27 Sep 2021 05:26:12 PM EDT
"""

import json
import os
from unittest.mock import MagicMock, patch
from elastic_blast.db_metadata import get_db_metadata
from elastic_blast.util import UserReportError
from elastic_blast.constants import MolType, BLASTDB_ERROR
from elastic_blast.base import DBSource
from tests.utils import gke_mock, aws_credentials, DB_METADATA_PROT as DB_METADATA
import pytest

GCP_PRJ = "mocked-gcp-project"

def test_get_db_metadata(gke_mock):
    """Test downloading and parsing BLAST database metadata"""
    REF_METADATA = json.loads(DB_METADATA)

    # for GCP
    db = get_db_metadata('testdb', MolType.PROTEIN, DBSource.GCP, gcp_prj=GCP_PRJ)
    assert db.dbtype == REF_METADATA['dbtype']
    assert db.bytes_to_cache == REF_METADATA['bytes-to-cache']

    # for AWS
    db = get_db_metadata('testdb', MolType.PROTEIN, DBSource.AWS)
    assert db.dbtype == REF_METADATA['dbtype']
    assert db.bytes_to_cache == REF_METADATA['bytes-to-cache']


def test_get_db_metadata_user_db(gke_mock):
    """Test downloading and parsing BLAST database metadata for a user database"""
    REF_METADATA = json.loads(DB_METADATA)

    # for GCP
    db = get_db_metadata('gs://test-bucket/testdb', MolType.PROTEIN, DBSource.GCP, gcp_prj=GCP_PRJ)
    assert db.dbtype == REF_METADATA['dbtype']
    assert db.bytes_to_cache == REF_METADATA['bytes-to-cache']

    # for AWS
    db = get_db_metadata('s3://test-bucket/testdb', MolType.PROTEIN, DBSource.AWS)
    assert db.dbtype == REF_METADATA['dbtype']
    assert db.bytes_to_cache == REF_METADATA['bytes-to-cache']


DB_METADATA_VERSION_12 = """{
  "version": "1.2",
  "dbname": "testdb",
  "dbtype": "Nucleotide",
  "db-version": 5,
  "description": "Some database",
  "number-of-letters": 2592,
  "number-of-sequences": 1,
  "last-updated": "2021-12-28T13:34:00",
  "number-of-volumes": 1,
  "bytes-total": 37772,
  "bytes-to-cache": 754,
  "files": [
    "testdb.ndb",
    "testdb.nhr",
    "testdb.nin",
    "testdb.not",
    "testdb.nsq",
    "testdb.ntf",
    "testdb.nto"
  ]
}
"""

def test_get_db_metadata_version_12(gke_mock):
    """Test downloading and parsing BLAST database metadata file version 1.2"""
    DB_NAME = 'testdb'
    gke_mock.cloud.storage[f'gs://blast-db/000/{DB_NAME}.njs'] = DB_METADATA_VERSION_12
    gke_mock.cloud.storage[f's3://ncbi-blast-databases/000/{DB_NAME}.njs'] = DB_METADATA_VERSION_12

    REF_METADATA = json.loads(DB_METADATA_VERSION_12)

    # for GCP
    db = get_db_metadata('testdb', MolType.NUCLEOTIDE, DBSource.GCP, gcp_prj=GCP_PRJ)
    assert db.dbtype == REF_METADATA['dbtype']
    assert db.bytes_to_cache == REF_METADATA['bytes-to-cache']
    assert db.version == '1.2'

    # for AWS
    db = get_db_metadata('testdb', MolType.NUCLEOTIDE, DBSource.AWS)
    assert db.dbtype == REF_METADATA['dbtype']
    assert db.bytes_to_cache == REF_METADATA['bytes-to-cache']
    assert db.version == '1.2'


def test_get_db_metadata_user_db_version_12(gke_mock):
    """Test downloading and parsing BLAST database metadata file version 1.2 for
    a user database"""
    DB_NAME = 'some-db'
    gke_mock.cloud.storage[f'gs://test-bucket/{DB_NAME}.njs'] = DB_METADATA_VERSION_12
    gke_mock.cloud.storage[f's3://test-bucket/{DB_NAME}.njs'] = DB_METADATA_VERSION_12

    REF_METADATA = json.loads(DB_METADATA_VERSION_12)

    # for GCP
    db = get_db_metadata(f'gs://test-bucket/{DB_NAME}', MolType.NUCLEOTIDE, DBSource.GCP, gcp_prj=GCP_PRJ)
    assert db.dbtype == REF_METADATA['dbtype']
    assert db.bytes_to_cache == REF_METADATA['bytes-to-cache']
    assert db.version == '1.2'

    # for AWS
    db = get_db_metadata(f's3://test-bucket/{DB_NAME}', MolType.NUCLEOTIDE, DBSource.AWS)
    assert db.dbtype == REF_METADATA['dbtype']
    assert db.bytes_to_cache == REF_METADATA['bytes-to-cache']
    assert db.version == '1.2'


def test_missing_metadata_file(gke_mock):
    """Test that the correct exception is raised when the metadata file is
    missing"""
    with pytest.raises(FileNotFoundError):
        get_db_metadata('s3://some-bucket/non-existent-db', MolType.NUCLEOTIDE, DBSource.AWS)

    with pytest.raises(FileNotFoundError):
        get_db_metadata('this-db-does-not-exist', MolType.PROTEIN, DBSource.GCP, gcp_prj=GCP_PRJ)


# additional field at the end
DB_METADATA_NEW_FIELD = """{
  "dbname": "swissprot",
  "version": "1.1",
  "dbtype": "Protein",
  "description": "Non-redundant UniProtKB/SwissProt sequences",
  "number-of-letters": 180911227,
  "number-of-sequences": 477327,
  "files": [
    "gs://blast-db/2021-09-28-01-05-02/swissprot.ppi",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.pos",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.pog",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.phr",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.ppd",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.psq",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.pto",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.pin",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.pot",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.ptf",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.pdb"
  ],
  "last-updated": "2021-09-19T00:00:00",
  "bytes-total": 353839003,
  "bytes-to-cache": 185207299,
  "number-of-volumes": 1,
  "new-field": "some-value"
}
"""

def test_metadata_with_new_field(gke_mock):
    """Test that additional field in the metadata file does not cause problems"""
    DB = 'gs://bucket/somedb'
    REF_METADATA = json.loads(DB_METADATA_NEW_FIELD)
    gke_mock.cloud.storage[f'{DB}-prot-metadata.json'] = DB_METADATA_NEW_FIELD

    db = get_db_metadata(DB, MolType.PROTEIN, DBSource.GCP, gcp_prj=GCP_PRJ)
    assert db.dbtype == REF_METADATA['dbtype']
    assert db.bytes_to_cache == REF_METADATA['bytes-to-cache']


# last-updated is missing
DB_METADATA_MISSING_FIELD = """{
  "dbname": "swissprot",
  "version": "1.1",
  "dbtype": "Protein",
  "description": "Non-redundant UniProtKB/SwissProt sequences",
  "number-of-letters": 180911227,
  "number-of-sequences": 477327,
  "files": [
    "gs://blast-db/2021-09-28-01-05-02/swissprot.ppi",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.pos",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.pog",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.phr",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.ppd",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.psq",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.pto",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.pin",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.pot",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.ptf",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.pdb"
  ],
  "bytes-total": 353839003,
  "bytes-to-cache": 185207299,
  "number-of-volumes": 1
}
"""

def test_missing_field(gke_mock):
    """Test that a missing field in metadata is properly reported"""
    DB = 'gs://bucket/somedb'
    gke_mock.cloud.storage[f'{DB}-prot-metadata.json'] = DB_METADATA_MISSING_FIELD

    with pytest.raises(UserReportError) as err:
        db = get_db_metadata(DB, MolType.PROTEIN, DBSource.GCP, gcp_prj=GCP_PRJ)
    assert err.value.returncode == BLASTDB_ERROR
    # last-updated is the missing field
    assert 'last-updated' in err.value.message
    assert 'required field' in err.value.message


# number-of-letters is a string
DB_METADATA_SPEC_PROBLEM = """{
  "dbname": "swissprot",
  "version": "1.1",
  "dbtype": "Protein",
  "description": "Non-redundant UniProtKB/SwissProt sequences",
  "number-of-letters": "a lot",
  "number-of-sequences": 477327,
  "files": [
    "gs://blast-db/2021-09-28-01-05-02/swissprot.ppi",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.pos",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.pog",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.phr",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.ppd",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.psq",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.pto",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.pin",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.pot",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.ptf",
    "gs://blast-db/2021-09-28-01-05-02/swissprot.pdb"
  ],
  "last-updated": "2021-09-19T00:00:00",
  "bytes-total": 353839003,
  "bytes-to-cache": 185207299,
  "number-of-volumes": 1
}
"""

def test_spec_problem(gke_mock):
    """Test that a missing field in metadata is properly reported"""
    DB = 'gs://bucket/somedb'
    gke_mock.cloud.storage[f'{DB}-prot-metadata.json'] = DB_METADATA_SPEC_PROBLEM

    with pytest.raises(UserReportError) as err:
        db = get_db_metadata(DB, MolType.PROTEIN, DBSource.GCP, gcp_prj=GCP_PRJ)
    assert err.value.returncode == BLASTDB_ERROR
    assert 'Problem parsing BLAST database metadata file' in err.value.message


def test_malformed_json(gke_mock):
    """Test that malformed metadata file is properly reported"""
    DB = 'gs://bucket/somedb'
    gke_mock.cloud.storage[f'{DB}-prot-metadata.json'] = 'abc'

    with pytest.raises(UserReportError) as err:
        db = get_db_metadata(DB, MolType.PROTEIN, DBSource.GCP, gcp_prj=GCP_PRJ)
    assert err.value.returncode == BLASTDB_ERROR
    assert 'is not a proper JSON file' in err.value.message
