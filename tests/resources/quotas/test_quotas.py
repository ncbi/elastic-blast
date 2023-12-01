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
import io
import contextlib
import unittest
from unittest.mock import MagicMock, patch
import configparser
import pytest
from elastic_blast.config import _set_sections
from elastic_blast.constants import CSP, ElbCommand, DEPENDENCY_ERROR
from elastic_blast.resources.quotas.quota_check import check_resource_quotas
from elastic_blast.resources.quotas.quota_aws_ec2_cf import ResourceCheckAwsEc2CloudFormation
from elastic_blast.base import InstanceProperties
from elastic_blast.elb_config import ElasticBlastConfig
from elastic_blast.constants import ElbCommand
from elastic_blast.db_metadata import DbMetadata
from elastic_blast.util import UserReportError
from tests.utils import GKEMock, gke_mock

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

    @patch(target='elastic_blast.elb_config.enable_gcp_api', new=MagicMock())
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



# Values used for mocked vCPU limits
MOCKED_AWS_ON_DEMAND_CPU_LIMIT = 16
MOCKED_AWS_SPOT_CPU_LIMIT = 16

class MockedLimit:
    """Mocked limit object for AwsLimitChecker"""

    def __init__(self, limit):
        self.limit = limit

    def get_limit(self):
        """Return limit value"""
        return self.limit


class MockedAwsLimitChecker:
    """Mocked AwsLimitChecker"""

    def __init__(self):
        pass

    def get_limits(self, service):
        """Get AWS EC2 quota limits"""
        return {'EC2': {'Running On-Demand All Standard instances': MockedLimit(MOCKED_AWS_ON_DEMAND_CPU_LIMIT),
                        'All Standard Spot Instance': MockedLimit(MOCKED_AWS_SPOT_CPU_LIMIT)}}

    def check_thresholds(self, service):
        """Report that no usage thresholds were crossed."""
        return None


class MockedAwsLimitCheckerNoLimits(MockedAwsLimitChecker):
    """Mocked AwsLimitChecker that reports no EC2 limits"""

    def get_limits(self, service):
        """Report no EC2 limits"""
        return {'EC2': {}}


class TestAwsCpuLimits:
    """A group of tests for checking AWS vCPU limits"""

    @pytest.fixture
    @patch(target='elastic_blast.tuner.aws_get_machine_properties', new=MagicMock(return_value=InstanceProperties(32, 120)))
    @patch(target='elastic_blast.elb_config.aws_get_machine_properties', new=MagicMock(return_value=InstanceProperties(32, 120)))
    def elb_cfg(self, gke_mock):
        """Create a mocked ElasticBlastConfig object"""
        cfg = ElasticBlastConfig(aws_region = 'test-region',
                                 program = 'blastn',
                                 queries = 'test-query.fa',
                                 db = 'testdb',
                                 results = 's3://test-results',
                                 machine_type = 'test-machine-type',
                                 task = ElbCommand.SUBMIT)

        return cfg
        

    def test_cannot_create_instance(self, elb_cfg):
        """Test that a quota limit that provides for too few CPUs to create an
        instance is reported via UserReportError with the proper message"""

        cfg = elb_cfg

        # Test on-demand vCPU limit
        # test pre-condition: limit < CPUs per instance, on-demand instances
        alc = MockedAwsLimitChecker()
        r = alc.get_limits(service='dummy')['EC2']
        keys = [k for k in r.keys() if 'On-Demand' in k]
        assert len(keys) == 1
        assert r[keys[0]].get_limit() < cfg.cluster.num_cores_per_instance
        assert not cfg.cluster.use_preemptible

        with patch(target='elastic_blast.resources.quotas.quota_aws_ec2_cf.AwsLimitChecker', side_effect=MockedAwsLimitChecker):
            resource_check = ResourceCheckAwsEc2CloudFormation(cfg)
            with pytest.raises(UserReportError) as err:
                resource_check()
            assert err.value.returncode == DEPENDENCY_ERROR
            assert f'Your account has a quota limit of {MOCKED_AWS_ON_DEMAND_CPU_LIMIT} vCPUs' in err.value.message


        cfg.cluster.use_preemptible = True

        # test pre-condition: limit < CPUs per instance, spot instances
        alc = MockedAwsLimitChecker()
        r = alc.get_limits(service='dummy')['EC2']
        keys = [k for k in r.keys() if 'Spot' in k]
        assert len(keys) == 1
        assert r[keys[0]].get_limit() < cfg.cluster.num_cores_per_instance
        assert cfg.cluster.use_preemptible

        with patch(target='elastic_blast.resources.quotas.quota_aws_ec2_cf.AwsLimitChecker', side_effect=MockedAwsLimitChecker):
            resource_check = ResourceCheckAwsEc2CloudFormation(cfg)
            with pytest.raises(UserReportError) as err:
                resource_check()
            assert err.value.returncode == DEPENDENCY_ERROR
            assert f'Your account has a quota limit of {MOCKED_AWS_ON_DEMAND_CPU_LIMIT} vCPUs' in err.value.message



    def test_fewer_than_expected_on_demand_instances(self, elb_cfg, caplog):
        """Test that a vCPU quota limit for on-demand instances that results
        in fewer than expected running instances is reported via a warning"""

        cfg = elb_cfg

        cfg.cluster.num_cores_per_instance = 16
        cfg.cluster.num_nodes = 10

        # test pre-condition: limit < all CPUs requested, on-demand instances requested
        alc = MockedAwsLimitChecker()
        r = alc.get_limits(service='dummy')['EC2']
        keys = [k for k in r.keys() if 'On-Demand' in k]
        assert len(keys) == 1
        assert r[keys[0]].get_limit() >= cfg.cluster.num_cores_per_instance
        assert r[keys[0]].get_limit() < cfg.cluster.num_cores_per_instance * cfg.cluster.num_nodes
        assert not cfg.cluster.use_preemptible

        with patch(target='elastic_blast.resources.quotas.quota_aws_ec2_cf.AwsLimitChecker', side_effect=MockedAwsLimitChecker):
            ResourceCheckAwsEc2CloudFormation(cfg)()

            msg = '\n'.join([k.msg for k in caplog.records])
            assert f'ElasticBLAST is configured to use up to {cfg.cluster.num_cores_per_instance * cfg.cluster.num_nodes} vCPUs, but only up to {MOCKED_AWS_ON_DEMAND_CPU_LIMIT} can be used in your account' in msg


    def test_fewer_than_expected_spot_instances(self, elb_cfg, caplog):
        """Test that a vCPU quota limit for spot instances that results in
        fewer than expected running instances is reported via a warning"""

        cfg = elb_cfg
        cfg.cluster.use_preemptible = True
        cfg.cluster.num_cores_per_instance = 16
        cfg.cluster.num_nodes = 10

        # test pre-condition: limit < all CPUs requested, spot instances requested
        alc = MockedAwsLimitChecker()
        r = alc.get_limits(service='dummy')['EC2']
        keys = [k for k in r.keys() if 'Spot' in k]
        assert len(keys) == 1
        assert r[keys[0]].get_limit() >= cfg.cluster.num_cores_per_instance
        assert r[keys[0]].get_limit() < cfg.cluster.num_cores_per_instance * cfg.cluster.num_nodes
        assert cfg.cluster.use_preemptible

        with patch(target='elastic_blast.resources.quotas.quota_aws_ec2_cf.AwsLimitChecker', side_effect=MockedAwsLimitChecker):
            ResourceCheckAwsEc2CloudFormation(cfg)()

            msg = '\n'.join([k.msg for k in caplog.records])
            assert f'ElasticBLAST is configured to use up to {cfg.cluster.num_cores_per_instance * cfg.cluster.num_nodes} vCPUs, but only up to {MOCKED_AWS_SPOT_CPU_LIMIT} can be used in your account' in msg


    def test_no_limits_found(self, elb_cfg, caplog):
        """Test that empty EC2 limits are reported via a warning"""

        with patch(target='elastic_blast.resources.quotas.quota_aws_ec2_cf.AwsLimitChecker', side_effect=MockedAwsLimitCheckerNoLimits):
            ResourceCheckAwsEc2CloudFormation(elb_cfg)()

            msg = '\n'.join([k.msg for k in caplog.records])
            assert 'EC2 CPU limit was not found' in msg



if __name__ == '__main__':
    unittest.main()
