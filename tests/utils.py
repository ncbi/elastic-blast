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
tests/utils.py - Utility functions for testing

Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
        Greg Boratyn (boratyng@nbci.nlm.nih.gov)
Created: Wed 29 Apr 2020 06:50:51 PM EDT
"""

import json
from elastic_blast.util import SafeExecError
from elastic_blast import config
from elastic_blast.elb_config import ElasticBlastConfig
from elastic_blast.constants import ElbCommand
from typing import Optional, List, Union
import pytest


class MockedCompletedProcess:
    """Fake subprocess.CompletedProcess class used for mocking return
    value of subprocess.run() to emulate command line calls."""

    def __init__(self, stdout: Optional[str] = None,
                 stderr: Optional[str] = None,
                 returncode: int = 0):
        """Class constructor"""
        self.stdout: Optional[bytes] = str.encode(stdout) if not stdout is None else None
        self.stderr: Optional[bytes] = str.encode(stderr) if not stderr is None else None
        self.returncode: int = returncode


@pytest.fixture
def gke_mock(mocker):
    """Fixtire function that replaces util.safe_exec with mocked_safe_exec"""

    mock = GKEMock()

    # we need gcp.safe_exec instead of util.safe exec here, because
    # safe_exec is imported in gcp.py with 'from util import safe_exec'
    # and safe_exec in gcp is seen as local, python is funny this way
    mocker.patch('elastic_blast.gcp.safe_exec', side_effect=mock.mocked_safe_exec)
    mocker.patch('elastic_blast.kubernetes.safe_exec', side_effect=mock.mocked_safe_exec)
    mocker.patch('elastic_blast.status.safe_exec', side_effect=mock.mocked_safe_exec)
    mocker.patch('elastic_blast.util.safe_exec', side_effect=mock.mocked_safe_exec)
    yield mock
    del mock


# constants used in mocked_safe_exec
GCP_PROJECT = 'mocked-gcp-project'
GCP_ZONE = 'mocked-gcp-zone'
GCP_REGION = 'mocked-gcp-region'
GCP_DISKS = ['mock-gcp-disk-1', 'mock-gcp-disk-2']
GKE_PVS = ['disk-1', 'disk-2']
GKE_CLUSTERS = ['mock-gke-cluster-1', 'mock-gke-cluster-2']
K8S_JOBS = ['k8s-job-1', 'k8s-job-2', 'k8s-job-3', 'k8s-job-4']
K8S_JOB_STATUS = ['Failed', 'Succeeded', 'Pending', 'Running']
BLASTDB = 'mocked_blastdb'


def get_mocked_config() -> ElasticBlastConfig:
    """Generate config for mocked gcloud and kubeclt"""
    cfg = ElasticBlastConfig(gcp_project = GCP_PROJECT,
                             gcp_region = GCP_REGION,
                             gcp_zone = GCP_ZONE,
                             program = 'blastn',
                             db = 'test-db',
                             queries = 'test-queries.fa',
                             results = 'gs://elasticblast-blastadm',
                             task = ElbCommand.SUBMIT)

    cfg.cluster.name = GKE_CLUSTERS[0]

    return cfg


def mocked_safe_exec(cmd: Union[List[str], str]) -> MockedCompletedProcess:
    """Substitute for util.safe_exec function that calls command line gcloud
    or kubectl. It emulates gcloud or kubectl stdout for recognized parameters.

    Arguments:
        cmd: Command line as a list

    Returns:
        MockedCompletedProcess object that simulates subprocess.CompletedProcess

    Raises:
        ValueError for unexpected command line"""

    if isinstance(cmd, str):
        cmd = cmd.split()

    if not isinstance(cmd, list):
        raise ValueError('Argument to mocked_safe_exec must be a list or string')

    # get GCP project
    if ' '.join(cmd) == 'gcloud config get-value project':
        return MockedCompletedProcess(GCP_PROJECT)

    # set GCP project
    elif ' '.join(cmd[:-1]) == 'gcloud config set project':
        return MockedCompletedProcess()

    # get a list of presistent disks
    elif ' '.join(cmd).startswith('gcloud compute disks list --format json'):
        result = []
        for d in GCP_DISKS:
            result.append({'name': d})
        return MockedCompletedProcess(json.dumps(result))

    # delete a persistent disk
    elif ' '.join(cmd).startswith('gcloud compute disks delete'):
        return MockedCompletedProcess()

    # GKE cluster status
    elif ' '.join(cmd).startswith('gcloud container clusters list --format=value(status) --filter name'):
        return MockedCompletedProcess('RUNNING\n')

    # list GKE clusters
    elif ' '.join(cmd).startswith('gcloud container clusters list --format json'):
        result = []
        for i in GKE_CLUSTERS:
            result.append({'name': i})
        return MockedCompletedProcess(json.dumps(result))

    # get GKE cluster credentials
    elif ' '.join(cmd).startswith('gcloud container clusters get-credentials'):
        return MockedCompletedProcess()

    # delete cluster
    elif ' '.join(cmd).startswith('gcloud container clusters delete'):
        return MockedCompletedProcess()

    # check GCP APIs
    elif ' '.join(cmd).startswith('gcloud services '):
        return MockedCompletedProcess()

    # get persistent disks
    elif ' '.join(cmd) == 'kubectl get pv -o json':
        result = {'items': []}  # type: ignore
        for i in GCP_DISKS:
            result['items'].append({'spec': {'gcePersistentDisk': {'pdName': i}}})  # type: ignore
        return MockedCompletedProcess(json.dumps(result))

    # get kubernetes jobs
    elif ' '.join(cmd).startswith('kubectl get jobs -o json'):
        result = {'items': []}
        for i in K8S_JOBS:
            result['items'].append({'metadata': {'name': i}})
        return MockedCompletedProcess(json.dumps(result))

    # get kubernetes job status with one pod deleted due to failure
    elif ' '.join(cmd).startswith('kubectl get pods -o custom-columns=STATUS'):
        return MockedCompletedProcess('\n'.join(['STATUS'] + ['Running' for i in K8S_JOB_STATUS if i == 'Running']))

    elif ' '.join(cmd).startswith('kubectl get jobs -o custom-columns=STATUS'):
        switcher = {'Failed': 'Failed',
                    'Succeeded': 'Complete',
                    'Running': '<none>',
                    'Pending': '<none>'}
        return MockedCompletedProcess('\n'.join(['STATUS'] + [switcher[i] for i in K8S_JOB_STATUS]))

    # delete all jobs
    elif ' '.join(cmd) == 'kubectl delete jobs --all':
       return MockedCompletedProcess('\n'.join(['deleted ' + i for i in K8S_JOBS]) + '\n')

    # delete all pvcs
    elif ' '.join(cmd) == 'kubectl delete pvc --all':
        return MockedCompletedProcess('\n'.join(['deleted ' + i for i in GKE_PVS]) + '\n')

    # delete all pvs
    elif ' '.join(cmd) == 'kubectl delete pv --all':
        return MockedCompletedProcess('\n')

    # check if kubernetes cluster is alive
    elif ' '.join(cmd) == 'kubectl version --short':
        return MockedCompletedProcess()

    # list BLAST databases available in the cloud
    elif ' '.join(cmd).startswith('update_blastdb.pl') and '--showall' in cmd:
        return MockedCompletedProcess(f'{BLASTDB}\tTitle of {BLASTDB}\t0.1\t2020-01-01')

    # Check the resource quota in GKE
    elif ' '.join(cmd).startswith('kubectl get resourcequota gke-resource-quotas'):
        return MockedCompletedProcess('10k')

    # Check whether a file exists in GCS
    elif ' '.join(cmd).startswith('gsutil -q stat'):
        return MockedCompletedProcess(stdout='',stderr='',returncode=1)

    # Check whether a file exists in GCS
    elif ' '.join(cmd).startswith('gsutil -q cat'):
        return MockedCompletedProcess(stdout='',stderr='',returncode=0)

    # raise ValueError for unrecognized command line
    else:
        raise ValueError(f'Unrecognized gcloud or kubectl command line: {cmd}')


class GKEMock:
    """Utility class for mocking util.safe_exec that with different
    results for the same parameters command line paramters."""
    allowed_options = ['no-cluster',
                       'kubectl-error']

    def __init__(self):
        """Class constructor"""
        self.options = list()
        self.disk_delete_called = False

    def set_options(self, options: List[str]) -> None:
        """Set optional mocked GKE behavior.

        Arguments:
            options: List of options, each must be one of GKEMock.allowed_options
        Raises:
            ValueError for unrecognized option"""
        self.options = options
        for opt in options:
            if opt not in GKEMock.allowed_options:
                raise ValueError(f'Unsupported GKEMock option: {opt}')

    def mocked_safe_exec(self, cmd):
        """Mocked util.safe_exec function"""

        if isinstance(cmd, list):
            cmd = ' '.join(cmd)

        # simulate manipulation of a non-existent GKE cluster
        if 'no-cluster' in self.options:
            if cmd.startswith('gcloud container clusters get-credentials') or \
                    cmd.startswith('gcloud container clusters delete') or \
                    cmd.startswith('kubectl'):
                raise SafeExecError(returncode=1,
                                    message='Mocked error: cluster does not exist')

        # any kubectl call fails
        if 'kubectl-error' in self.options:
            if cmd.startswith('kubectl'):
                raise SafeExecError(returncode=1,
                                    message='Mocked kubectl error')

        # report no disks after disk deletion was called
        if cmd.startswith('gcloud compute disks list') and self.disk_delete_called:
            return MockedCompletedProcess(json.dumps([]))
        if cmd.startswith('gcloud compute disks delete'):
           self.disk_delete_called = True

        return mocked_safe_exec(cmd)
