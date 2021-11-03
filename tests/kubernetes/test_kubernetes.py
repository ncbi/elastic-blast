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
Unit tests for kubernetes

Author: Greg Boratyn boratyng@ncbi.nlm.nih.gov
"""

import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
import json
from unittest.mock import MagicMock, patch
import pytest
from tests.utils import MockedCompletedProcess
from tests.utils import mocked_safe_exec
from tests.utils import GKE_PVS, GCP_DISKS, K8S_JOBS, gke_mock

from elastic_blast import kubernetes
from elastic_blast import gcp
from elastic_blast.config import configure
from elastic_blast.elb_config import ElasticBlastConfig
from elastic_blast.constants import ElbCommand
from elastic_blast.constants import K8S_UNINITIALIZED_CONTEXT
from elastic_blast.db_metadata import DbMetadata

from typing import List

TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

# Mocked tests


@pytest.fixture
def kubectl_mock(mocker):
    """Fixture function that replaces util.safe_exec with mocked_safe_exec"""

    # we need kubernetes.safe_exec instead of util.safe_exec here, because
    # safe_exec is imported in kubernetes.py with 'from util import safe_exec'
    # and safe_exec in kubernetes is seen as local, python is funny this way
    mocker.patch('elastic_blast.kubernetes.safe_exec', side_effect=mocked_safe_exec)


def test_fake_kubectl(kubectl_mock):
    """Test that calling fake safe_exec with wrong command line results in
    ValueError"""
    with pytest.raises(ValueError):
        kubernetes.safe_exec(['some', 'bad', 'commad', 'line'])
    kubernetes.safe_exec.assert_called()


def test_get_persistent_volumes(mocker):
    """Test getting k8s presistent volumes"""
    def fake_safe_exec(cmd):
        """Mocked safe_exec"""
        result = {'items': []}
        for i in GKE_PVS:
            result['items'].append({'metadata': {'name': i}})
        return MockedCompletedProcess(json.dumps(result))
    mocker.patch('elastic_blast.kubernetes.safe_exec', side_effect=fake_safe_exec)

    pvs = kubernetes.get_persistent_volumes(K8S_UNINITIALIZED_CONTEXT)
    assert sorted(pvs) == sorted(GKE_PVS)
    kubernetes.safe_exec.assert_called()


def test_get_persistent_volumes_bad_json(mocker):
    """Test that json parsing errors result in RuntimeError"""
    def safe_exec_bad_json(cmd):
        """Mocked kubectl that returns garbage"""
        return MockedCompletedProcess('some strange string')

    mocker.patch('elastic_blast.kubernetes.safe_exec', side_effect=safe_exec_bad_json)
    with pytest.raises(RuntimeError):
        kubernetes.get_persistent_volumes(K8S_UNINITIALIZED_CONTEXT)
    kubernetes.safe_exec.assert_called()


def test_get_persistent_disk(kubectl_mock):
    """Test getting k8s cluster persistent disks"""
    disks = kubernetes.get_persistent_disks(K8S_UNINITIALIZED_CONTEXT)
    assert sorted(disks) == sorted(GCP_DISKS)
    kubernetes.safe_exec.assert_called()


def test_get_persistent_disk_empty(mocker):
    """Test getting k8s cluster persistent disks with no disks"""
    def safe_exec_no_disks(cmd):
        """Mocked safe_exec"""
        result = {'items': []}
        return MockedCompletedProcess(json.dumps(result))
    mocker.patch('elastic_blast.kubernetes.safe_exec', side_effect=safe_exec_no_disks)

    disks = kubernetes.get_persistent_disks(K8S_UNINITIALIZED_CONTEXT)
    assert disks is not None
    assert not disks
    kubernetes.safe_exec.assert_called()


def test_submit_jobs_bad_path():
    """Test that RuntimeError is raised for non-existent path or empty directory"""
    path: Path = Path('/some/non/existent/path')
    assert not path.exists()
    with pytest.raises(RuntimeError):
        kubernetes.submit_jobs(K8S_UNINITIALIZED_CONTEXT, path)

    with TemporaryDirectory() as temp:
        path = Path(temp)
        assert path.exists()
        with pytest.raises(RuntimeError):
            kubernetes.submit_jobs(K8S_UNINITIALIZED_CONTEXT, path)


FAKE_LABELS = 'cluster-name=fake-cluster'


@pytest.fixture
def safe_exec_mock(mocker):
    """Fixture function that replaces util.safe_exec with print_safe_exec"""
    def print_safe_exec(cmd):
        """Specialized version of safe_exec mock to print its parameters and provide
        output only for initialize_persistent_disk specific calls"""
        if isinstance(cmd, list):
            cmd = ' '.join(cmd)
        print(cmd)
        if 'kubectl ' in cmd and 'get pv -o json' in cmd:
            result = {'items': []}  # type: ignore
            result['items'].append({'spec': {'gcePersistentDisk': {'pdName': GCP_DISKS[0]}}})  # type: ignore
            return MockedCompletedProcess(stdout=json.dumps(result))
        if 'kubectl ' in cmd and 'get pv' in cmd:
            return MockedCompletedProcess(stdout='CLAIM PDNAME\nblast-dbs-pvc gke-some-synthetic-name')
        if 'kubectl' in cmd and 'get -f' in cmd:
            fn = os.path.join(TEST_DATA_DIR, 'job-status.json')
            return MockedCompletedProcess(stdout=Path(fn).read_text())
        if 'kubectl ' in cmd and 'apply -f' in cmd:
            fn = cmd.split(' ')[-1] # the file name is the last argument in cmd
            with open(fn) as f:
                print(f.read())
        if cmd.startswith('gcloud compute disks update'):
            assert(cmd.startswith(f'gcloud compute disks update gke-some-synthetic-name --update-labels {FAKE_LABELS}'))
        if 'kubectl' in cmd and 'logs' in cmd:
            return MockedCompletedProcess(stdout='2020-06-18T04:48:33.320344002Z test log entry')
        return MockedCompletedProcess()

    # we need kubernetes.safe_exec instead of util.safe exec here, because
    # safe_exec is imported in kubernetes.py with 'from util import safe_exec'
    # and safe_exec in kubernetes is seen as local, python is funny this way
    mocker.patch('elastic_blast.kubernetes.safe_exec', side_effect=print_safe_exec)


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
def test_initialize_persistent_disk(safe_exec_mock, mocker):
    """Exercises initialize_persistent_disk with mock safe_exec and prints out
    arguments to safe_exec
    Run pytest -s -v tests/kubernetes to verify correct order of calls"""
    from argparse import Namespace
    def mocked_upload_file_to_gcs(fname, loc, dryrun):
        """Mocked upload to GS function"""
        pass
    mocker.patch('elastic_blast.kubernetes.upload_file_to_gcs', side_effect=mocked_upload_file_to_gcs)

    args = Namespace(cfg=os.path.join(TEST_DATA_DIR, 'initialize_persistent_disk.ini'))
    cfg = ElasticBlastConfig(configure(args), task = ElbCommand.SUBMIT)
    cfg.appstate.k8s_ctx = K8S_UNINITIALIZED_CONTEXT
    kubernetes.initialize_persistent_disk(cfg)


@patch(target='elastic_blast.elb_config.get_db_metadata', new=MagicMock(return_value=DB_METADATA))
def test_initialize_persistent_disk_failed(mocker):
    def fake_safe_exec_failed_job(cmd):
        fn = os.path.join(TEST_DATA_DIR, 'job-status-failed.json')
        return MockedCompletedProcess(stdout=Path(fn).read_text())

    def mocked_get_persistent_disks(k8s_ctx, dry_run):
        """Mocked getting persistent disks ids"""
        return list()

    mocker.patch('elastic_blast.kubernetes.safe_exec',
                 side_effect=fake_safe_exec_failed_job)
    mocker.patch('elastic_blast.kubernetes.get_persistent_disks',
                 side_effect=mocked_get_persistent_disks)
    from argparse import Namespace
    args = Namespace(cfg=os.path.join(TEST_DATA_DIR, 'initialize_persistent_disk.ini'))
    cfg = ElasticBlastConfig(configure(args), task = ElbCommand.SUBMIT)
    cfg.appstate.k8s_ctx = K8S_UNINITIALIZED_CONTEXT
    with pytest.raises(RuntimeError):
        kubernetes.initialize_persistent_disk(cfg)
    kubernetes.safe_exec.assert_called()


@patch(target='elastic_blast.elb_config.get_db_metadata', new=MagicMock(return_value=DB_METADATA))
def test_label_persistent_disk(safe_exec_mock):
    """Exercises label_persistent_disk with mock safe_exec and prints out
    arguments to safe_exec
    Run pytest -s -v tests/kubernetes to verify correct order of calls"""
    from argparse import Namespace
    args = Namespace(cfg=os.path.join(TEST_DATA_DIR, 'initialize_persistent_disk.ini'))
    cfg = ElasticBlastConfig(configure(args), task = ElbCommand.SUBMIT)
    # Replace labels with well-known fake for the purpose of testing command match,
    # see above in safe_exec_mock
    cfg.cluster.labels = FAKE_LABELS
    kubernetes.label_persistent_disk(cfg)


def test_delete_all(kubectl_mock):
    """Test deleteting all jobs, persistent volume claims and persistent volumes"""
    deleted = kubernetes.delete_all(K8S_UNINITIALIZED_CONTEXT)
    assert sorted(set(deleted)) == sorted(K8S_JOBS + GKE_PVS)
    kubernetes.safe_exec.assert_called()


def test_delete_all_no_resources(mocker):
    """Test deleting all whem no resources were created"""
    def safe_exec_no_resources(cmd):
        """Mocked safe_exec returning no resources found"""
        return MockedCompletedProcess('No resources found')

    mocker.patch('elastic_blast.kubernetes.safe_exec',
                 side_effect=safe_exec_no_resources)
    deleted = kubernetes.delete_all(K8S_UNINITIALIZED_CONTEXT)
    # result must be an empty list
    assert isinstance(deleted, list)
    assert not deleted
    kubernetes.safe_exec.assert_called()


def test_get_jobs(kubectl_mock):
    """Test getting kubernetes job ids"""
    jobs = kubernetes.get_jobs(K8S_UNINITIALIZED_CONTEXT)
    assert sorted(jobs) == sorted(K8S_JOBS)


# Tests running real kubectl

# A few test require specific GCP credentials and may create GCP resources.
# They are skipped. Set environment variable RUN_ALL_GCP_TESTS to run all tests.
SKIP = not os.getenv('RUN_ALL_TESTS')


def get_yamldir():
    """Return directory containg k8s yaml files used for tests"""
    return os.path.dirname(__file__)


def delete_cluster(name):
    """Helper function to delete a GKE cluster"""
    cmd = f'gcloud container clusters delete {name} -q'
    kubernetes.safe_exec(cmd)


def cluster_cleanup(cluster: str, disks: List[str] = None) -> List[str]:
    """Utility function to delete an existing GKE cluster along with its
    persistent disk.

    Agruments:
        cluster: GKE cluster name
        disks: Names of persistent disks used by the cluster

    Returns:
        List of errors"""
    errors = []

    try:
        delete_cluster(cluster)
    except Exception as err:
        errors.append(f'Error while deleting cluster: {cluster}: {err}')

    if disks:
        gcp_disks = None
        try:
            gcp_disks = gcp.get_disks()
        except Exception as err:
            errors.append('Error while listing GCP disks: {err}')

        for d in disks:
            if gcp_disks is None or d in gcp_disks:
                try:
                    gcp.delete_disk(d)
                except Exception as err:
                    errors.append(f'Error while deleting persistent disk {d}: {err}')

    return errors


@pytest.fixture
def gke_cluster_with_pv():
    """Fixture function that creates GKE cluster with persistent volume"""

    # test setup

    # create cluster
    name = os.environ['USER'] + '-elastic-blast-test-suite'
    gcp_zone = 'us-east4-b'
    cmd = f'gcloud container clusters create {name} --num-nodes 1 --preemptible --machine-type n1-standard-1 --labels project=elastic-blast-test'
    kubernetes.safe_exec(cmd.split())
    try:
        cmd = []
        cmd.append(f'gcloud container clusters get-credentials {name}')
        cmd.append('kubectl config current-context')
        cmd.append(f'kubectl apply -f {get_yamldir()}/test-storage-gcp.yaml')
        cmd.append(f'kubectl apply -f {get_yamldir()}/test-pvc.yaml')
        cmd.append(f'kubectl apply -f {get_yamldir()}/test-job-init-pv.yaml')
        for c in cmd:
            kubernetes.safe_exec(c.split())
    except:
        cluster_cleanup(name)
        raise
    # we need to wait for kubenetes to act on the cluster
    time.sleep(30)
    disks = kubernetes.get_persistent_disks(K8S_UNINITIALIZED_CONTEXT)
    yield name

    # test teardown
    if not name in gcp.get_gke_clusters():
        raise RuntimeError(f'Error cluster {name} should be present after the test')
    errors = cluster_cleanup(name, disks)
    message = '\n'.join(errors)

    # make sure that GCP resources were cleaned up
    assert name not in gcp.get_gke_clusters(), message
    gcp_disks = gcp.get_disks()
    for d in disks:
        assert d not in gcp_disks, message

    # and there were no errors
    assert not errors, message


@pytest.mark.skipif(SKIP, reason='This test requires specific GCP credentials and may create GCP resources. It should be used with care.')
def test_get_persistent_disks_real(gke_cluster_with_pv):
    """Test listing GKE persistent disks using real kubectl"""

    # cluster name
    name = gke_cluster_with_pv

    # make sure that cluster exists
    assert name in gcp.get_gke_clusters()

    disks = kubernetes.get_persistent_disks(K8S_UNINITIALIZED_CONTEXT)

    # there must be exactly one persistent disk
    assert len(disks) == 1

    # GCP disk name must be the same as in kubernetes
    assert len([d for d in gcp.get_disks() if disks[0] in d]) == 1


@pytest.mark.skipif(SKIP, reason='This test requires specific GCP credentials and may create GCP resources. It should be used with care.')
def test_delete_all_real(gke_cluster_with_pv):
    """Test deleting all jobs, pvcs, and pvs on a real GKE cluster"""
    # cluster name
    name = gke_cluster_with_pv

    # make sure cluster exists
    assert name in gcp.get_gke_clusters()

    # ... and has jobs and persistent disks
    disks = kubernetes.get_persistent_disks(K8S_UNINITIALIZED_CONTEXT)
    assert len(disks) > 0
    assert len(kubernetes.get_jobs(K8S_UNINITIALIZED_CONTEXT)) > 0

    # delete everything
    kubernetes.delete_all(K8S_UNINITIALIZED_CONTEXT)

    # test that jobs and volumes were deleted
    assert len(kubernetes.get_jobs(K8S_UNINITIALIZED_CONTEXT)) == 0
    assert len(kubernetes.get_persistent_disks(K8S_UNINITIALIZED_CONTEXT)) == 0
