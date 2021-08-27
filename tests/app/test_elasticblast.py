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
Application tests for elastic-blast

Author: Greg Boratyn boratyng@ncbi.nlm.nih.gov
"""

import subprocess
import os
import tempfile
import configparser
import signal
import time
import io
import re
from typing import List
from tempfile import TemporaryDirectory, NamedTemporaryFile
from unittest.mock import patch, MagicMock
import contextlib
import argparse
from elastic_blast import constants
from elastic_blast.util import safe_exec, UserReportError
from elastic_blast.base import InstanceProperties
from tests.utils import gke_mock
from tests.utils import MockedCompletedProcess
# TODO: refactor bin/elastic-blast to a sub-module inside the elastic_blast module
from .elastic_blast_app import main

import pytest


TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
SUBCOMMANDS = ['submit', 'status', 'delete']
INI_NO_BLASTDB = os.path.join(TEST_DATA_DIR, 'blastdb-notfound.ini')
INI_TOO_MANY_K8S_JOBS = os.path.join(TEST_DATA_DIR, 'too-many-k8s-jobs.ini')
INI_INVALID_AUTOSCALING = os.path.join(TEST_DATA_DIR, 'invalid-autoscaling-conf.ini')
INI_INCOMPLETE_MEM_LIMIT_OPTIMAL_MACHINE_TYPE_AWS = os.path.join(TEST_DATA_DIR, 'incomplete-mem-limit-optimal-aws-machine-type.ini')
INI_NO_NUM_CPUS_OPTIMAL_MACHINE_TYPE_AWS = os.path.join(TEST_DATA_DIR, 'no-num-cpus-optimal-aws-machine-type.ini')
INI_INVALID_MACHINE_TYPE_AWS = os.path.join(TEST_DATA_DIR, 'invalid-machine-type-aws.ini')
INI_INVALID_MACHINE_TYPE_GCP = os.path.join(TEST_DATA_DIR, 'invalid-machine-type-gcp.ini')
INI_INVALID_MEM_LIMIT = os.path.join(TEST_DATA_DIR, 'invalid-mem-req.ini')
INI_BLAST_OPT_NO_CLOSING_QUOTE = os.path.join(TEST_DATA_DIR, 'invalid-blast-opt-no-closing-quote.ini')
INI_VALID = os.path.join(TEST_DATA_DIR, 'good_conf.ini')
ELB_EXENAME = 'elastic-blast'


def run_elastic_blast(cmd: List[str], env=None) -> subprocess.CompletedProcess:
    """Run Elastic-BLAST application with given command line parameters.

    Arguments:
        cmd: A list of command line parameters

    Returns:
        subprocess.CompletedProcess object"""
    effective_env = dict(os.environ)
    if env:
        for key, value in env.items():
            effective_env[key] = str(value)
    p = subprocess.run([ELB_EXENAME] + cmd, check=False,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       env=effective_env)
    return p


## Mocked tests

def test_no_cmd_params(gke_mock):
    """Test that running elastic-blast with no parameters produces an error
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
    p = run_elastic_blast(f'submit --cfg {INI_TOO_MANY_K8S_JOBS}'.split(), env={'ELB_USE_CLIENT_SPLIT':1})
    run_elastic_blast(f'delete --cfg {INI_TOO_MANY_K8S_JOBS}'.split())
    print(p.stderr.decode())
    assert p.returncode == constants.INPUT_ERROR
    msg = p.stderr.decode()
    assert 'Traceback' not in msg
    assert 'Please increase the batch-len' in msg


def test_bad_num_nodes(gke_mock):
    """Test that providing negative number of nodes produces a correct error
    message and exit code"""
    p = run_elastic_blast('submit --num-nodes -1'.split())
    run_elastic_blast('delete --num-nodes -1'.split())
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
    run_elastic_blast(f'delete --cfg {INI_INVALID_MACHINE_TYPE_GCP}'.split())
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
    run_elastic_blast(f'delete --cfg {INI_INVALID_MACHINE_TYPE_AWS}'.split())
    assert p.returncode == constants.INPUT_ERROR
    msg = p.stderr.decode()
    assert 'Traceback' not in msg
    assert 'ERROR' in msg
    assert 'Invalid AWS machine type' in msg


@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='No credentials in TC unit tests')
def test_invalid_optimal_machine_type_aws_incomplete_mem_limit(gke_mock):
    """Test that providing a machine type 'optimal' with incomplete
    configuration produces a correct error message and exit code"""
    p = run_elastic_blast(f'submit --cfg {INI_INCOMPLETE_MEM_LIMIT_OPTIMAL_MACHINE_TYPE_AWS}'.split())
    run_elastic_blast(f'delete --cfg {INI_INCOMPLETE_MEM_LIMIT_OPTIMAL_MACHINE_TYPE_AWS}'.split())
    assert p.returncode == constants.INPUT_ERROR
    msg = p.stderr.decode()
    assert 'Traceback' not in msg
    assert 'ERROR' in msg
    assert 'requires configuring blast.mem-limit' in msg


@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='No credentials in TC unit tests')
def test_optimal_machine_type_aws_no_num_cpus(gke_mock):
    """Test that providing a machine type 'optimal' without num-cpus works fine"""
    p = run_elastic_blast(f'submit --cfg {INI_NO_NUM_CPUS_OPTIMAL_MACHINE_TYPE_AWS}'.split())
    run_elastic_blast(f'delete --cfg {INI_NO_NUM_CPUS_OPTIMAL_MACHINE_TYPE_AWS}'.split())
    msg = p.stderr.decode()
    assert 'Traceback' not in msg
    assert 'ERROR' not in msg
    assert p.returncode == 0


def test_invalid_mem_limit(gke_mock):
    """Test that providing an invalid memory limit configuration produces a correct error
    message and exit code"""
    p = run_elastic_blast(f'submit --cfg {INI_INVALID_MEM_LIMIT}'.split())
    run_elastic_blast(f'delete --cfg {INI_INVALID_MEM_LIMIT}'.split())
    msg = p.stderr.decode()
    assert p.returncode == constants.INPUT_ERROR
    assert 'Traceback' not in msg
    assert 'ERROR' in msg
    assert ' has an invalid value:' in msg


# FIXME: This is sad, but config doesn't take into account dry run, so it tries to 
# get_instance_props - see elb_config.py:360
@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='No credentials in TC unit tests')
def test_invalid_blast_option_no_closing_quote(gke_mock):
    """Test that providing an invalid memory limit configuration produces a correct error
    message and exit code"""
    p = run_elastic_blast(f'submit --dry-run --cfg {INI_BLAST_OPT_NO_CLOSING_QUOTE}'.split())
    msg = p.stderr.decode()
    assert p.returncode == constants.INPUT_ERROR
    assert 'Traceback' not in msg
    assert 'ERROR' in msg
    assert 'Incorrect BLAST options: No closing quotation' in msg


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
    run_elastic_blast(['delete', '--cfg', os.path.join(TEST_DATA_DIR, 'good_conf.ini')])
    assert p.returncode == constants.INPUT_ERROR
    msg = p.stderr.decode()
    assert 'Traceback' not in msg
    assert 'Query input invalid-file is not readable or does not exist' in msg


def test_wrong_results_bucket(gke_mock):
    p = run_elastic_blast(['submit', '--query', os.path.join(TEST_DATA_DIR, 'query.fa'), '--db', 'nt', '--cfg', os.path.join(TEST_DATA_DIR, 'bad_bucket_conf.ini')])
    run_elastic_blast(['delete', 'nt', '--cfg', os.path.join(TEST_DATA_DIR, 'bad_bucket_conf.ini')])
    msg = p.stderr.decode()
    print(msg)
    assert p.returncode == constants.PERMISSIONS_ERROR
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
    run_elastic_blast(f'delete --cfg {INI_NO_BLASTDB}'.split())
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
    p = safe_exec('which elastic-blast')
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
    p = safe_exec('which gsutil')
    gsutil_exepath = p.stdout.decode()
    spy_file = os.path.join(os.getcwd(), 'spy_file.txt')

    gcloud = f"""\
#!/bin/sh
if [ "${1} ${2} ${3}" == "container clusters list" ]; then
echo STOPPING
else
echo `{gcloud_exepath} $@`
fi"""
    gsutil = f"""\
#!/bin/sh
if [ "${1} ${2}" == "-q stat" ]; then
exit 1
else
echo `{gsutil_exepath} $@`
fi"""
    env = dict(os.environ)
    with TemporaryDirectory() as d:
        env['PATH'] = d + ':' + env['PATH']
        gcloud_fname = os.path.join(d, 'gcloud')
        with open(gcloud_fname, 'wt') as f:
            f.write(gcloud)
        gsutil_fname = os.path.join(d, 'gsutil')
        with open(gsutil_fname, 'wt') as f:
            f.write(gsutil)
        import stat
        os.chmod(gcloud_fname, stat.S_IRWXU)
        os.chmod(gsutil_fname, stat.S_IRWXU)

        fn_config = os.path.join(TEST_DATA_DIR, 'cluster-error.ini')

        # elastic-blast delete --cfg tests/app/data/cluster-error.ini --logfile stderr
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

        # elastic-blast submit --cfg tests/app/data/cluster-error.ini --logfile stderr
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
        assert 'delete the previous ElasticBLAST search' in msg

        # elastic-blast status --cfg tests/app/data/cluster-error.ini --loglevel DEBUG --logfile stderr
        p = subprocess.run([ELB_EXENAME, 'status',
            '--cfg', fn_config,
            '--logfile', 'stderr'],
            env=env, stderr=subprocess.PIPE)
        assert p.returncode == constants.CLUSTER_ERROR
        msg = p.stderr.decode()
        print(msg)
        assert 'Traceback' not in msg
    run_elastic_blast(['delete', '--cfg', fn_config])

# Failing tests for not implemented error codes
# TODO: Update the call and modify running condition when implemented

@pytest.mark.skip(reason="Not yet implemented return code")
def test_blast_engine_error():
    p = run_elastic_blast(f'submit --cfg blast_engine_fail.ini'.split())
    run_elastic_blast(f'delete --cfg blast_engine_fail.ini'.split())
    assert p.returncode == constants.BLAST_ENGINE_ERROR
    msg = p.stderr.decode()
    print(msg)
    assert 'Traceback' not in msg


@pytest.mark.skip(reason="Not yet implemented return code")
def test_blast_out_of_memory_error():
    p = run_elastic_blast(f'submit --cfg out_of_memory.ini'.split())
    run_elastic_blast(f'delete --cfg out_of_memory.ini'.split())
    assert p.returncode == constants.OUT_OF_MEMORY_ERROR
    msg = p.stderr.decode()
    print(msg)
    assert 'Traceback' not in msg


@pytest.mark.skip(reason="Not yet implemented return code")
def test_blast_timeout_error():
    p = run_elastic_blast(f'submit --cfg timeout.ini'.split())
    run_elastic_blast(f'delete --cfg timeout.ini'.split())
    assert p.returncode == constants.TIMEOUT_ERROR
    msg = p.stderr.decode()
    print(msg)
    assert 'Traceback' not in msg


@patch(target='elastic_blast.elb_config.aws_get_machine_properties', new=MagicMock(return_value=InstanceProperties(4, 32)))
def test_memory_limit_too_large():
    """Test that selecting memory limit that exceeds memory available on a
    selected instance type results in the appropriate error code and message."""

    conf = """[cloud-provider]
aws-region = us-east-1

[cluster]
machine-type = m5.large

[blast]
program = blastp
db = some-db
queries = some-queries
mem-limit = 900G
results = s3://some-bucket
"""

    with NamedTemporaryFile() as f:
        f.write(conf.encode())
        f.flush()
        f.seek(0)
        
        # mock AgrumentParser.parse_args() to create an argparse.Namespace
        # object that fakes command line parameters
        with patch.object(argparse.ArgumentParser, 'parse_args',
                          return_value=argparse.Namespace(subcommand='submit',
                                                          cfg=f.name,
                                                          aws_region=None,
                                                          gcp_project=None,
                                                          gcp_region=None,
                                                          gcp_zone=None,
                                                          blast_opts=[],
                                                          db=None,
                                                          dry_run=False,
                                                          logfile='stderr',
                                                          loglevel='ERROR',
                                                          num_nodes=None,
                                                          program=None,
                                                          query=None,
                                                          results=None,
                                                          run_label=None)):
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                returncode = main()
            assert returncode == constants.INPUT_ERROR
            assert re.search(r'Memory limit [\w"]* exceeds memory available on the selected machine type', stderr.getvalue())


@patch(target='elastic_blast.elb_config.aws_get_machine_properties', new=MagicMock(return_value=InstanceProperties(4, 32)))
def test_misplaced_config_parameter():
    """Test that using a config parameter in a wrong section results in an
    appropriate error code and message"""

    # num-cpus should be in [cluster]
    conf = """[cloud-provider]
aws-region = us-east-1

[cluster]
machine-type = m5.large

[blast]
num-cpus = 8
program = blastp
db = some-db
queries = some-queries
mem-limit = 900G
results = s3://some-bucket
"""

    with NamedTemporaryFile() as f:
        f.write(conf.encode())
        f.flush()
        f.seek(0)

        # mock ArgumentParser.parse_args() to create an argparse.Namespace
        # object that fakes command line parameters
        with patch.object(argparse.ArgumentParser, 'parse_args',
                          return_value=argparse.Namespace(subcommand='submit',
                                                          cfg=f.name,
                                                          aws_region=None,
                                                          gcp_project=None,
                                                          gcp_region=None,
                                                          gcp_zone=None,
                                                          blast_opts=[],
                                                          db=None,
                                                          dry_run=False,
                                                          logfile='stderr',
                                                          loglevel='ERROR',
                                                          num_nodes=None,
                                                          program=None,
                                                          query=None,
                                                          results=None,
                                                          run_label=None)):
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                returncode = main()
            print(stderr.getvalue())
            assert returncode == constants.INPUT_ERROR
            assert re.search(r'Unrecognized configuration parameter [\w"-]* in section [\w"-]*', stderr.getvalue())
