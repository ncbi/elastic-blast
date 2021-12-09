#!/usr/bin/env python3
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
tests/resources/quotas/test_quotas.py - Tests for resource quotas module

Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
"""
import os
import unittest
from unittest.mock import MagicMock, patch
import configparser
import pytest
from elastic_blast.config import _set_sections
from elastic_blast.constants import CSP
from elastic_blast.resources.quotas.quota_check import check_resource_quotas
from elastic_blast.base import InstanceProperties
from elastic_blast.elb_config import ElasticBlastConfig
from elastic_blast.constants import ElbCommand
from elastic_blast.db_metadata import DbMetadata
from tests.utils import GKEMock

TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'data')

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


class TestResourceQuotasAws(unittest.TestCase):

    def setUp(self):
        """ Initialize 2 configurations: one for GCP another for AWS """
        cfg_gcp = configparser.ConfigParser()
        cfg_aws = configparser.ConfigParser()
        _set_sections(cfg_gcp)
        _set_sections(cfg_aws)

        cfg_gcp.read(f"{TEST_DATA_DIR}/correct-cfg-file.ini")
        cfg_aws.read(f"{TEST_DATA_DIR}/elb-aws-blastn-pdbnt.ini")

        with patch('elastic_blast.elb_config.get_db_metadata', new=MagicMock(return_value=DB_METADATA)):
            with patch(target='elastic_blast.elb_config.safe_exec', new=MagicMock(side_effect=GKEMock().mocked_safe_exec)):
                with patch(target='elastic_blast.util.safe_exec', new=MagicMock(side_effect=GKEMock().mocked_safe_exec)):
                    self.cfg_gcp = ElasticBlastConfig(cfg_gcp, task = ElbCommand.SUBMIT)
        with patch('elastic_blast.elb_config.aws_get_machine_properties', new=MagicMock(return_value=InstanceProperties(32, 120))):
            with patch('elastic_blast.elb_config.get_db_metadata', new=MagicMock(return_value=DB_METADATA)):
                with patch(target='boto3.client', new=MagicMock(side_effect=GKEMock().mocked_client)):
                    self.cfg_aws = ElasticBlastConfig(cfg_aws, task = ElbCommand.SUBMIT)

    @pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='AWS credentials not set in TC')
    def test_check_resource_quotas_aws(self):
        self.assertEqual(self.cfg_aws.aws.cloud, CSP.AWS)
        check_resource_quotas(self.cfg_aws)

    def test_check_resource_quotas_gcp(self):
        with self.assertRaises(NotImplementedError) as cm:
            self.assertEqual(self.cfg_gcp.gcp.cloud, CSP.GCP)
            check_resource_quotas(self.cfg_gcp)
            self.assertEqual('not implemented yet', str(cm.exception))


if __name__ == '__main__':
    unittest.main()
