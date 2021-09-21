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
Tests for elb/config.py

Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
Created: Fri 24 Apr 2020 09:43:24 AM EDT
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import pytest
import configparser
import argparse
import hashlib
import getpass
import re
from elastic_blast.util import UserReportError

from elastic_blast.config import configure, _set_sections
from elastic_blast.constants import CFG_BLAST, CFG_BLAST_BATCH_LEN, CFG_BLAST_DB, CFG_BLAST_DB_MEM_MARGIN
from elastic_blast.constants import CFG_BLAST_DB_SRC, CFG_BLAST_MEM_LIMIT, CFG_BLAST_MEM_REQUEST, CFG_BLAST_OPTIONS, CFG_BLAST_QUERY
from elastic_blast.constants import CFG_CLUSTER_EXP_USE_LOCAL_SSD, CFG_CP_AWS_KEY_PAIR, CFG_CP_AWS_REGION, CFG_CP_AWS_SECURITY_GROUP
from elastic_blast.constants import CFG_CP_AWS_SUBNET, CFG_CP_GCP_NETWORK, CFG_CP_GCP_PROJECT, CFG_CP_GCP_REGION, CFG_CP_GCP_ZONE
from elastic_blast.constants import CFG_TIMEOUTS, CFG_TIMEOUT_BLAST_K8S_JOB, CFG_TIMEOUT_INIT_PV
from elastic_blast.constants import CFG_BLAST_PROGRAM, CFG_BLAST_RESULTS, CFG_CLOUD_PROVIDER
from elastic_blast.constants import CFG_CLUSTER, CFG_CLUSTER_BID_PERCENTAGE, CFG_CLUSTER_MACHINE_TYPE
from elastic_blast.constants import CFG_CLUSTER_NAME
from elastic_blast.constants import CFG_CLUSTER_NUM_CPUS, CFG_CLUSTER_NUM_NODES, CFG_CLUSTER_PD_SIZE
from elastic_blast.constants import CFG_CLUSTER_PROVISIONED_IOPS, CFG_CLUSTER_USE_PREEMPTIBLE
from elastic_blast.constants import CFG_CP_NAME, CSP, INPUT_ERROR, SYSTEM_MEMORY_RESERVE
from elastic_blast.constants import ELB_DFLT_AWS_MACHINE_TYPE, ELB_DFLT_OUTFMT, ElbCommand
from elastic_blast.constants import MolType
from elastic_blast import constants
from elastic_blast.util import ElbSupportedPrograms
from elastic_blast.gcp_traits import get_machine_properties
from elastic_blast.base import InstanceProperties, DBSource
from elastic_blast.elb_config import ElasticBlastConfig

TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


class ElbConfigLibTester(unittest.TestCase):

    """ Testing class for this module. """

    def test_invalid_configuration_blank(self):
        cfg = configparser.ConfigParser()

        with self.assertRaises(UserReportError):
            ElasticBlastConfig(cfg, task=ElbCommand.SUBMIT)

        _set_sections(cfg)
        with self.assertRaises(UserReportError):
            ElasticBlastConfig(cfg, task=ElbCommand.SUBMIT)


    def setUp(self):
        self.cfg = configparser.ConfigParser()
        _set_sections(self.cfg)

    def test_invalid_gcp_cluster_name(self):
        self.cfg.read(f"{TEST_DATA_DIR}/correct-cfg-file.ini")
        cfg = ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

        self.cfg[CFG_CLUSTER][CFG_CLUSTER_NAME] = 'invalid-CLUSTER_NAME'
        with self.assertRaises(UserReportError):
            ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

        self.cfg[CFG_CLUSTER][CFG_CLUSTER_NAME] = 'invalid-cluster-name-'
        with self.assertRaises(UserReportError):
            ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

        self.cfg[CFG_CLUSTER][CFG_CLUSTER_NAME] = 'invalid-cluster-name-because-it-is-long-it-should-be-less-than-40-characters'
        with self.assertRaises(UserReportError):
            ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

        self.cfg[CFG_CLUSTER][CFG_CLUSTER_NAME] = 'valid-name'
        ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

    def test_invalid_configuration_invalid_params(self):
        self.cfg.read(f"{TEST_DATA_DIR}/invalid-parameters.ini")

        with self.assertRaises(UserReportError):
            ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

        self.cfg[CFG_BLAST][CFG_BLAST_PROGRAM] = 'blastp'
        with self.assertRaises(UserReportError):
            ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

        self.cfg[CFG_CLUSTER][CFG_CLUSTER_NUM_NODES] = '1'

        self.cfg[CFG_BLAST][CFG_BLAST_DB_SRC] = 'AWS'
        self.cfg.write(sys.stdout)
        ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)


        # Test some explicitly set incorrect values: blast.batch-len
        self.cfg[CFG_BLAST][CFG_BLAST_BATCH_LEN] = 'junk'
        with self.assertRaises(UserReportError):
            ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        self.cfg[CFG_BLAST][CFG_BLAST_BATCH_LEN] = '1'
        ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

        # Test some explicitly set incorrect values: blast.mem-request
        self.cfg[CFG_BLAST][CFG_BLAST_MEM_REQUEST] = 'junk'
        with self.assertRaises(UserReportError):
            ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        self.cfg[CFG_BLAST][CFG_BLAST_MEM_REQUEST] = '1G'
        ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

        # Test some explicitly set incorrect values: blast.mem-limit
        self.cfg[CFG_BLAST][CFG_BLAST_MEM_LIMIT] = 'junk'
        with self.assertRaises(UserReportError):
            ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        self.cfg[CFG_BLAST][CFG_BLAST_MEM_LIMIT] = '1.0G'
        ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

        # Test some explicitly set incorrect values: timeouts.init-pv
        self.cfg[CFG_TIMEOUTS][CFG_TIMEOUT_INIT_PV] = 'junk'
        with self.assertRaises(UserReportError):
            ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        self.cfg[CFG_TIMEOUTS][CFG_TIMEOUT_INIT_PV] = '1'
        ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

        # Test some explicitly set incorrect values: timeouts.blast-k8s-job
        self.cfg[CFG_TIMEOUTS][CFG_TIMEOUT_BLAST_K8S_JOB] = '-3'
        with self.assertRaises(UserReportError):
            ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        self.cfg[CFG_TIMEOUTS][CFG_TIMEOUT_BLAST_K8S_JOB] = '1'
        ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

        # Test some explicitly set incompatible values: auto-scaling and local SSD
        self.cfg[CFG_CLUSTER][CFG_CLUSTER_EXP_USE_LOCAL_SSD] = 'yes'
        with self.assertRaises(NotImplementedError):
            ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        self.cfg.remove_option(CFG_CLUSTER, CFG_CLUSTER_EXP_USE_LOCAL_SSD)
        ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

        # Test some explicitly set incorrect values: blast.blastdb-src
        self.cfg[CFG_BLAST][CFG_BLAST_DB_SRC] = 'none'
        with self.assertRaises(UserReportError):
            ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        self.cfg[CFG_BLAST][CFG_BLAST_DB_SRC] = 'ncbi'
        ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

    def test_invalid_configuration_corrupt_file(self):
        with self.assertRaises(configparser.MissingSectionHeaderError):
            self.cfg.read(f"{TEST_DATA_DIR}/corrupt-cfg-file.ini")

    def test_invalid_configuration_non_existent_file(self):
        with self.assertRaises(FileNotFoundError):
            args = argparse.Namespace(cfg='/dev/null')
            cfg = configure(args)

        with self.assertRaises(FileNotFoundError):
            args = argparse.Namespace(cfg='some-non-existent-file')
            cfg = configure(args)

    def test_invalid_configuration_missing_required_params(self):
        self.cfg.read(f"{TEST_DATA_DIR}/missing-required-parameters.ini")
        with self.assertRaises(UserReportError):
            ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        self.cfg[CFG_BLAST][CFG_BLAST_RESULTS] = "my-bucket"
        with self.assertRaises(UserReportError):
            ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        self.cfg[CFG_BLAST][CFG_BLAST_RESULTS] = "gs://my-bucket"
        with self.assertRaises(UserReportError):
            ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        self.cfg[CFG_BLAST][CFG_BLAST_DB] = "nr"
        with self.assertRaises(UserReportError):
            ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        self.cfg[CFG_CLOUD_PROVIDER][CFG_CP_GCP_PROJECT] = "dummy"
        self.cfg[CFG_BLAST][CFG_BLAST_DB_SRC] = "GCP"
        ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

    def test_invalid_gcp_network_configuration(self):
        self.cfg.read(f"{TEST_DATA_DIR}/incomplete-gcp-vpc-cfg-file.ini")
        with self.assertRaises(UserReportError):
            ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        self.cfg[CFG_CLOUD_PROVIDER][CFG_CP_GCP_NETWORK] = "custom-vpc"
        ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

    @patch(target='elastic_blast.elb_config.aws_get_machine_properties', new=MagicMock(return_value=InstanceProperties(32, 120)))
    def test_provisioned_iops(self):
        self.cfg.read(f"{TEST_DATA_DIR}/elb-aws-blastn-pdbnt.ini")
        ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        self.cfg[CFG_CLUSTER][CFG_CLUSTER_PROVISIONED_IOPS] = '2000'
        ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

    def test_correct_configuration(self):
        self.cfg.read(f"{TEST_DATA_DIR}/correct-cfg-file.ini")
        ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

    def test_minimal_configuration(self):
        """Test the auto-configurable parameters"""
        args = argparse.Namespace(cfg=os.path.join(TEST_DATA_DIR, 'minimal-cfg-file.ini'))
        self.cfg = configure(args)
        cfg = ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

        self.assertTrue(cfg.blast.db_source)
        self.assertEqual(cfg.blast.db_source, DBSource.GCP)

        self.assertTrue(cfg.blast.batch_len)
        self.assertEqual(cfg.blast.batch_len, 10000)

        self.assertTrue(cfg.blast.mem_request)
        self.assertEqual(cfg.blast.mem_request, '0.5G')

        self.assertTrue(cfg.blast.mem_limit)
        expected_mem_limit = f'{get_machine_properties(cfg.cluster.machine_type).memory - SYSTEM_MEMORY_RESERVE}G'
        self.assertEqual(cfg.blast.mem_limit, expected_mem_limit)

        self.assertTrue(cfg.timeouts.init_pv > 0)
        self.assertTrue(cfg.timeouts.blast_k8s > 0)

        ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)

    def test_default_outfmt(self):
        """ Test that default optional BLAST parameters has -outfmt 11 set """
        args = argparse.Namespace(cfg=os.path.join(TEST_DATA_DIR, 'minimal-cfg-file.ini'))
        self.cfg = configure(args)
        cfg = ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        self.assertEqual(cfg.blast.options.strip(), f'-outfmt {ELB_DFLT_OUTFMT}')

    def test_optional_blast_parameters(self):
        """ Test that optional BLAST parameters properly read from config file """
        args = argparse.Namespace(cfg=os.path.join(TEST_DATA_DIR, 'optional-cfg-file.ini'))
        self.cfg = configure(args)
        cfg = ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        # str.find is not enough here, need to make sure options are properly merged
        # with whitespace around them.
        options = cfg.blast.options.strip()
        self.assertTrue(re.search('(^| )-outfmt 11($| )', options) != None)
        self.assertTrue(re.search('(^| )-task blastp-fast($| )', options) != None)

    def test_optional_blast_parameters_from_command_line(self):
        """ Test that parameters are read correctly from command line """
        args = argparse.Namespace(cfg=os.path.join(TEST_DATA_DIR, 'optional-cfg-file.ini'), blast_opts=['-outfmt', '8'])
        print(args)
        self.cfg = configure(args)
        cfg = ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        self.assertTrue(re.search('(^| )-outfmt 8($| )', cfg.blast.options.strip()) != None)
        # NB - options are treated as single entity and command line overwrites them all, not merge, not overwrites selectively
        self.assertTrue(cfg.blast.options.strip().find('-task blastp-fast') < 0)

    def test_db_mol_type(self):
        sp = ElbSupportedPrograms()
        for p in ['BLASTp', 'blastx', 'PSIBLAST', 'rpsBLAST', 'rpstblastn']:
            self.assertEqual(sp.get_db_mol_type(p), MolType.PROTEIN)
        for p in ['blastn', 'tBLASTn', 'TBLASTX']:
            self.assertEqual(sp.get_db_mol_type(p), MolType.NUCLEOTIDE)

    def test_invalid_db_mol_type(self):
        sp = ElbSupportedPrograms()
        for p in ['psi-blast', 'dummy', 'rps-blast']:
            with self.assertRaises(NotImplementedError):
                sp.get_db_mol_type(p)

    def test_query_mol_type(self):
        sp = ElbSupportedPrograms()
        for p in ['BLASTp', 'tblastn', 'PSIBLAST', 'rpsBLAST']:
            self.assertEqual(sp.get_query_mol_type(p), MolType.PROTEIN)
        for p in ['blastn', 'BLASTx', 'TBLASTX', 'rpstblastn']:
            self.assertEqual(sp.get_query_mol_type(p), MolType.NUCLEOTIDE)

    def test_invalid_query_mol_type(self):
        sp = ElbSupportedPrograms()
        for p in ['psi-blast', 'dummy', 'rps-blast']:
            with self.assertRaises(NotImplementedError):
                sp.get_query_mol_type(p)

    def test_two_cloud_providers(self):
        self.cfg.read(f"{TEST_DATA_DIR}/correct-cfg-file.ini")
        ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        self.cfg[CFG_CLOUD_PROVIDER][CFG_CP_AWS_REGION] = 'us-east-1'
        with self.assertRaises(UserReportError) as err:
            ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        assert 'more than one cloud provider' in str(err.exception)

    def test_no_cloud_provider(self):
        self.cfg.read(f"{TEST_DATA_DIR}/correct-cfg-file.ini")
        ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        self.cfg[CFG_CLOUD_PROVIDER] = {}
        with self.assertRaises(UserReportError) as err:
            ElasticBlastConfig(self.cfg, task = ElbCommand.SUBMIT)
        assert 'Cloud provider configuration is missing' in str(err.exception)


def test_validate_gcp_config():
    """Test validation of GCP id strings in config"""
    cfg = configparser.ConfigParser()
    cfg.read(f"{TEST_DATA_DIR}/correct-cfg-file.ini")
    ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)

    # test correct parameter values
    cfg[CFG_CLOUD_PROVIDER] = {CFG_CP_GCP_PROJECT: 'correct-gcp-project',
                               CFG_CP_GCP_REGION: 'correct-region-123',
                               CFG_CP_GCP_ZONE: 'correct-zone-456'}
    ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)


    # test missing parameter values
    cfg[CFG_CLOUD_PROVIDER] = {CFG_CP_GCP_NETWORK: 'test-network'}
    with pytest.raises(UserReportError) as err:
        ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)
    messages = str(err.value).split('\n')
    assert len(messages) >= 3
    assert [s for s in messages if s.startswith('Missing gcp-project')]
    assert [s for s in messages if s.startswith('Missing gcp-region')]
    assert [s for s in messages if s.startswith('Missing gcp-zone')]

    # test incorrect parameter values
    cfg[CFG_CLOUD_PROVIDER] = {CFG_CP_GCP_PROJECT: 'UPPERCASE-project',
                               CFG_CP_GCP_REGION: 'region with space',
                               CFG_CP_GCP_ZONE: 'zone-with#'}
    with pytest.raises(UserReportError) as err:
        ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)
    messages = str(err.value).split('\n')
    assert len(messages) >= 3
    assert [s for s in messages if s.startswith('Parameter "gcp-project" has an invalid value')]
    assert [s for s in messages if s.startswith('Parameter "gcp-region" has an invalid value')]
    assert [s for s in messages if s.startswith('Parameter "gcp-zone" has an invalid value')]


@patch(target='elastic_blast.elb_config.aws_get_machine_properties', new=MagicMock(return_value=InstanceProperties(32, 120)))
def test_validate_aws_config():
    """Test validation of AWS config"""
    cfg = configparser.ConfigParser()
    cfg[CFG_BLAST] = {CFG_BLAST_PROGRAM: 'blastp',
                      CFG_BLAST_RESULTS: 's3://test-results',
                      CFG_BLAST_DB: 'test-db',
                      CFG_BLAST_QUERY: 'test-queries'}

    valid_aws_provider = {
        CFG_CP_AWS_REGION: 'correct-Region-1',
        CFG_CP_AWS_SUBNET: 'subnet-2345145',
        CFG_CP_AWS_KEY_PAIR: 'foo',
        CFG_CP_AWS_SECURITY_GROUP: 'sg-2345145'
    }

    # test correct value
    cfg[CFG_CLOUD_PROVIDER] = valid_aws_provider
    ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)

    # test missing value
    cfg[CFG_CLOUD_PROVIDER] = {CFG_CP_AWS_SUBNET: 'test-subnet'}
    with pytest.raises(UserReportError) as err:
        ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)
    messages = str(err.value).split('\n')
    assert messages
    assert [s for s in messages if s.startswith('Missing aws-region')]

    # test incorrect value
    cfg[CFG_CLOUD_PROVIDER] = {CFG_CP_AWS_REGION: 'incorrect_region'}
    with pytest.raises(UserReportError) as err:
        ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)
    messages = str(err.value).split('\n')
    assert messages
    assert [s for s in messages if s.startswith('Parameter "aws-region" has an invalid value')]

    # Test BLAST programs
    cfg[CFG_CLOUD_PROVIDER] = valid_aws_provider
    # test missing BLAST program
    cfg[CFG_BLAST] = {CFG_BLAST_RESULTS: 's3://test-results'}
    with pytest.raises(UserReportError) as err:
        ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)
    messages = str(err.value).split('\n')
    assert messages
    assert [s for s in messages if s.startswith('Missing program')]

    # test invalid BLAST program
    cfg[CFG_BLAST] = {CFG_BLAST_PROGRAM: 'invalid_program',
                      CFG_BLAST_RESULTS: 's3://test-results'}
    with pytest.raises(UserReportError) as err:
        ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)
    messages = str(err.value).split('\n')
    assert messages
    assert [s for s in messages if s.startswith('Parameter "program" has an invalid value')]


@patch(target='elastic_blast.elb_config.aws_get_machine_properties', new=MagicMock(return_value=InstanceProperties(32, 120)))
def test_validate_results_bucket_config():
    """Test validation of AWS config"""
    cfg = configparser.ConfigParser()
    _set_sections(cfg)

    # test bucket consistent with cloud provider
    cfg[CFG_CLOUD_PROVIDER] = {
        CFG_CP_AWS_REGION: 'us-east-1',
        CFG_CP_AWS_SUBNET: 'subnet-2345145',
        CFG_CP_AWS_KEY_PAIR: 'foo',
        CFG_CP_AWS_SECURITY_GROUP: 'sg-2345145'
    }

    cfg[CFG_BLAST][CFG_BLAST_RESULTS] = 's3://bucket'
    # pacify submit config checks
    cfg[CFG_BLAST][CFG_BLAST_PROGRAM] = 'blastn'
    cfg[CFG_BLAST][CFG_BLAST_QUERY] = 'queries'
    cfg[CFG_BLAST][CFG_BLAST_DB] = 'nt'
    ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)

    # test bucket inconsistent with cloud provider
    cfg[CFG_BLAST][CFG_BLAST_RESULTS] = 'gs://bucket'
    with pytest.raises(UserReportError):
        ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)

    # test invalid bucket with no prefix
    cfg[CFG_BLAST][CFG_BLAST_RESULTS] = 'bucket'
    with pytest.raises(UserReportError):
        ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)

    # test invalid bucket with illigal characters in bucket name
    cfg[CFG_BLAST][CFG_BLAST_RESULTS] = 's3://s3://bucket'
    with pytest.raises(UserReportError):
        ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)

    # test correct results buckets
    cfg[CFG_BLAST][CFG_BLAST_RESULTS] = 's3://bucket'
    ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)

    cfg[CFG_BLAST][CFG_BLAST_RESULTS] = 's3://bucket-123/some-dir#$!'
    ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)


@patch(target='elastic_blast.elb_config.aws_get_machine_properties', new=MagicMock(return_value=InstanceProperties(32, 120)))
def test_validate_queries_config():
    """Test validation of AWS config"""
    cfg = configparser.ConfigParser()
    _set_sections(cfg)

    # set up test config
    cfg[CFG_CLOUD_PROVIDER] = {
        CFG_CP_AWS_REGION: 'us-east-1',
        CFG_CP_AWS_SUBNET: 'subnet-2345145',
        CFG_CP_AWS_KEY_PAIR: 'foo',
        CFG_CP_AWS_SECURITY_GROUP: 'sg-2345145'
    }
    # pacify submit config checks
    cfg[CFG_BLAST][CFG_BLAST_RESULTS] = 's3://bucket'
    cfg[CFG_BLAST][CFG_BLAST_DB] = 'nt'
    cfg[CFG_BLAST][CFG_BLAST_PROGRAM] = 'blastn'
    cfg[CFG_CLUSTER][CFG_CLUSTER_MACHINE_TYPE] = ELB_DFLT_AWS_MACHINE_TYPE

    # test correct queries
    # S3 bucket
    cfg[CFG_BLAST][CFG_BLAST_QUERY] = 's3://bucket-123/@#$*/queris!.fa'
    ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)

    # GS bucket
    cfg[CFG_BLAST][CFG_BLAST_QUERY] = 'gs://bucket-123/@^*?/queries@.fa'
    ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)

    # local file
    cfg[CFG_BLAST][CFG_BLAST_QUERY] = 'queries'
    ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)

    # test illigal characters in bucket name
    cfg[CFG_BLAST][CFG_BLAST_QUERY] = 's3://bucket!-123/@#$*/queris!.fa'
    with pytest.raises(UserReportError) as err:
        ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)
    assert 'Incorrect queries' in err.value.message

    cfg[CFG_BLAST][CFG_BLAST_QUERY] = 'gs://bucket@-123/@#$*/queris!.fa'
    with pytest.raises(UserReportError) as err:
        ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)
    assert 'Incorrect queries' in err.value.message


@ pytest.fixture()
def env_config():
    """Set ELB_* environment variables and clean them up after a test"""
    # setup
    env = {'ELB_GCP_PROJECT': 'expected-gcp-project',
           'ELB_GCP_REGION': 'expected-gcp-region',
           'ELB_GCP_ZONE': 'expected-gcp-zone',
           'ELB_BATCH_LEN': '93',
           'ELB_CLUSTER_NAME': 'expected-cluster-name',
           'ELB_RESULTS': 'gs://expected-results',
           'ELB_USE_PREEMPTIBLE': 'true',
           'ELB_BID_PERCENTAGE': '91'}

    for var_name in env:
        os.environ[var_name] = str(env[var_name])

    yield env

    # cleanup
    for var_name in env:
        # os.unsetenv does not work on every system
        del os.environ[var_name]


def test_load_config_from_environment(env_config):
    """Test config values set from environment"""
    args = argparse.Namespace()
    cfg = configure(args)

    assert cfg[CFG_CLOUD_PROVIDER][CFG_CP_GCP_PROJECT] == env_config['ELB_GCP_PROJECT']
    assert cfg[CFG_CLOUD_PROVIDER][CFG_CP_GCP_REGION] == env_config['ELB_GCP_REGION']
    assert cfg[CFG_CLOUD_PROVIDER][CFG_CP_GCP_ZONE] == env_config['ELB_GCP_ZONE']
    assert cfg[CFG_BLAST][CFG_BLAST_BATCH_LEN] == env_config['ELB_BATCH_LEN']
    assert cfg[CFG_CLUSTER][CFG_CLUSTER_NAME] == env_config['ELB_CLUSTER_NAME']
    assert cfg[CFG_CLUSTER][CFG_CLUSTER_USE_PREEMPTIBLE] == env_config['ELB_USE_PREEMPTIBLE']
    assert cfg[CFG_CLUSTER][CFG_CLUSTER_BID_PERCENTAGE] == env_config['ELB_BID_PERCENTAGE']


def check_common_defaults(cfg):
    """Test default config parametr values common for all cloud providers"""
    assert cfg.cluster.name.startswith('elasticblast')  # Needed to run ElasticBLAST on NCBI AWS account see SYS-360205
    if cfg.cloud_provider.cloud == CSP.GCP:
        assert cfg.cluster.machine_type == constants.ELB_DFLT_GCP_MACHINE_TYPE
    else:
        assert cfg.cluster.machine_type == constants.ELB_DFLT_AWS_MACHINE_TYPE

    assert cfg.cluster.use_preemptible == constants.ELB_DFLT_USE_PREEMPTIBLE
    assert cfg.blast.options == f'-outfmt {int(constants.ELB_DFLT_OUTFMT)}'
    assert cfg.blast.db_source.name == cfg.cloud_provider.cloud.name
    assert cfg.blast.db_mem_margin == constants.ELB_BLASTDB_MEMORY_MARGIN


@patch(target='elastic_blast.elb_config.aws_get_machine_properties', new=MagicMock(return_value=InstanceProperties(32, 120)))
def test_aws_defaults():
    """Test that default config parameters are set correctly for AWS"""
    args = argparse.Namespace(cfg=os.path.join(TEST_DATA_DIR, 'aws-defaults.ini'))
    cfg = ElasticBlastConfig(configure(args), task = ElbCommand.SUBMIT)
    check_common_defaults(cfg)

    assert cfg.cloud_provider.cloud == CSP.AWS
    assert cfg.cluster.pd_size == constants.ELB_DFLT_AWS_PD_SIZE


def test_gcp_defaults():
    """Test that default config parameters are set correctly for GCP"""
    args = argparse.Namespace(cfg=os.path.join(TEST_DATA_DIR, 'gcp-defaults.ini'))
    cfg = ElasticBlastConfig(configure(args), task = ElbCommand.SUBMIT)
    check_common_defaults(cfg)

    assert cfg.cloud_provider.cloud == CSP.GCP
    assert cfg.cluster.pd_size == constants.ELB_DFLT_GCP_PD_SIZE

    assert cfg.timeouts.blast_k8s == constants.ELB_DFLT_BLAST_K8S_TIMEOUT
    assert cfg.timeouts.init_pv == constants.ELB_DFLT_INIT_PV_TIMEOUT


TEST_RESULTS_BUCKET = 'gs://elasticblast-test'
@ pytest.fixture()
def env_config_no_cluster():
    """Set ELB_* environment variables and clean them up after a test"""
    # setup
    env = {'ELB_GCP_PROJECT': 'expected-gcp-project',
           'ELB_RESULTS': 'gs://expected-results'}

    for var_name in env:
        os.environ[var_name] = env[var_name]
    # Test that the results parameter is passed correctly and that trailing slash is discarded
    os.environ['ELB_RESULTS'] = TEST_RESULTS_BUCKET + '/'

    yield env

    # cleanup
    for var_name in env:
        # os.unsetenv does not work on every system
        del os.environ[var_name]


def test_cluster_name_from_environment(env_config):
    """Test cluster name from environment overrides everything else"""
    args = argparse.Namespace(cfg=os.path.join(TEST_DATA_DIR, 'gcp-defaults.ini'))
    cfg = ElasticBlastConfig(configure(args), task = ElbCommand.SUBMIT)

    assert cfg.cluster.results == env_config['ELB_RESULTS']
    assert cfg.cluster.name == env_config['ELB_CLUSTER_NAME']


def test_generated_cluster_name(env_config_no_cluster):
    """Test cluster name generated from results, and value from config file is ignored"""
    args = argparse.Namespace(cfg=os.path.join(TEST_DATA_DIR, 'gcp-defaults.ini'))
    cfg = ElasticBlastConfig(configure(args), task = ElbCommand.SUBMIT)

    assert cfg.cluster.results == TEST_RESULTS_BUCKET
    user = getpass.getuser()
    digest = hashlib.md5(TEST_RESULTS_BUCKET.encode()).hexdigest()[0:9]
    assert cfg.cluster.name == f'elasticblast-{user.lower()}-{digest}'


@patch(target='elastic_blast.elb_config.aws_get_machine_properties', new=MagicMock(return_value=InstanceProperties(32, 120)))
def test_multiple_query_files():
    """Test getting config with multiple query files"""
    args = argparse.Namespace(cfg=os.path.join(TEST_DATA_DIR, 'multiple-query-files.ini'))
    cfg = ElasticBlastConfig(configure(args), task = ElbCommand.SUBMIT)
    expected_query_files = ['query-file-1', 'query-file-2']
    assert sorted(cfg.blast.queries_arg.split()) == sorted(expected_query_files)


def test_mem_limit_too_high():
    """Test that setting memory limit that exceeds cloud instance memory
    triggers an error"""
    args = argparse.Namespace(cfg=os.path.join(TEST_DATA_DIR, 'mem-limit-too-high.ini'))
    with pytest.raises(UserReportError) as err:
        cfg = ElasticBlastConfig(configure(args), task = ElbCommand.SUBMIT)
    assert err.value.returncode == INPUT_ERROR
    m = re.match(r'Memory limit.*exceeds', err.value.message)
    assert m is not None
    

@patch(target='elastic_blast.elb_config.aws_get_machine_properties', new=MagicMock(return_value=InstanceProperties(4, 2)))
def test_instance_too_small_aws():
    """Test that using too small an instance triggers an error"""
    args = argparse.Namespace(cfg=os.path.join(TEST_DATA_DIR, 'instance-too-small-aws.ini'))
    with pytest.raises(UserReportError) as err:
        cfg = ElasticBlastConfig(configure(args), task = ElbCommand.SUBMIT)
        cfg.validate()
    assert err.value.returncode == INPUT_ERROR
    print(err.value.message)
    assert 'does not have enough memory' in err.value.message
    
def test_instance_too_small_gcp():
    """Test that using too small an instance triggers an error"""
    args = argparse.Namespace(cfg=os.path.join(TEST_DATA_DIR, 'instance-too-small-gcp.ini'))
    with pytest.raises(UserReportError) as err:
        cfg = ElasticBlastConfig(configure(args), task = ElbCommand.SUBMIT)
        cfg.validate()
    assert err.value.returncode == INPUT_ERROR
    print(err.value.message)
    assert 'does not have enough memory' in err.value.message
