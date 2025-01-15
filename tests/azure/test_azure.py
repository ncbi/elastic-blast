# 

"""
Unit tests for azure module

Author: Moon Hyuk Choi moonchoi@microsoft.com
"""

import subprocess
import os
from argparse import Namespace
from unittest.mock import patch, MagicMock
import pytest  # type: ignore
from elastic_blast import gcp
from elastic_blast import azure
from elastic_blast import kubernetes
from elastic_blast import config
from elastic_blast import elb_config
from elastic_blast import util
from elastic_blast.constants import CLUSTER_ERROR, ElbCommand
from elastic_blast.util import SafeExecError, UserReportError
from elastic_blast.elb_config import ElasticBlastConfig
from elastic_blast.db_metadata import DbMetadata
from tests.utils import MockedCompletedProcess
from tests.utils import mocked_safe_exec, get_mocked_config
from tests.utils import GCP_PROJECT, GCP_DISKS, GKE_PVS, GKE_CLUSTERS
from tests.utils import GKEMock, gke_mock, GCP_REGIONS

# Mocked tests

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

def test_fake_gcloud(gke_mock):
    """Test that calling fake safe_exec with wrong command line results in
    ValueError"""
    with pytest.raises(ValueError):
        gcp.safe_exec(['some', 'bad', 'commad', 'line'])


def test_get_gcp_project(gke_mock):
    """Test getting GCP project"""
    project = util.get_gcp_project()
    assert project == GCP_PROJECT
    util.safe_exec.assert_called()


def test_get_unset_gcp_project(mocker):
    """Test getting GCP project for unset project"""

    # we need a special case safe_exec
    def subst_safe_exec_unset_project(cmd):
        if cmd != 'gcloud config get-value project':
            raise ValueError(f'Bad gcloud command line: {cmd}')
        # this is how gcloud reports unset project
        return MockedCompletedProcess('(unset)')

    mocker.patch('elastic_blast.util.safe_exec',
                 side_effect=subst_safe_exec_unset_project)
    with pytest.raises(ValueError):
        project = util.get_gcp_project()


def test_set_gcp_project(gke_mock):
    """Test setting GCP project"""
    gcp.set_gcp_project('some-project')
    gcp.safe_exec.assert_called()


@patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
def test_get_disks(gke_mock):
    """Test getting a list of GCP persistent disks"""
    cfg = get_mocked_config()
    disks = gcp.get_disks(cfg)
    assert sorted(disks) == sorted(GCP_DISKS)
    gcp.safe_exec.assert_called()


@patch(target='elastic_blast.elb_config.get_db_metadata', new=MagicMock(return_value=DB_METADATA))
@patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
def test_get_disks_bad_output(mocker):
    """Test that gcp.get_disks raises RuntimeError for bad gcloud output"""

    def safe_exec_bad_gcloud(cmd):
        """Mocked util.safe_exec function that returns incorrect JSON"""
        if not cmd.startswith('gcloud compute disks list --format json'):
            raise ValueError(f'Bad gcloud command line: {cmd}')
        return MockedCompletedProcess('some-non-json-string')

    mocker.patch('elastic_blast.gcp.safe_exec', side_effect=safe_exec_bad_gcloud)
    with patch(target='elastic_blast.elb_config.safe_exec', new=MagicMock(side_effect=GKEMock().mocked_safe_exec)):
        with patch(target='elastic_blast.util.safe_exec', new=MagicMock(side_effect=GKEMock().mocked_safe_exec)):
            cfg = get_mocked_config()
    with pytest.raises(RuntimeError):
        gcp.get_disks(cfg)
    gcp.safe_exec.assert_called()


@patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
def test_delete_disk(gke_mock):
    """Test deleting a GCP disk"""
    cfg = get_mocked_config()
    gcp.delete_disk(GCP_DISKS[0], cfg)
    gcp.safe_exec.assert_called()


@patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
@patch(target='elastic_blast.elb_config.get_db_metadata', new=MagicMock(return_value=DB_METADATA))
def test_delete_nonexistent_disk(mocker):
    """Test that deleting a GCP disk that does not exits raises util.SafeExecError"""

    def fake_subprocess_run(cmd, check, stdout, stderr, env):
        """Fake subprocess.run function that raises exception and emulates
        command line returning with a non-zero exit code"""
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd, output=b'',
                                            stderr=b'')

    with patch(target='elastic_blast.elb_config.safe_exec', new=MagicMock(side_effect=GKEMock().mocked_safe_exec)):
        with patch(target='elastic_blast.util.safe_exec', new=MagicMock(side_effect=GKEMock().mocked_safe_exec)):
            cfg = get_mocked_config()

    mocker.patch('subprocess.run', side_effect=fake_subprocess_run)

    with pytest.raises(SafeExecError):
        gcp.delete_disk('some-disk', cfg)
    subprocess.run.assert_called()


@patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
def test_delete_disk_empty_name(gke_mock):
    """Test that deleting disk with and empty name results in ValueError"""
    cfg = get_mocked_config()
    with pytest.raises(ValueError):
        gcp.delete_disk('', cfg)


@patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
def test_get_gke_clusters(gke_mock):
    """Test listing GKE clusters"""
    cfg = get_mocked_config()
    clusters = gcp.get_gke_clusters(cfg)
    assert sorted(clusters) == sorted(GKE_CLUSTERS)
    gcp.safe_exec.assert_called()


@patch(target='elastic_blast.elb_config.get_db_metadata', new=MagicMock(return_value=DB_METADATA))
@patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
def test_get_gke_clusters_empty(mocker):
    """Test listing GKE clusters for an empty list"""

    def safe_exec_empty(cmd):
        """Mocked safe_exec returning an emty JSON list"""
        return MockedCompletedProcess('[]')

    mocker.patch('elastic_blast.gcp.safe_exec', side_effect=safe_exec_empty)
    with patch(target='elastic_blast.elb_config.safe_exec', new=MagicMock(side_effect=GKEMock().mocked_safe_exec)):
        with patch(target='elastic_blast.util.safe_exec', new=MagicMock(side_effect=GKEMock().mocked_safe_exec)):
            cfg = get_mocked_config()
    assert len(gcp.get_gke_clusters(cfg)) == 0
    gcp.safe_exec.assert_called()


@patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
def test_delete_cluster_with_cleanup(gke_mock):
    """Test deleting GKE cluster and its persistent disks"""
    cfg = get_mocked_config()
    gcp.delete_cluster_with_cleanup(cfg)
    gcp.safe_exec.assert_called()
    kubernetes.safe_exec.assert_called()


@patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
def test_delete_cluster_with_cleanup_no_cluster(gke_mock):
    """Test deleting GKE cluster with cleanup when no cluster is present"""
    # no cluster found in GKE
    gke_mock.set_options(['no-cluster'])

    cfg = get_mocked_config()
    with pytest.raises(UserReportError):
        gcp.delete_cluster_with_cleanup(cfg)
    gcp.safe_exec.assert_called()


@patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
def test_delete_cluster_with_cleanup_disk_left(gke_mock, mocker):
    """Test that disk is deleted even if k8s did not delete it"""
    def mocked_get_disks(cfg, dry_run):
        """Mocked getting GCP disks"""
        return GCP_DISKS

    def mocked_delete_disk(name, cfg):
        """Mocked GCP disk deletion"""
        pass

    def mocked_delete_cluster(cfg):
        """Mocked deletion of GKE cluster"""
        return GKE_CLUSTERS[0]

    def mocked_get_persistent_disks(ignore_me, dry_run):
        """Mocked listing of kubernets persistent disks"""
        # persistent disk to delete
        return [GCP_DISKS[0]]

    mocker.patch('elastic_blast.gcp.get_disks', side_effect=mocked_get_disks)
    mocker.patch('elastic_blast.gcp.delete_disk', side_effect=mocked_delete_disk)
    mocker.patch('elastic_blast.gcp.delete_cluster', side_effect=mocked_delete_cluster)
    mocker.patch('elastic_blast.kubernetes.get_persistent_disks',
                 side_effect=mocked_get_persistent_disks)

    cfg = get_mocked_config()
    #with pytest.raises(UserReportError) as err:
    gcp.delete_cluster_with_cleanup(cfg)
    #assert err.value.returncode == CLUSTER_ERROR
    #assert 'not able to delete persistent disk' in err.value.message
    #assert GCP_DISKS[0] in err.value.message
    gcp.safe_exec.assert_called()
    kubernetes.get_persistent_disks.assert_called()
    # test that GCP disk deletion was called for the appropriate disk
    gcp.delete_disk.assert_called_with(GCP_DISKS[0], cfg)
    # test that cluster deletion was called
    gcp.delete_cluster.assert_called_with(cfg)


@patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
def test_delete_cluster_with_cleanup_failed_kubectl(gke_mock, mocker):
    """Test that cluster deletion is called when we cannot communicate with
    it with kubectl"""
    def mocked_delete_cluster(cfg):
        """Mocked cluster deletion"""
        return GKE_CLUSTERS[0]

    # any kubectl call fails
    gke_mock.set_options(['kubectl-error'])
    mocker.patch('elastic_blast.gcp.delete_cluster', side_effect=mocked_delete_cluster)

    cfg = get_mocked_config()
    gcp.delete_cluster_with_cleanup(cfg)
    kubernetes.safe_exec.assert_called()
    # test cluster deletion was called
    gcp.delete_cluster.assert_called_with(cfg)


@patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
def test_delete_cluster_with_cleanup_failed_get_disks(gke_mock, mocker):
    """Test that cluster and disk deletion are called when getting a list of
    GCP disks failed"""
    def mocked_get_disks(cfg, dry_run):
        """Mocked listing of GCP disks"""
        mocked_get_disks.invocation_counter += 1
        if mocked_get_disks.invocation_counter == 1:
            raise RuntimeError('Mocked GCP listing error')
        elif mocked_get_disks.invocation_counter == 2:
            return [GCP_DISKS[0]]
        return []
    mocked_get_disks.invocation_counter = 0

    def mocked_delete_cluster(cfg):
        """Mocked cluster deletion"""
        return GKE_CLUSTERS[0]

    def mocked_delete_disk(name, cfg):
        """Mocked disk deletion"""
        pass

    def mocked_get_persistent_disks(ignore_me, dry_run):
        """Mocked listing of GKE cluster persistent disks"""
        return [GCP_DISKS[0]]

    mocker.patch('elastic_blast.gcp.get_disks', side_effect=mocked_get_disks)
    mocker.patch('elastic_blast.gcp.delete_cluster', side_effect=mocked_delete_cluster)
    mocker.patch('elastic_blast.gcp.delete_disk', side_effect=mocked_delete_disk)
    mocker.patch('elastic_blast.kubernetes.get_persistent_disks',
                 side_effect=mocked_get_persistent_disks)

    cfg = get_mocked_config()
    gcp.delete_cluster_with_cleanup(cfg)
    gcp.safe_exec.assert_called()
    kubernetes.safe_exec.assert_called()
    # test cluster deletion was called
    gcp.delete_cluster.assert_called_with(cfg)
    # test that disk deletion was called
    gcp.delete_disk.assert_called_with(GCP_DISKS[0], cfg)


@patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
def test_delete_cluster_with_cleanup_cluster_provisioning(gke_mock, mocker):
    """Test that cluster provisioning is handled when deleting the cluster.
    The code should wait until cluster status is RUNNING and delete it then."""
    class GKEStatusMock:
        """Class to mock changin GKE cluster status"""

        def __init__(self):
            self.status = 'PROVISIONING'

        def mocked_check_cluster(self, cfg):
            """Mocked check cluster status. Returns PROVISIONING the first time
            and RUNNING after that"""
            if self.status == 'PROVISIONING':
                self.status = 'RUNNING'
                return 'PROVISIONING'
            return self.status

    def mocked_delete_cluster(cfg):
        """Mocked cluster deletion"""
        return cfg.cluster.name

    mocked_cluster = GKEStatusMock()
    mocker.patch('elastic_blast.gcp.check_cluster',
                 side_effect=mocked_cluster.mocked_check_cluster)
    mocker.patch('elastic_blast.gcp.delete_cluster', side_effect=mocked_delete_cluster)

    cfg = get_mocked_config()
    gcp.delete_cluster_with_cleanup(cfg)
    # test that gcp.check_cluster was called more than once
    assert gcp.check_cluster.call_count > 1
    # test that cluster deletion was called
    gcp.delete_cluster.assert_called()


@patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
def test_delete_cluster_with_cleanup_cluster_reconciling(gke_mock, mocker):
    """Test that cluster status RECONCILING is handled when deleting the
    cluster. The code should wait until cluster status is RUNNING and delete
    it then."""
    class GKEStatusMock:
        """Class to mock changin GKE cluster status"""

        def __init__(self):
            self.status = 'RECONCILING'

        def mocked_check_cluster(self, cfg):
            """Mocked check cluster status. Returns RECONCILING the first time
            and RUNNING after that"""
            if self.status == 'RECONCILING':
                self.status = 'RUNNING'
                return 'RECONCILING'
            return self.status

    def mocked_delete_cluster(cfg):
        """Mocked cluster deletion"""
        return cfg.cluster.name

    mocked_cluster = GKEStatusMock()
    mocker.patch('elastic_blast.gcp.check_cluster',
                 side_effect=mocked_cluster.mocked_check_cluster)
    mocker.patch('elastic_blast.gcp.delete_cluster', side_effect=mocked_delete_cluster)

    cfg = get_mocked_config()
    gcp.delete_cluster_with_cleanup(cfg)
    # test that gcp.check_cluster was called more than once
    assert gcp.check_cluster.call_count > 1
    # test that cluster deletion was called
    gcp.delete_cluster.assert_called()


@patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
def test_delete_cluster_with_cleanup_cluster_error(gke_mock, mocker):
    """Test deleting a cluster with ERROR status"""
    def mocked_check_cluster(cfg):
        """Mocked checking cluster status"""
        return 'ERROR'

    def mocked_delete_cluster(cfg):
        """Mocked cluster deletion only to verify that it was called"""
        return cfg.cluster.name

    mocker.patch('elastic_blast.gcp.check_cluster', side_effect=mocked_check_cluster)
    mocker.patch('elastic_blast.gcp.delete_cluster', side_effect=mocked_delete_cluster)
    cfg = get_mocked_config()
    gcp.delete_cluster_with_cleanup(cfg)
    gcp.check_cluster.assert_called()
    # cluster deletion must be called
    gcp.delete_cluster.assert_called()


@patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
def test_delete_cluster_with_cleanup_cluster_status_unrecognized(gke_mock, mocker):
    """Test deleting a cluster with unrecognized status"""
    def mocked_check_cluster(cfg):
        """Mocked checking cluster status"""
        return 'SOME_STRANGE_STATUS'

    def mocked_delete_cluster(cfg):
        """Mocked cluster deletion only to verify that it was called"""
        return cfg.cluster.name

    mocker.patch('elastic_blast.gcp.check_cluster', side_effect=mocked_check_cluster)
    mocker.patch('elastic_blast.gcp.delete_cluster', side_effect=mocked_delete_cluster)
    cfg = get_mocked_config()
    gcp.delete_cluster_with_cleanup(cfg)
    gcp.check_cluster.assert_called()
    # cluster deletion must be called
    gcp.delete_cluster.assert_called()


@patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
def test_delete_cluster_with_cleanup_cluster_stopping(gke_mock, mocker):
    """Test deleting cluster with the cluster is beeing stopped. The code
    should raise RuntimeError"""
    def mocked_check_cluster(cfg):
        """Mocked check cluster status. STOPPING never changes to RUNNING."""
        return 'STOPPING'

    mocker.patch('elastic_blast.gcp.check_cluster', side_effect=mocked_check_cluster)
    cfg = get_mocked_config()
    with pytest.raises(UserReportError) as errinfo:
        gcp.delete_cluster_with_cleanup(cfg)

    # test return code and message in UserReportError
    assert errinfo.value.returncode == CLUSTER_ERROR
    assert GKE_CLUSTERS[0] in errinfo.value.message
    assert 'already being deleted' in errinfo.value.message


@patch(target='elastic_blast.elb_config.gcp_get_regions', new=MagicMock(return_value=GCP_REGIONS))
def test_remove_split_query(mocker):
    """Test that util.remove_split_query calls safe_exec with correct command"""

    RESULTS = 'gs://results'
    QUERIES = RESULTS + '/query_batches/*'

    def safe_exec_gsutil_rm(cmd):
        """Mocked util.safe_exec function that simulates gsutil rm"""
        if cmd != f'gsutil -mq rm {QUERIES}':
            raise ValueError(f'Bad gsutil command line: {cmd}')
        return MockedCompletedProcess('')

    mocker.patch('elastic_blast.gcp.safe_exec', side_effect=safe_exec_gsutil_rm)
    mocker.patch('elastic_blast.gcp_traits.safe_exec', side_effect=mocked_safe_exec)
    with patch(target='elastic_blast.elb_config.safe_exec', new=MagicMock(side_effect=GKEMock().mocked_safe_exec)):
        with patch(target='elastic_blast.util.safe_exec', new=MagicMock(side_effect=GKEMock().mocked_safe_exec)):
            cfg = ElasticBlastConfig(gcp_project = 'test-gcp-project',
                                     gcp_region = 'test-gcp-region',
                                     gcp_zone = 'test-gcp-zone',
                                     results = 'gs://test-bucket',
                                     task = ElbCommand.DELETE)

    cfg.cluster.results = RESULTS
    gcp.remove_split_query(cfg)
    gcp.safe_exec.assert_called()



# Tests running real gcloud

# A few test require specific GCP credentials and may create GCP resources.
# They are skipped. Set environment variable RUN_ALL_TESTS to run all tests.
SKIP = not os.getenv('RUN_ALL_TESTS')


@pytest.mark.skipif(SKIP, reason='This test requires specific GCP credentials and may create GCP resources. It should be used with care.')
def test_get_gcp_project_real():
    """Test getting GCP project using real command line"""
    result = elb_config.get_gcp_project()
    # result must not be an empty string
    assert (result is None or len(result) > 0)


@pytest.fixture
def provide_disk():
    """Fixture function that creates GCP disk when setting up a test and
    deletes it when tearing the test down, returns disk name."""

    # test setup
    name = os.environ['USER'] + '-elastic-blast-test-suite'
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    args = Namespace(cfg=os.path.join(data_dir, 'test-cfg-file.ini'))
    cfg = ElasticBlastConfig(config.configure(args), task = ElbCommand.SUBMIT)
    cmd = f'gcloud beta compute disks create {name} --project={cfg.gcp.project} --type=pd-standard --size=10GB --zone={cfg.gcp.zone}'
    gcp.safe_exec(cmd.split())
    yield name, cfg

    # test teardown
    if name in gcp.get_disks(cfg):
        gcp.delete_disk(name, cfg)


@pytest.mark.skipif(SKIP, reason='This test requires specific GCP credentials and may create GCP resources. It should be used with care.')
def test_get_delete_disk_real(provide_disk):
    """Test deleting GCP disk using real gcloud calls"""

    # disk name
    name, cfg = provide_disk

    # the disk was created in setp
    assert name in gcp.get_disks(cfg)

    # delete the disk and test that it does not appear when listing disks
    gcp.delete_disk(name, cfg)
    assert name not in gcp.get_disks(cfg)


@pytest.fixture
def provide_cluster():
    """Create a GCKE cluster before and delete it after a test"""
    # setup
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    args = Namespace(cfg=os.path.join(data_dir, 'test-cfg-file.ini'))
    cfg = ElasticBlastConfig(config.configure(args), task = ElbCommand.SUBMIT)
    
    # The following values should be defined in .env.
    cfg.cluster.name = cfg.cluster.name + f'-{os.environ["USER"]}'    
    # cfg.azure.tenant_id = os.environ['AZURE_TENANT_ID']
    # cfg.azure.client_id = os.environ['AZURE_CLIENT_ID']
    # cfg.azure.client_secret = os.environ['AZURE_CLIENT_SECRET']

    cmd = f'gcloud container clusters create {cfg.cluster.name} --num-nodes 1 --machine-type n1-standard-1 --labels elb=test-suite'
    gcp.safe_exec(cmd.split())
    yield cfg

    # teardown
    name = cfg.cluster.name
    if name in gcp.get_gke_clusters(cfg):
        cmd = f'gcloud container clusters delete {name} -q'
        gcp.safe_exec(cmd.split())


@pytest.mark.skipif(False, reason='This test requires specific GCP credentials and may create GCP resources. It should be used with care.')
def test_get_aks_credentials_real(provide_cluster):
    """Test that gcp.get_gke_credentials does not raise exceptiions when a
    cluster is present"""
    cfg = provide_cluster
    azure.get_aks_credentials(cfg)


@pytest.mark.skipif(False, reason='This test requires specific GCP credentials and may create GCP resources. It should be used with care.')
def test_get_gke_credentials_no_cluster_real():
    """Test that util.SafeExecError is raised when getting credentials of a
    non-existent cluster"""
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    args = Namespace(cfg=os.path.join(data_dir, 'test-cfg-file.ini'))
    cfg = ElasticBlastConfig(config.configure(args), task = ElbCommand.SUBMIT)
    cfg.cluster.name = 'some-strange-cluster-name'
    assert cfg.cluster.name not in gcp.get_gke_clusters(cfg)
    with pytest.raises(SafeExecError):
        gcp.get_gke_credentials(cfg)

