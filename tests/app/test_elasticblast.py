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
Application tests for elastic-blast.py

Author: Greg Boratyn boratyng@ncbi.nlm.nih.gov
"""

import subprocess
import os
import tempfile
import configparser
import signal
import time
from typing import List
from tempfile import TemporaryDirectory
from elb import constants
from elb.util import safe_exec
from tests.utils import gke_mock
from tests.utils import MockedCompletedProcess

import pytest


TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
SUBCOMMANDS = ['submit', 'status', 'delete']
INI_NO_BLASTDB = os.path.join(TEST_DATA_DIR, 'blastdb-notfound.ini')
INI_TOO_MANY_K8S_JOBS = os.path.join(TEST_DATA_DIR, 'too-many-k8s-jobs.ini')
INI_INVALID_AUTOSCALING = os.path.join(TEST_DATA_DIR, 'invalid-autoscaling-conf.ini')
INI_INCOMPLETE_MEM_LIMIT_OPTIMAL_MACHINE_TYPE_AWS = os.path.join(TEST_DATA_DIR, 'incomplete-mem-limit-optimal-aws-machine-type.ini')
INI_INCOMPLETE_NUM_CPUS_OPTIMAL_MACHINE_TYPE_AWS = os.path.join(TEST_DATA_DIR, 'incomplete-num-cpus-optimal-aws-machine-type.ini')
INI_INVALID_MACHINE_TYPE_AWS = os.path.join(TEST_DATA_DIR, 'invalid-machine-type-aws.ini')
INI_INVALID_MACHINE_TYPE_GCP = os.path.join(TEST_DATA_DIR, 'invalid-machine-type-gcp.ini')
INI_INVALID_MEM_LIMIT = os.path.join(TEST_DATA_DIR, 'invalid-mem-req.ini')
INI_VALID = os.path.join(TEST_DATA_DIR, 'good_conf.ini')
ELB_EXENAME = 'elastic-blast.py'


def run_elastic_blast(cmd: List[str]) -> subprocess.CompletedProcess:
    """Run Elastic-BLAST application with given command line parameters.

    Arguments:
        cmd: A list of command line parameters

    Returns:
        subprocess.CompletedProcess object"""
    p = subprocess.run([ELB_EXENAME] + cmd, check=False,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p


## Mocked tests

def test_no_cmd_params(gke_mock):
    """Test that running elastic-blast.py with no parameters produces an error
    message, appropriate exit code, and no python tracepack information"""
    p = run_elastic_blast([])
    msg = p.stderr.decode()
    assert p.returncode == constants.INPUT_ERROR
    assert 'Traceback' not in msg
    assert 'error' in msg or 'ERROR' in msg
    for subcommand in SUBCOMMANDS:
        assert subcommand in msg


def test_no_cfg(gke_mock):
    """Test that running elastic-blast with no cfg parameter produces an error
    message, appropriate exit code, and no python traceback information"""
    for subcommand in SUBCOMMANDS:
        print(subcommand)
        p = run_elastic_blast([subcommand])
        msg = p.stderr.decode()
        print(msg)
        assert p.returncode == constants.INPUT_ERROR
        assert 'Traceback' not in msg
        assert 'error' in msg or 'ERROR' in msg
        assert '--cfg' in msg
        assert 'environment variables' in msg


def test_cfg_file_no_found(gke_mock):
    """Test that missing cfg file produces an error message, appropriate exit
    code, and no python traceback information"""
    filename = 'some-non-existant-file'
    for subcommand in SUBCOMMANDS:
        p = run_elastic_blast([subcommand, '--cfg', filename])
        msg = p.stderr.decode()
        assert p.returncode == constants.INPUT_ERROR
        assert 'Traceback' not in msg
        assert 'error' in msg
        assert f'{filename} was not found' in msg


def test_unicode_args(gke_mock):
    """Test that arguments with Unicode letters are rejected"""
    filename = 'some-non-existant-file'
    # NB: in following line the argument --cfg has long dash instead of normal
    # which can't be processed by elastic-blast
    p = run_elastic_blast(['submit', '–-cfg', filename])
    msg = p.stderr.decode()
    assert p.returncode == constants.INPUT_ERROR
    assert 'Traceback' not in msg
    assert 'Command line has Unicode letters in argument' in msg
    assert "can't be processed" in msg


def test_too_many_k8s_jobs(gke_mock):
    """Test that providing a configuration that generates k8s jobs that exceed the limit produces 
    a sensible error message and exit code.
    """
    p = run_elastic_blast(f'submit --cfg {INI_TOO_MANY_K8S_JOBS}'.split())
    print(p.stderr.decode())
    assert p.returncode == constants.INPUT_ERROR
    msg = p.stderr.decode()
    assert 'Traceback' not in msg
    assert 'Please increase the batch-len' in msg


def test_bad_num_nodes(gke_mock):
    """Test that providing negative number of nodes produces a correct error
    message and exit code"""
    p = run_elastic_blast('submit --num-nodes -1'.split())
    assert p.returncode == constants.INPUT_ERROR
    msg = p.stderr.decode()
    assert 'Traceback' not in msg
    assert 'error' in msg
    assert '-1' in msg
    assert 'not a positive integer' in msg


def test_invalid_machine_type_gcp(gke_mock):
    """Test that providing an invalid machine type produces a correct error
    message and exit code"""
    p = run_elastic_blast(f'submit --cfg {INI_INVALID_MACHINE_TYPE_GCP}'.split())
    msg = p.stderr.decode()
    assert p.returncode == constants.INPUT_ERROR
    assert 'Traceback' not in msg
    assert 'ERROR' in msg
    assert 'Invalid machine type' in msg
    #assert 'Invalid machine type' in msg  # this is an error from gcloud


@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='No credentials in TC unit tests')
def test_invalid_machine_type_aws(gke_mock):
    """Test that providing an invalid machine type produces a correct error
    message and exit code"""
    p = run_elastic_blast(f'submit --cfg {INI_INVALID_MACHINE_TYPE_AWS}'.split())
    assert p.returncode == constants.INPUT_ERROR
    msg = p.stderr.decode()
    assert 'Traceback' not in msg
    assert 'ERROR' in msg
    assert 'Invalid AWS machine type' in msg


@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='No credentials in TC unit tests')
def test_invalid_optimal_machine_type_aws_incomplete_mem_limit(gke_mock):
    """Test that providing a machine type 'optiomal' with incomplete
    configuration produces a correct error message and exit code"""
    p = run_elastic_blast(f'submit --cfg {INI_INCOMPLETE_MEM_LIMIT_OPTIMAL_MACHINE_TYPE_AWS}'.split())
    assert p.returncode == constants.INPUT_ERROR
    msg = p.stderr.decode()
    assert 'Traceback' not in msg
    assert 'ERROR' in msg
    assert 'requires configuring blast.mem-limit' in msg


@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='No credentials in TC unit tests')
def test_invalid_optimal_machine_type_aws_incomplete_num_cpus(gke_mock):
    """Test that providing a machine type 'optiomal' with incomplete
    configuration produces a correct error message and exit code"""
    p = run_elastic_blast(f'submit --cfg {INI_INCOMPLETE_NUM_CPUS_OPTIMAL_MACHINE_TYPE_AWS}'.split())
    assert p.returncode == constants.INPUT_ERROR
    msg = p.stderr.decode()
    assert 'Traceback' not in msg
    assert 'ERROR' in msg
    assert 'requires configuring cluster.num-cpus' in msg


def test_invalid_mem_limit(gke_mock):
    """Test that providing an invalid memory limit configuration produces a correct error
    message and exit code"""
    p = run_elastic_blast(f'submit --cfg {INI_INVALID_MEM_LIMIT}'.split())
    msg = p.stderr.decode()
    assert p.returncode == constants.INPUT_ERROR
    assert 'Traceback' not in msg
    assert 'ERROR' in msg
    assert ' has an invalid value:' in msg


def test_invalid_autoscaling_config(gke_mock):
    """Test that providing an invalid autoscaling configuration produces a correct error
    message and exit code"""
    p = run_elastic_blast(f'submit --cfg {INI_INVALID_AUTOSCALING}'.split())
    assert p.returncode == constants.INPUT_ERROR
    msg = p.stderr.decode()
    assert 'Traceback' not in msg
    assert 'ERROR' in msg
    assert 'Both min-nodes and max-nodes must be specified' in msg


def test_non_existent_option(gke_mock):
    """Test that providing a non-existent option produces a correct error
    message and exit code"""
    opt = '--option-that-does-not-exist'
    for subcommand in SUBCOMMANDS:
        p = run_elastic_blast([subcommand, opt])
        assert p.returncode == constants.INPUT_ERROR
        msg = p.stderr.decode()
        assert 'Traceback' not in msg
        assert 'error' in msg
        assert opt in msg
        assert 'unrecognized argument' in msg


def test_wrong_input_query(gke_mock):
    p = run_elastic_blast(['submit', '--query', 'invalid-file', '--db', 'nt', '--cfg', os.path.join(TEST_DATA_DIR, 'good_conf.ini')])
    assert p.returncode == constants.INPUT_ERROR
    msg = p.stderr.decode()
    assert 'Traceback' not in msg
    assert 'Query input invalid-file is not readable or does not exist' in msg


def test_wrong_results_bucket(gke_mock):
    p = run_elastic_blast(['submit', '--query', os.path.join(TEST_DATA_DIR, 'query.fa'), '--db', 'nt', '--cfg', os.path.join(TEST_DATA_DIR, 'bad_bucket_conf.ini')])
    assert p.returncode == constants.PERMISSIONS_ERROR
    msg = p.stderr.decode()
    assert 'Traceback' not in msg
    assert 'Cannot write into bucket gs://blast-db' in msg


def test_gcp_config_errors(gke_mock):
    """Test that errors in GCP config are reported"""
    cfg = configparser.ConfigParser()
    cfg[constants.CFG_CLOUD_PROVIDER] = {constants.CFG_CP_GCP_PROJECT: 'GCP-project',
                                         constants.CFG_CP_GCP_REGION: 'region # with comment',
                                         constants.CFG_CP_GCP_ZONE: 'us-east$-a'}
    cfg[constants.CFG_BLAST] = { constants.CFG_BLAST_RESULTS : 'gs://elasticblast-tomcat',
                                 constants.CFG_BLAST_PROGRAM: 'blastn',
                                 constants.CFG_BLAST_DB: 'some-db',
                                 constants.CFG_BLAST_QUERY: 'test-queries.fa',
                                 constants.CFG_BLAST_RESULTS: 'gs://elasticblast-tomcat'}


    for subcommand in SUBCOMMANDS:
        with tempfile.NamedTemporaryFile('w') as cfg_file:
            cfg.write(cfg_file)
            cfg_file.flush()
            p = run_elastic_blast(f'{subcommand} --cfg {cfg_file.name}'.split())

        assert p.returncode == constants.INPUT_ERROR
        msg = p.stderr.decode()
        print(msg)
        assert '"gcp-project" has an invalid value' in msg
        assert '"gcp-region" has an invalid value' in msg
        assert '"gcp-zone" has an invalid value' in msg


def test_blastdb_error():
    p = run_elastic_blast(f'submit --cfg {INI_NO_BLASTDB}'.split())
    assert p.returncode == constants.BLASTDB_ERROR
    msg = p.stderr.decode()
    print(msg)
    assert 'Traceback' not in msg
    assert 'BLAST database' in msg
    assert 'not found' in msg


@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='This test is flaky in TC')
def test_interrupt_error():
    p = subprocess.Popen([ELB_EXENAME, 'submit',
        '--query', os.path.join(TEST_DATA_DIR, 'query.fa'),
        '--cfg', os.path.join(TEST_DATA_DIR, 'good_conf.ini'),
        '--dry-run'],
        stderr=subprocess.PIPE)
    # it takes arund 0.3 seconds to establish the process
    # and 3.5 seconds to run to completion with dry-run,
    # so 1 second wait is well within these safety margins
    time.sleep(2)
    p.send_signal(signal.SIGINT)
    p.wait()
    print(p.stderr.read().decode())
    assert p.returncode == constants.INTERRUPT_ERROR
    msg = p.stderr.read().decode()
    assert 'Traceback' not in msg


def test_dependency_error():
    p = safe_exec('which elastic-blast.py')
    exepath = p.stdout.decode()
    newpath = os.path.dirname(exepath)
    orig_exe_path = exepath
    # Check gcloud missing
    p = subprocess.run([ELB_EXENAME, 'submit', '--cfg', INI_VALID, '--dry-run'], env={'PATH': newpath}, stderr=subprocess.PIPE)
    assert p.returncode == constants.DEPENDENCY_ERROR
    msg = p.stderr.decode()
    print(msg)
    assert 'Traceback' not in msg
    assert "Required pre-requisite 'gcloud' doesn't work" in msg
    # Eliminate gcloud, check kubectl missing
    p = safe_exec('which gcloud')
    exepath = p.stdout.decode()
    newpath += ':' + os.path.dirname(exepath)
    p = subprocess.run([ELB_EXENAME, 'submit', '--cfg', INI_VALID, '--dry-run'], env={'PATH': newpath}, stderr=subprocess.PIPE)
    assert p.returncode == constants.DEPENDENCY_ERROR
    msg = p.stderr.decode()
    print(msg)
    assert 'Traceback' not in msg
    assert "Required pre-requisite 'kubectl' doesn't work" in msg
    from tempfile import TemporaryDirectory
    # Provide non-executable gcloud file
    with TemporaryDirectory() as d:
        safe_exec(f'touch {d}/gcloud')
        newpath = os.path.dirname(orig_exe_path) + ':' + d
        p = subprocess.run([ELB_EXENAME, 'submit', '--cfg', INI_VALID, '--dry-run'], env={'PATH': newpath}, stderr=subprocess.PIPE)
        assert p.returncode == constants.DEPENDENCY_ERROR
        msg = p.stderr.decode()
        print(msg)
        assert 'Traceback' not in msg
        assert "Required pre-requisite 'gcloud' doesn't work" in msg


# Disabled until EB-726 is fixed
#def test_cleanup_gsutil_error():
#    p = subprocess.run([ELB_EXENAME, 'delete',
#        '--cfg', os.path.join(TEST_DATA_DIR, 'cleanup-error.ini')],
#        stderr=subprocess.PIPE)
#    assert p.returncode == 0
#    msg = p.stderr.decode()
#    print(msg)
#    assert 'Traceback' not in msg
#    assert 'WARNING' in msg
#    assert 'could not be removed' in msg


def test_cluster_error():
    p = safe_exec('which gcloud')
    gcloud_exepath = p.stdout.decode()
    spy_file = os.path.join(os.getcwd(), 'spy_file.txt')

    gcloud = f"""\
#!/bin/sh
if [ "${1} ${2} ${3}" == "container clusters list" ]; then
echo STOPPING
else
echo `{gcloud_exepath} $@`
fi"""
    env = dict(os.environ)
    with TemporaryDirectory() as d:
        env['PATH'] = d + ':' + env['PATH']
        gcloud_fname = os.path.join(d, 'gcloud')
        with open(gcloud_fname, 'wt') as f:
            f.write(gcloud)
        import stat
        os.chmod(gcloud_fname, stat.S_IRWXU)

        fn_config = os.path.join(TEST_DATA_DIR, 'cluster-error.ini')

        # elastic-blast.py delete --cfg tests/app/data/cluster-error.ini --logfile stderr
        p = subprocess.run([ELB_EXENAME, 'delete',
            '--cfg', fn_config,
            '--logfile', 'stderr'],
            env=env, stderr=subprocess.PIPE)
        msg = p.stderr.decode()
        print(msg)
        assert p.returncode == constants.CLUSTER_ERROR
        assert 'Traceback' not in msg
        assert 'ERROR' in msg
        assert 'is already being deleted' in msg

        # elastic-blast.py submit --cfg tests/app/data/cluster-error.ini --logfile stderr
        p = subprocess.run([ELB_EXENAME, 'submit',
            '--cfg', fn_config,
            '--logfile', 'stderr'],
            env=env, stderr=subprocess.PIPE)
        assert p.returncode == constants.CLUSTER_ERROR
        msg = p.stderr.decode()
        print(msg)
        assert 'Traceback' not in msg
        assert 'Previous instance of cluster' in msg
        assert 'is still STOPPING' in msg

        # elastic-blast.py status --cfg tests/app/data/cluster-error.ini --loglevel DEBUG --logfile stderr
        p = subprocess.run([ELB_EXENAME, 'status',
            '--cfg', fn_config,
            '--logfile', 'stderr'],
            env=env, stderr=subprocess.PIPE)
        assert p.returncode == constants.CLUSTER_ERROR
        msg = p.stderr.decode()
        print(msg)
        assert 'Traceback' not in msg

# Failing tests for not implemented error codes
# TODO: Update the call and modify running condition when implemented

@pytest.mark.skip(reason="Not yet implemented return code")
def test_blast_engine_error():
    p = run_elastic_blast(f'submit --cfg blast_engine_fail.ini'.split())
    assert p.returncode == constants.BLAST_ENGINE_ERROR
    msg = p.stderr.decode()
    print(msg)
    assert 'Traceback' not in msg


@pytest.mark.skip(reason="Not yet implemented return code")
def test_blast_out_of_memory_error():
    p = run_elastic_blast(f'submit --cfg out_of_memory.ini'.split())
    assert p.returncode == constants.OUT_OF_MEMORY_ERROR
    msg = p.stderr.decode()
    print(msg)
    assert 'Traceback' not in msg


@pytest.mark.skip(reason="Not yet implemented return code")
def test_blast_timeout_error():
    p = run_elastic_blast(f'submit --cfg timeout.ini'.split())
    assert p.returncode == constants.TIMEOUT_ERROR
    msg = p.stderr.decode()
    print(msg)
    assert 'Traceback' not in msg
