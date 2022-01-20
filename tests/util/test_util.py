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
test for elb/util.py

Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
Created: Tue 07 Apr 2020 03:43:24 PM EDT
"""
import os
import unittest
from unittest.mock import patch, MagicMock
import re

from elastic_blast import util
from elastic_blast.constants import ELB_DFLT_GCP_MACHINE_TYPE
from elastic_blast.constants import GCP_MAX_LABEL_LENGTH, AWS_MAX_TAG_LENGTH
from elastic_blast.constants import ElbCommand, MolType
from elastic_blast.util import get_query_batch_size
from elastic_blast.util import convert_memory_to_mb, get_blastdb_size, sanitize_aws_batch_job_name
from elastic_blast.util import safe_exec, SafeExecError, convert_disk_size_to_gb
from elastic_blast.util import sanitize_gcp_labels, sanitize_for_k8s, sanitize_aws_tag
from elastic_blast.util import validate_gcp_string, convert_labels_to_aws_tags
from elastic_blast.util import validate_gcp_disk_name, gcp_get_regions
from elastic_blast.gcp_traits import get_machine_properties
from elastic_blast.elb_config import ElasticBlastConfig
from elastic_blast.base import InstanceProperties
from elastic_blast.db_metadata import DbMetadata
import pytest
from tests.utils import MockedCompletedProcess, gke_mock, GCP_REGIONS


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


def test_mol_type():
    choices = MolType.valid_choices()
    assert(len(choices) == 2)
    assert('prot' in choices)
    assert('nucl' in choices)


class ElbLibTester(unittest.TestCase):
    """ Testing class for this module. """
    def test_batch_size(self):
        expected = 10000
        rv = get_query_batch_size('blastp')
        self.assertEqual(rv, expected)

        rv = get_query_batch_size('BLASTP')
        self.assertEqual(rv, expected)

    def test_batch_size_invalid_input(self):
        expected = -1
        rv = get_query_batch_size('junk')
        self.assertEqual(rv, expected)

        rv = get_query_batch_size(12334)
        self.assertEqual(rv, expected)

    def test_batch_size_env_var(self):
        expected = 10

        original = os.getenv('ELB_BATCH_LEN')
        try:
            os.environ['ELB_BATCH_LEN'] = str(expected)

            rv = get_query_batch_size('blastn')
            self.assertEqual(rv, expected)
        finally:
            del os.environ['ELB_BATCH_LEN']
            if original is not None:
                os.environ['ELB_BATCH_LEN'] = original

    def test_safe_exec(self):
        text = 'some cool text'
        cmd = f'echo {text}'.split()
        p = safe_exec(cmd)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.decode().rstrip(), text)

    def test_safe_exec_fail(self):
        """Test that command line returning with non-zero exit status raises
        SafeExecError"""
        cmd = 'date -o'.split()
        with self.assertRaises(SafeExecError):
            safe_exec(cmd)

    def test_safe_exec_permission_error(self):
        """Test that a non-existent or non-executable binary/shell command
        raises SafeExecError"""
        cmd = ['date -o']
        with self.assertRaises(SafeExecError):
            safe_exec(cmd)

    def test_safe_exec_cmd_not_a_list_or_string(self):
        """Test that safe_exec cmd argument of type other than a list or string
        raises ValueError"""

        with self.assertRaises(ValueError) as e:
            safe_exec(1)

    @patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
    def test_get_blastdb_size(self):
        cfg = create_config_for_db('nr')
        dbsize = get_blastdb_size(cfg.blast.db, cfg.cluster.db_source)
        assert dbsize >= 227.4

    @patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
    def test_get_blastdb_size_invalid_database(self):
        cfg = create_config_for_db('non_existent_blast_database')
        with self.assertRaises(ValueError):
            get_blastdb_size(cfg.blast.db, cfg.cluster.db_source)

    def test_sanitize_gcp_labels(self):
        self.assertEqual('harry-potter', sanitize_gcp_labels('Harry.Potter'))
        self.assertEqual('macbook-pro-home', sanitize_gcp_labels('MacBook-Pro.Home'))
        label = sanitize_gcp_labels('gs://tomcat-test/tc-elb-int-swissprot-psiblast-multi-node-sync-351')
        self.assertLessEqual(len(label), GCP_MAX_LABEL_LENGTH)
        self.assertEqual('gs---tomcat-test-tc-elb-int-swissprot-psiblast-multi-node-sync-', label)

    def test_sanitize_for_k8s(self):
        self.assertEqual('ref-viruses-rep-genomes', sanitize_for_k8s('ref_viruses_rep_genomes'))
        self.assertEqual('betacoronavirus', sanitize_for_k8s('Betacoronavirus'))
        self.assertEqual('16s-ribosomal-rna', sanitize_for_k8s('16S_ribosomal_RNA'))
        self.assertEqual('gcf-000001405.38-top-level', sanitize_for_k8s('GCF_000001405.38_top_level'))

    def test_sanitize_aws_tag(self):
        self.assertEqual('s3://abra-Cada-bra+-@.-', sanitize_aws_tag('s3://abra;Cada#bra+-@.='))
        label = sanitize_aws_tag('s3://tomcat-test/tc-elb-int-swissprot-psiblast-multi-node-sync-351')
        self.assertLessEqual(len(label), AWS_MAX_TAG_LENGTH)
        self.assertEqual('s3://tomcat-test/tc-elb-int-swissprot-psiblast-multi-node-sync-351', label)

    def test_sanitize_aws_batch_job_name(self):
        self.assertEqual('GCF_000001405-38_top_level', sanitize_aws_batch_job_name('GCF_000001405.38_top_level '))

    def test_sanitize_aws_user_name(self):
        self.assertEqual('user-name', sanitize_aws_batch_job_name('user.name'))

    def test_sanitize_gcp_user_name(self):
        self.assertEqual('user-name', sanitize_gcp_labels('user.name'))

@patch(target='elastic_blast.elb_config.get_db_metadata', new=MagicMock(return_value=DB_METADATA))
def create_config_for_db(dbname):
    """Create minimal config for a database name"""
    return ElasticBlastConfig(gcp_project = 'test-gcp-project',
                              gcp_region = 'test-gcp-region',
                              gcp_zone = 'test-gcp-zone',
                              program = 'blastn',
                              db = dbname,
                              queries = 'test-queries.fa',
                              results = 'gs://test-bucket',
                              task = ElbCommand.SUBMIT)


def test_safe_exec_run(mocker):
    """Test that safe_exec calls subprocess.run with check=True"""
    import subprocess

    cmd = 'some command line'.split()
    mocker.patch('subprocess.run')
    safe_exec(cmd)
    # test subprocess.run is called with check=True
    subprocess.run.assert_called_with(cmd, check=True, stdout=-1, stderr=-1)


@patch(target='elastic_blast.elb_config.get_db_metadata', new=MagicMock(return_value=DB_METADATA))
@patch(target='elastic_blast.elb_config.aws_get_machine_properties', new=MagicMock(return_value=InstanceProperties(32, 120)))
@patch(target='elastic_blast.tuner.aws_get_machine_properties', new=MagicMock(return_value=InstanceProperties(32, 120)))
def test_convert_labels_to_aws_tags(gke_mock):
    cfg = ElasticBlastConfig(aws_region = 'test-region',
                             program = 'blastn',
                             db = 'testdb',
                             queries = 'test-queries.fa',
                             results = 's3://some.bucket.with_s0me-interesting-name-end',
                             cluster_name = 'some-cluster-name',
                             task = ElbCommand.SUBMIT)

    labels = cfg.cluster.labels
    tags = convert_labels_to_aws_tags(labels)

    assert(isinstance(tags, list))
    t = {}
    for i in tags:
        k, v = i.values()
        t[k] = v
    assert('Project' in t.keys())
    assert('billingcode' in t.keys())
    assert('Name' in t.keys())
    assert('Owner' in t.keys())
    assert('results' in t.keys())
    assert(t['results'] == 's3://some.bucket.with_s0me-interesting-name-end')


def test_disk_size_conversions():
    rv = convert_disk_size_to_gb('100G')
    assert(rv == 100)
    rv = convert_disk_size_to_gb('50')
    assert(rv == 50)
    rv = convert_disk_size_to_gb('2.5T')
    assert(rv == 2500)
    rv = convert_disk_size_to_gb('500m')
    assert(rv == 1)
    rv = convert_disk_size_to_gb('1500m')
    assert(rv == 1)
    rv = convert_disk_size_to_gb('0.5G')
    assert(rv == 1)


def test_memory_conversions():
    rv = convert_memory_to_mb('100G')
    assert(rv == 100000)
    rv = convert_memory_to_mb('50')
    assert(rv == 50000)
    rv = convert_memory_to_mb('2.5T')
    assert(rv == 2500000)
    rv = convert_memory_to_mb('500m')
    assert(rv == 500)
    rv = convert_memory_to_mb('1500m')
    assert(rv == 1500)
    rv = convert_memory_to_mb('0.5G')
    assert(rv == 500)


def test_validate_gcp_string():
    """Test GCP id validation"""
    # correct string
    validate_gcp_string('abc_123-')

    # incorrect strings
    incorrect_strings = ['a string with spaces',
                         'UPPERCASE',
                         'illegal-character-:',
                         'illigal-character-.',
                         'illigal-character-?',
                         'illigal-character-!',
                         '']

    for s in incorrect_strings:
        with pytest.raises(ValueError):
            validate_gcp_string(s)


def test_validate_gcp_disk_name():
    """Test GCP disk name validation"""
    # correct string
    validate_gcp_disk_name('gke-some-name-1234455677')

    # incorrect strings
    incorrect_strings = ['a string with spaces',
                         'UPPERCASE',
                         'illegal-character-:',
                         'illigal-character-.',
                         'illigal-character-?',
                         'illigal-character-_',
                         '']

    for s in incorrect_strings:
        with pytest.raises(ValueError):
            validate_gcp_disk_name(s)


def test_cleanup_stage_failed():
    """Test that a failed cleanup stage does not stop the cleanup"""
    error_message = 'Stage failed'

    def failed_stage():
        """A failed cleanup stage"""
        raise util.UserReportError(255, error_message)

    def normal_stage(counter):
        """A normal cleanup stage"""
        counter[0] += 1

    counter = [0]

    cleanup_stack = []
    cleanup_stack.append(lambda: normal_stage(counter))
    cleanup_stack.append(failed_stage)
    cleanup_stack.append(lambda: normal_stage(counter))

    messages = util.clean_up(cleanup_stack)
    # test that both normal stages were executed
    assert counter[0] == 2
    # test that the error messaged generated by th failed stage was retrieved
    assert messages
    assert error_message in messages


def test_cleanup_keyboard_interrupt():
    """Test that an interrupted stage is retried"""
    class InterruptedStage:
        """Clenaup stage with a state"""

        def __init__(self):
            self.iterations = 0

        def cleanup_stage(self, counter):
            """Cleanup stage interrupted once"""
            self.iterations += 1
            # interrupt only once
            if self.iterations < 2:
                raise KeyboardInterrupt()
            counter[0] += 1

    def normal_stage(counter):
        """A normal cleanup stage"""
        counter[0] += 1

    counter = [0]
    interrupted_stage = InterruptedStage()

    cleanup_stack = []
    cleanup_stack.append(lambda: normal_stage(counter))
    cleanup_stack.append(lambda: interrupted_stage.cleanup_stage(counter))
    cleanup_stack.append(lambda: normal_stage(counter))

    util.clean_up(cleanup_stack)
    # test that all stages were executed
    assert counter[0] == 3
    # test that the interrupted stage was attempted twice
    assert interrupted_stage.iterations == 2


def test_get_blastdb_info(mocker):
    DB_BUCKET = 'gs://test-bucket'
    DB_NAME = 'test_db'
    DB_LABEL = 'test-db'
    DB = f'{DB_BUCKET}/{DB_NAME}'
    response = DB_NAME+'tar.gz'

    def safe_exec_gsutil_ls(cmd):
        """Mocked util.safe_exec function that simulates gsutil ls"""
        if cmd != f'gsutil ls {DB}.*':
            raise ValueError(f'Bad gsutil command line: "{cmd}"')
        return MockedCompletedProcess(response)

    mocker.patch('elastic_blast.util.safe_exec', side_effect=safe_exec_gsutil_ls)

    # tar.gz file, db_path should explicitely mention it
    db, db_path, k8sdblabel = util.get_blastdb_info(DB)
    assert(db_path == DB+'.tar.gz')
    assert(k8sdblabel == DB_LABEL)
    print(db, db_path, k8sdblabel)

    # no tar.gz file, db_path should have .*
    response = DB_NAME+'tar.gz.md5'
    db, db_path, k8sdblabel = util.get_blastdb_info(DB)
    assert(db_path == DB+'.*')
    assert(k8sdblabel == DB_LABEL)
    print(db, db_path, k8sdblabel)

    # tar.gz file, db_path should explicitely mention it
    response = DB_NAME+'tar.gz'+'\n'+DB_NAME+'.ndb'
    db, db_path, k8sdblabel = util.get_blastdb_info(DB)
    assert(db_path == DB+'.tar.gz')
    assert(k8sdblabel == DB_LABEL)
    print(db, db_path, k8sdblabel)

    # empty result, should throw an exception
    response = ''
    with pytest.raises(ValueError):
        util.get_blastdb_info(DB)

    # error executing gsutil, should throw an exception
    def safe_exec_gsutil_ls_exception(cmd):
        """Mocked util.safe_exec function that simulates gsutil rm"""
        raise SafeExecError(1, 'CommandException: One or more URLs matched no objects.')
    mocker.patch('elastic_blast.util.safe_exec', side_effect=safe_exec_gsutil_ls_exception)
    with pytest.raises(ValueError):
        util.get_blastdb_info(DB)
