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


* gke_mock is a pytest fixture that sets up code that simulates cloud APIs and mocks safe_exec and boto3.resource. It simulates a lot of GCP functionality and a little bit of AWS, so the name needs to be changed to something like cloud_mock.

* CloudResources is a class that simulates present and absent cloud resources, currently only GCS and S3, but I plan to add disks and clusters (likely in other pull requests). The code in gke_mock creates, deletes, and test entries in the CloudResources. Currently, because our code expects query files and results bucket to be present in cloud storage one needs create entries for them in the CloudResources object in each test. I plan to change all tests to use the same query file and results bucket so that these can be preset for all tests and then CloudResources will be an internal class for most tests and a test implementer will not need to know about it.
"""

import json
import os
import io
from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError
from elastic_blast.util import SafeExecError
from elastic_blast import config
from elastic_blast.elb_config import ElasticBlastConfig
from elastic_blast.constants import ElbCommand
from elastic_blast.constants import ELB_DFLT_AWS_REGION, CLUSTER_ERROR
from typing import Optional, List, Union, Dict
import pytest

# name of bucket without write permissions, used for tests where bucket exits
# but is not writable
NOT_WRITABLE_BUCKET = 'not-writable-bucket'
DB_METADATA_PROT = """{
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
  "number-of-volumes": 1
}
"""
DB_METADATA_PROT_FILE_NAME = 'testdb-prot-metadata.json'

DB_METADATA_NUCL = """{
  "dbname": "testdb",
  "version": "1.1",
  "dbtype": "Nucleotide",
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
  "number-of-volumes": 1
}
"""
DB_METADATA_NUCL_FILE_NAME = 'testdb-nucl-metadata.json'


class MockedCompletedProcess:
    """Fake subprocess.CompletedProcess class used for mocking return
    value of subprocess.run() to emulate command line calls."""

    def __init__(self, stdout: str = '',
                 stderr: str = '',
                 returncode: int = 0,
                 subprocess_run_called: bool = True,
                 storage: Optional[Dict[str, str]] = None,
                 key: Optional[str] = None):
        """Class constructor
        Arguments:
            stdout: Called process stdout
            stderr: Called process stderr
            returncode: Called process return code
            subprocess_run_called: Differentiates between objects created by
                                   subprocess.run and subprocess.Popen
            storage: Object simulating cloud storage (not needed in most cases)
            key: Cloud storage object key (not needed in most cases)"""
        if subprocess_run_called:
            self.stdout: Optional[bytes] = str.encode(stdout)
            self.stderr: Optional[bytes] = str.encode(stderr)
        else:
            # when CompletedProcess is created by subprocess.Popen,
            # CompletedProcess.stdout and CompletedProcess.stderr are streams
            self.stdout = io.StringIO(stdout)
            self.stderr = io.StringIO(stderr)
        self.returncode: int = returncode
        self.stdin = MagicMock()
        self.storage = storage
        self.key = key

    def communicate(self, arg):
        """Simulate writing subprocess stdin to a cloud storage object.
        This function is used in elastic_blast.fileheloper.check_dir_for_write
        to test that a bucket is writable."""
        if self.storage and self.key:
            if NOT_WRITABLE_BUCKET in self.key:
                return (1, b'Mocked error: cannot write to bucket')
            self.storage[self.key] = arg.decode()
        else:
            return (1, b'Mocked error: no storage or key')
        return (0, b' ')


@pytest.fixture
def gke_mock(mocker):
    """Fixtire function that replaces util.safe_exec with mocked_safe_exec"""

    mock = GKEMock()

    mock.cloud.storage['gs://test-bucket/test-query.fa'] = '>query\nACTGGAGATGAC'
    mock.cloud.storage['gs://test-results'] = ''
    mock.cloud.storage[f'gs://{NOT_WRITABLE_BUCKET}'] = ''
    mock.cloud.storage['s3://test-bucket/test-query.fa'] = '>query\nACTGGAGATGAC'
    mock.cloud.storage['s3://test-results'] = ''
    mock.cloud.storage[f's3://{NOT_WRITABLE_BUCKET}'] = ''

    # Mocked NCBI database metadata
    mock.cloud.storage['gs://blast-db/latest-dir'] = '000'
    mock.cloud.storage[f'gs://blast-db/000/{DB_METADATA_PROT_FILE_NAME}'] = DB_METADATA_PROT
    mock.cloud.storage[f'gs://blast-db/000/{DB_METADATA_NUCL_FILE_NAME}'] = DB_METADATA_NUCL
    mock.cloud.storage['s3://ncbi-blast-databases/latest-dir'] = '000'
    mock.cloud.storage[f's3://ncbi-blast-databases/000/{DB_METADATA_PROT_FILE_NAME}'] = DB_METADATA_PROT
    mock.cloud.storage[f's3://ncbi-blast-databases/000/{DB_METADATA_NUCL_FILE_NAME}'] = DB_METADATA_NUCL

    # User database metadata
    mock.cloud.storage[f'gs://test-bucket/{DB_METADATA_PROT_FILE_NAME}'] = DB_METADATA_PROT
    mock.cloud.storage[f'gs://test-bucket/{DB_METADATA_NUCL_FILE_NAME}'] = DB_METADATA_NUCL
    mock.cloud.storage[f's3://test-bucket/{DB_METADATA_PROT_FILE_NAME}'] = DB_METADATA_PROT
    mock.cloud.storage[f's3://test-bucket/{DB_METADATA_NUCL_FILE_NAME}'] = DB_METADATA_NUCL

    # we need gcp.safe_exec instead of util.safe exec here, because
    # safe_exec is imported in gcp.py with 'from util import safe_exec'
    # and safe_exec in gcp is seen as local, python is funny this way
    mocker.patch('elastic_blast.gcp.safe_exec', side_effect=mock.mocked_safe_exec)
    mocker.patch('elastic_blast.kubernetes.safe_exec', side_effect=mock.mocked_safe_exec)
    mocker.patch('elastic_blast.util.safe_exec', side_effect=mock.mocked_safe_exec)
    mocker.patch('elastic_blast.filehelper.safe_exec', side_effect=mock.mocked_safe_exec)
#    mocker.patch('subprocess.Popen', new=MagicMock(return_value=MockedCompletedProcess()))
    mocker.patch('subprocess.Popen', side_effect=mock.mocked_popen)
    mocker.patch('boto3.resource', side_effect=mock.mocked_resource)
    mocker.patch('boto3.client', side_effect=mock.mocked_client)
    mocker.patch('botocore.exceptions.ClientError.__init__', new=MagicMock(return_value=None))

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
                             db = 'testdb',
                             queries = 'test-queries.fa',
                             results = 'gs://elasticblast-blastadm',
                             task = ElbCommand.SUBMIT)

    cfg.cluster.name = GKE_CLUSTERS[0]

    return cfg


@dataclass
class CloudResources:
    """Class to simulate created cloud resources"""
    # dictionary of cloud storage objects, where key is object keya and value is
    # object content, any object is readable and writable
    storage: Dict[str, str] = field(default_factory=dict)


def mocked_safe_exec(cmd: Union[List[str], str], cloud_state: CloudResources = None) -> MockedCompletedProcess:
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

    # check if gcloud is installed
    if ' '.join(cmd) == 'gcloud --version':
        return MockedCompletedProcess()

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
    elif cmd[0] == 'kubectl' and 'get pv -o json' in ' '.join(cmd):
        result = {'items': []}  # type: ignore
        for i in GCP_DISKS:
            result['items'].append({'spec': {'gcePersistentDisk': {'pdName': i}}})  # type: ignore
        return MockedCompletedProcess(json.dumps(result))

    # get kubernetes jobs
    elif cmd[0] == 'kubectl' and 'get jobs -o json' in ' '.join(cmd):
        result = {'items': []}
        for i in K8S_JOBS:
            result['items'].append({'metadata': {'name': i}})
        return MockedCompletedProcess(json.dumps(result))

    # get kubernetes job status with one pod deleted due to failure
    elif cmd[0] == 'kubectl' and 'get pods -o custom-columns=STATUS' in ' '.join(cmd):
        return MockedCompletedProcess('\n'.join(['STATUS'] + ['Running' for i in K8S_JOB_STATUS if i == 'Running']))

    elif cmd[0] == 'kubectl' and 'get jobs -o custom-columns=STATUS' in ' '.join(cmd):
        switcher = {'Failed': 'Failed',
                    'Succeeded': 'Complete',
                    'Running': '<none>',
                    'Pending': '<none>'}
        return MockedCompletedProcess('\n'.join(['STATUS'] + [switcher[i] for i in K8S_JOB_STATUS]))

    # delete all jobs
    elif cmd[0] == 'kubectl' and 'delete jobs' in ' '.join(cmd):
       return MockedCompletedProcess('\n'.join(['deleted ' + i for i in K8S_JOBS]) + '\n')

    # delete all pvcs
    elif cmd[0] == 'kubectl' and  'delete pvc --all' in ' '.join(cmd):
        return MockedCompletedProcess('\n'.join(['deleted ' + i for i in GKE_PVS]) + '\n')

    # delete all pvs
    elif cmd[0] == 'kubectl' and 'delete pv --all' in ' '.join(cmd):
        return MockedCompletedProcess('\n')

    # check if kubernetes client is installed or cluster is alive
    elif ' '.join(cmd).startswith('kubectl') and 'version' in ' '.join(cmd):
        return MockedCompletedProcess()

    # list BLAST databases available in the cloud
    elif ' '.join(cmd).startswith('update_blastdb.pl') and '--showall' in cmd:
        return MockedCompletedProcess(f'{BLASTDB}\tTitle of {BLASTDB}\t0.1\t2020-01-01')

    # Check the resource quota in GKE
    elif ' '.join(cmd).startswith('kubectl get resourcequota gke-resource-quotas'):
        return MockedCompletedProcess('"10k"')

    # check if gsutil is installed
    elif ' '.join(cmd) == 'gsutil --version':
        return MockedCompletedProcess()

    # Check whether a file exists in GCS
    elif ' '.join(cmd).startswith('gsutil -q stat'):
        if cloud_state:
            if cmd[-1] in cloud_state.storage:
                return MockedCompletedProcess()
            else:
                raise SafeExecError(returncode=1, message=f'File {cmd[-1]} was not found')
        else:
            return MockedCompletedProcess(stdout='',stderr='',returncode=0)

    # Check whether a file exists in GCS
    elif ' '.join(cmd).startswith('gsutil -q cat') or ' '.join(cmd).startswith('gsutil cat'):
        cmd = ' '.join(cmd)
        # simulate reading NCBI database manifest
        if cmd.endswith('latest-dir'):
            return MockedCompletedProcess(stdout='xxxx')
        elif cmd.endswith('blastdb-manifest.json'):
            manifest = {'nr': {'size': 25}, 'nt': {'size': 25}, 'pdbnt': {'size': 25}, 'testdb': {'size': 25}}
            return MockedCompletedProcess(stdout=json.dumps(manifest))
        else:
            return MockedCompletedProcess(stdout='',stderr='',returncode=0)

    # copy files to GCS
    elif ' '.join(cmd).startswith('gsutil -qm cp') or ' '.join(cmd).startswith('gsutil -mq cp'):
        return MockedCompletedProcess()

    # remove a file from GCS
    elif ' '.join(cmd).startswith('gsutil -q rm'):
        return MockedCompletedProcess(stdout='',stderr='',returncode=0)

    # Check whether a file is being removed from GCS
    elif ' '.join(cmd).startswith('gsutil -mq rm'):
        return MockedCompletedProcess(stdout='',stderr='',returncode=0)

    elif ' '.join(cmd).startswith('kubectl config current-context'):
        return MockedCompletedProcess(stdout='dummy-context',stderr='',returncode=0)

    elif cmd[0] == 'kubectl' and  'apply -f' in ' '.join(cmd):
        return MockedCompletedProcess(stdout='',stderr='',returncode=0)

    # raise ValueError for unrecognized command line
    else:
        raise ValueError(f'Unrecognized gcloud or kubectl command line: {cmd}')


class GKEMock:
    """Utility class for mocking util.safe_exec that with different
    results for the same parameters command line paramters."""
    allowed_options = ['no-cluster',
                       'kubectl-error',
                       'bad-results-bucket']

    def __init__(self):
        """Class constructor"""
        self.options = list()
        self.disk_delete_called = False
        self.cloud = CloudResources()

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
                cmd.startswith('gcloud container clusters delete'):
                raise SafeExecError(returncode=1,
                                    message='Mocked error: cluster does not exist')

            if cmd.startswith('gcloud container clusters delete'):
                raise UserReportError(returncode=CLUSTER_ERROR,
                                      message='Mocked error: cluster does not exist')

            if cmd.startswith('gcloud container clusters list'):
                return MockedCompletedProcess('')

        # any kubectl call fails
        if 'kubectl-error' in self.options:
            if cmd.startswith('kubectl') and 'config current-context' not in cmd:
                raise SafeExecError(returncode=1,
                                    message=f'Mocked kubectl error in "{cmd}"')

        # report no disks after disk deletion was called
        if cmd.startswith('gcloud compute disks list') and self.disk_delete_called:
            return MockedCompletedProcess(json.dumps([]))
        if cmd.startswith('gcloud compute disks delete'):
           self.disk_delete_called = True

        return mocked_safe_exec(cmd, self.cloud)


    def mocked_popen(self, cmd, stderr, stdin=None, stdout=None, universal_newlines=True):
        """Mocked subprocess.Popen function, used to mock calls to gsutil used
            in elastic_blast.filehelper"""
        # open_for_read
        if ' '.join(cmd).startswith('gsutil cat'):
            if cmd[-1] in self.cloud.storage:
                return MockedCompletedProcess(stdout=self.cloud.storage[cmd[-1]], stderr='', subprocess_run_called=False)
            else:
                return MockedCompletedProcess(returncode=1, stdout='', stderr=f'Object "{cmd[-1]}" does not exist', subprocess_run_called=False)
        # test dir for write
        elif ' '.join(cmd).startswith('gsutil cp -'):
            if '/'.join(cmd[-1].split('/')[:-1]) in self.cloud.storage:
                if NOT_WRITABLE_BUCKET in cmd[-1]:
                    return MockedCompletedProcess(returncode=1, stderr=f'Mocked error: cannot write to bucker {cmd[-1]}')
                return MockedCompletedProcess(storage=self.cloud.storage, key=cmd[-1], subprocess_run_called=False)
            else:
                return MockedCompletedProcess(returncode=1, subprocess_run_called=False)

        # raise ValueError for unrecognized command line
        else:
            raise ValueError(f'Unrecognized gcloud or kubectl command line: {cmd}')


    def mocked_resource(self, resource, config=None):
        """Mocked boto3.resource function"""
        if resource == 's3':
            return MockedS3Resource(self.cloud.storage)
        elif resource == 'cloudformation':
            return MockedCloudformationResource()
        else:
            raise NotImplementedError(f'boto3 mock for {resource} resource is not implemented')


    def mocked_client(self, client, config=None):
        """Mocked boto3.resource function"""
        if client == 's3':
            return MockedS3Client(self.cloud.storage)
        else:
            raise NotImplementedError(f'boto3 mock for {client} client is not implemented')


@pytest.fixture
def aws_credentials():
    """Credentials for mocked AWS services. This fixture ensures that we are
    not accidentally creating resources in real AWS accounts."""

    # Setup
    # save AWS-related variables before modifying environment
    saved_vars = {key: os.environ[key] for key in os.environ if key.startswith('AWS')}

    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_ACCT'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = ELB_DFLT_AWS_REGION

    yield

    # Cleanup
    # bring back pre-test environment
    for i in saved_vars:
        os.environ[i] = saved_vars[i]


class MockedS3Object:
    """Mocked boto3 S3 object"""
    def __init__(self, bucket, key):
        self.obj = f's3://{bucket}/{key}'
        self.storage = {}

    def load(self):
        """Raise ClientError if the object is not in storage, otherwise do nothing"""
        if self.obj not in self.storage:
            raise ClientError(None, None)


class MockedS3Resource:
    """Mocked boto3 S3 resource object"""
    def __init__(self, cloud_storage):
        """Initialize object"""
        self.storage = cloud_storage

    def Object(self, bucket, key):
        """Mocked s3.Object function that creates S3 objects"""
        obj = MockedS3Object(bucket, key)
        obj.storage = self.storage
        return obj


class MockedStream(str):
    """A string stream class needed for mocked downloads from S3, used by
    filehelper.open_for_read"""
    def __init__(self, data):
        """Initialize an object"""
        self.data = data
        self.cl = False

    def close(self):
        """Close stream"""
        pass

    def read(self, pos):
        """Read from the stream"""
        if not self.cl:
            self.cl = True
            return self.data.encode()
        else:
            return b''


class MockedS3Client:
    """Mocked boto3 S3 client object"""
    def __init__(self, cloud_storage):
        """Initialize object"""
        self.storage = cloud_storage

    def get_object(self, Bucket, Key):
        """Get an S3 object"""
        key = f's3://{Bucket}/{Key}'
        if key not in self.storage:
            raise
        return {'Body': MockedStream(self.storage[key])}


class MockedCloudformationStack:
    """Mocked boto3 cloudformation stack object"""
    def __init__(self, name):
        self.name = name

    def __getattr__(self, name):
        """Always raise an exception to indicate that there is no stack named
            self.name"""
        raise ClientError


class MockedCloudformationResource:
    """Mocked boto3 cloudformation resource"""
    def Stack(self, name):
        """Mocked create stack object"""
        return MockedCloudformationStack(name)
