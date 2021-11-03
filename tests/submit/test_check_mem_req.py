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
test_check_mem_req.py - unit test for check_memory_requirements
in commands/submit.py module

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""

import pytest
from unittest.mock import patch, MagicMock
from elastic_blast.constants import ELB_DFLT_GCP_MACHINE_TYPE
from tests.utils import MockedCompletedProcess
import elastic_blast
from elastic_blast.commands.submit import check_memory_requirements
from elastic_blast.elb_config import ElasticBlastConfig
from elastic_blast.constants import ElbCommand
from elastic_blast.db_metadata import DbMetadata
from tests.utils import gke_mock

DB_METADATA = DbMetadata(version = '1',
                         dbname = 'some-name',
                         dbtype = 'Protein',
                         description = 'A test database',
                         number_of_letters = 25,
                         number_of_sequences = 25,
                         files = [],
                         last_updated = 'some-date',
                         bytes_total = 25,
                         bytes_to_cache = 25,
                         number_of_volumes = 1)


@patch(target='elastic_blast.elb_config.get_db_metadata', new=MagicMock(return_value=DB_METADATA))
def test_check_memory_requirements(gke_mock, mocker):
    def mock_safe_exec(cmd):
        if isinstance(cmd, list):
            cmd = ' '.join(cmd)
        if cmd == 'gsutil cat gs://blast-db/latest-dir':
            return MockedCompletedProcess(stdout='2020-20-20')
        elif cmd == 'gsutil cat gs://blast-db/2020-20-20/blastdb-manifest.json':
            return MockedCompletedProcess(stdout='{"nt":{"size":93.36}, "nr":{"size":227.4}}')
        return MockedCompletedProcess(stdout='nt\t\t100\t')
    cfg = ElasticBlastConfig(gcp_project = 'test-gcp-project',
                             gcp_region = 'test-gcp-region',
                             gcp_zone = 'test-gcp-zone',
                             program = 'blastn',
                             db = 'nt',
                             queries = 'test-queries',
                             results = 'gs://results',
                             task = ElbCommand.SUBMIT)

    mocker.patch('elastic_blast.util.safe_exec', side_effect=mock_safe_exec)
    check_memory_requirements(cfg)
    cfg.blast.db_mem_margin = 3.0
    with pytest.raises(RuntimeError):
        check_memory_requirements(cfg)
