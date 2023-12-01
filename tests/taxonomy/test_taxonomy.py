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
Tests for taxonomy filtering implemented in elb/taxonomy.py

Author: Greg Boratyn (boratyng@ncbi.nlm.nih.gov)
"""

import configparser
import re
from tempfile import NamedTemporaryFile
from unittest.mock import patch

from elastic_blast import taxonomy
from elastic_blast import constants
from elastic_blast.constants import ELB_TAXIDLIST_FILE
from elastic_blast.constants import ElbCommand
from elastic_blast.elb_config import ElasticBlastConfig
from elastic_blast.base import InstanceProperties
from tests.utils import gke_mock

import pytest


@pytest.fixture
def mocked_get_machine_properties(mocker):
    """Fixture that proviedes mocked get_machine_properties function so that
    AWS credentials and real AWS regions are not needed for the tests"""
    def fun_mocked_get_machine_properties(instance_type, boto_cfg=None):
        """Mocked getting instance number of CPUs and memory"""
        return InstanceProperties(32, 128)

    mocker.patch('elastic_blast.elb_config.aws_get_machine_properties', side_effect=fun_mocked_get_machine_properties)
    mocker.patch('elastic_blast.tuner.aws_get_machine_properties', side_effect=fun_mocked_get_machine_properties)


@pytest.fixture
def cfg(mocked_get_machine_properties, gke_mock):
    """Create an ElasticBlastConfig object"""
    cfg = ElasticBlastConfig(aws_region = 'test-region',
                             program = 'blastn',
                             db = 'testdb',
                             queries = 'test-queries.fa',
                             results = 's3://test-results',
                             task = ElbCommand.SUBMIT)
    yield cfg



def test_setup_taxid_filtering_taxidlist(cfg, gke_mock):
    """Test preparing taxidlist file and blast options for taxid filtering
    -taxids option"""

    # set up input taxidlist
    with NamedTemporaryFile() as fin:
        for i in [2, 3, 4]:
            fin.write(str(i).encode())
            fin.write(b'\n')
        fin.flush()
        fin.seek(0)

        # set up blast command line options
        cfg.blast.options = f'-taxidlist {fin.name}'

        taxonomy.setup_taxid_filtering(cfg)
        assert fin.name not in cfg.blast.options
        matches = re.findall(r'-taxidlist\s+(\S+)', cfg.blast.options)
        assert len(matches) == 1
        assert matches[0] == ELB_TAXIDLIST_FILE


def test_setup_taxid_filtering_negative_taxidlist(cfg, gke_mock):
    """Test preparing taxidlist file and blast options for taxid filtering
    -negative_taxids option"""

    # set up input taxidlist
    with NamedTemporaryFile() as fin:
        for i in [2, 3, 4]:
            fin.write(str(i).encode())
            fin.write(b'\n')
        fin.flush()
        fin.seek(0)

        # set up blast command line options
        cfg.blast.options = f'-negative_taxidlist {fin.name}'

        taxonomy.setup_taxid_filtering(cfg)
        assert fin.name not in cfg.blast.options
        matches = re.findall(r'-negative_taxidlist\s+(\S+)', cfg.blast.options)
        assert len(matches) == 1
        assert matches[0] == ELB_TAXIDLIST_FILE

