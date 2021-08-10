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
Help functions to access GCP resources and manipulate parameters and environment

Author: Greg Boratyn boratyng@ncbi.nlm.nih.gov
             Yuriy Merezhuk merezhuk@ncbi.nlm.nih.gov
"""

import os
import time
import logging
import json
from timeit import default_timer as timer
from tenacity import retry, stop_after_attempt, wait_exponential
from .util import safe_exec, UserReportError, SafeExecError
from .util import validate_gcp_disk_name
from . import kubernetes
from .constants import CLUSTER_ERROR, GCP_APIS, ELB_METADATA_DIR
from .constants import ELB_STATE_DISK_ID_FILE, CSP, DEPENDENCY_ERROR
from .constants import ELB_QUERY_BATCH_DIR, ELB_DFLT_NUM_NODES, ELB_DFLT_MIN_NUM_NODES
from .elb_config import ElasticBlastConfig
from typing import Optional, List


def enable_gcp_api(cfg: ElasticBlastConfig):
    """ Enable GCP APIs if they are not already enabled 
    parameters:
        cfg: configuration object
    raises:
        SafeExecError if there is an error checking or trying to enable APIs
    """
    dry_run = cfg.cluster.dry_run
    for api in GCP_APIS:
        cmd = 'gcloud services list --enabled --format=value(config.name) '
        cmd += f'--filter=config.name={api}.googleapis.com '
        cmd += f'--project {cfg.gcp.project}'
        if dry_run:
            logging.info(cmd)
        else:
            p = safe_exec(cmd)
            if not p.stdout:
                cmd = f'gcloud services enable {api}.googleapis.com '
                cmd += f'--project {cfg.gcp.project}'
                p = safe_exec(cmd)


def get_gcp_project() -> Optional[str]:
    """Return current GCP project or None if the property is unset.

    Raises:
        util.SafeExecError on problems with command line gcloud
        RuntimeError if gcloud run is successful, but the result is empty"""
    cmd: str = 'gcloud config get-value project'
    p = safe_exec(cmd)
    result: Optional[str]

    # the result should not be empty, for unset properties gcloud returns the
    # string: '(unset)' to stderr
    if not p.stdout and not p.stderr:
        raise RuntimeError('Current GCP project could not be established')

    result = p.stdout.decode().split('\n')[0]

    # return None if project is unset
    if result == '(unset)':
        result = None
    return result


def set_gcp_project(project: str) -> None:
    """Set current GCP project in gcloud environment, raises
    util.SafeExecError on problems with running command line gcloud"""
    cmd = f'gcloud config set project {project}'
    safe_exec(cmd)


def get_disks(cfg: ElasticBlastConfig, dry_run: bool = False) -> List[str]:
    """Return a list of disk names in the current GCP project.
    Raises:
        util.SafeExecError on problems with command line gcloud,
        RuntimeError when gcloud results cannot be parsed"""
    cmd = f'gcloud compute disks list --format json --project {cfg.gcp.project}'
    if dry_run:
        logging.info(cmd)
        return list()

    p = safe_exec(cmd)
    try:
        disks = json.loads(p.stdout.decode())
    except Exception as err:
        raise RuntimeError('Error when parsing listing of GCP disks' + str(err))
    if disks is None:
        raise RuntimeError('Improperly read gcloud disk listing')
    return [i['name'] for i in disks]


def delete_disk(name: str, cfg: ElasticBlastConfig) -> None:
    """Delete a persistent disk.

    Arguments:
        name: Disk name
        cfg: Application config

    Raises:
        util.SafeExecError on problems with command line tools
        ValueError if disk name is empty"""
    if not name:
        raise ValueError('No disk name provided')
    if not cfg:
        raise ValueError('No application config provided')
    cmd = f'gcloud compute disks delete -q {name} --project {cfg.gcp.project}  --zone {cfg.gcp.zone}'
    safe_exec(cmd)


@retry(reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _get_pd_id(cfg: ElasticBlastConfig) -> List[str]:
    """ Try to get the GCP persistent disk ID from elastic-blast records"""
    retval = list()
    if cfg.appstate.disk_id:
        retval = [cfg.appstate.disk_id]
        logging.debug(f'GCP disk ID {retval[0]}')
        # no need to get disk id from GS if we already have it
        return retval

    disk_id_on_gcs = os.path.join(cfg.cluster.results, ELB_METADATA_DIR, ELB_STATE_DISK_ID_FILE)
    cmd = f'gsutil -q stat {disk_id_on_gcs}'
    try:
        safe_exec(cmd)
    except Exception as e:
        logging.debug(f'{disk_id_on_gcs} not found')
        return retval

    cmd = f'gsutil -q cat {disk_id_on_gcs}'
    try:
        p = safe_exec(cmd)
        gcp_disk_id = p.stdout.decode().strip('\n')
        err = p.stderr.decode()
        if gcp_disk_id:
            logging.debug(f"Retrieved GCP disk ID {gcp_disk_id} from {disk_id_on_gcs}")
            try:
                validate_gcp_disk_name(gcp_disk_id)
            except ValueError:
                logging.error(f'GCP disk ID "{gcp_disk_id}" retrieved from {disk_id_on_gcs} is invalid.')
                gcp_disk_id = ''
            else:
                retval.append(gcp_disk_id)
        else:
            raise RuntimeError('Persistent disk id stored in GS is empty')
    except Exception as e:
        logging.error(f'Unable to read {disk_id_on_gcs}: {e}')
        raise

    logging.debug(f'Fetched disk IDs {retval}')
    return retval


def delete_cluster_with_cleanup(cfg: ElasticBlastConfig) -> None:
    """Delete GKE cluster along with persistent disk

    Arguments:
        cfg: Config parameters"""

    dry_run = cfg.cluster.dry_run
    try_kubernetes = True
    pds = []
    try:
        pds = _get_pd_id(cfg)
    except Exception as e:
        logging.error(f'Unable to read disk id from GS: {e}')
    else:
        logging.debug(f'PD id {" ".join(pds)}')

    # detrmine the course of action based on cluster status
    while True:
        status = check_cluster(cfg)
        logging.debug(f'Cluster status {status}')
        if not status:
            return

        if status == 'RUNNING' or status == 'RUNNING_WITH_ERROR':
            break
        # if error, there is something wrong with the cluster, kubernetes will
        # likely not work
        if status == 'ERROR':
            try_kubernetes = False
            break
        # if cluster is provisioning or undergoing software updates, wait
        # until it is active,
        if status == 'PROVISIONING' or status == 'RECONCILING':
            time.sleep(10)
            continue
        # if cluster is already being deleted, nothing to do, exit with an error
        if status == 'STOPPING':
            raise UserReportError(returncode=CLUSTER_ERROR,
                                  message=f"cluster '{cfg.cluster.name}' is already being deleted")

        # for unrecognized cluster status exit the loop and the code below
        # will delete the cluster
        logging.warning(f'Unrecognized cluster status {status}')
        break

    if try_kubernetes:
        try:
            # get credentials for GKE cluster
            get_gke_credentials(cfg)
            kubernetes.check_server(dry_run)
        except Exception as e:
            logging.warning(f'Connection to Kubernetes cluster failed.\tDetails: {e}')
            # Can't do anything kubernetes without cluster credentials
            try_kubernetes = False

    if try_kubernetes:
        try:
            # get cluster's persistent disk in case they leak
            pds = kubernetes.get_persistent_disks(dry_run)
        except Exception as e:
            logging.warning(f'kubernetes.get_persistent_disks failed.\tDetails: {e}')

        try:
            # delete all k8s jobs, persistent volumes and volume claims
            # this should delete persistent disks
            deleted = kubernetes.delete_all(dry_run)
            logging.debug(f'Deleted k8s objects {" ".join(deleted)}')
            disks = get_disks(cfg, dry_run)
            for i in pds:
                if i in disks:
                    logging.debug(f'PD {i} still present after deleteing k8s jobs and PVCs')
                else:
                    logging.debug(f'PD {i} was deleted by deleting k8s PVC')
        except Exception as e:
            # nothing to do the above fails, the code below will take care of
            # persistent disk leak
            logging.warning(f'kubernetes.delete_all failed.\tDetails: {e}')

    delete_cluster(cfg)

    if pds:
        try:
            # delete persistent disks if they are still in GCP, this may be faster
            # than deleting a non-existent disk
            disks = get_disks(cfg, dry_run)
            for i in pds:
                if i in disks:
                    logging.debug(f'PD {i} still present after cluster deletion, deleting again')
                    delete_disk(i, cfg)
        except Exception as e:
            logging.error(getattr(e, 'message', repr(e)))

            # if the above failed, try deleting each disk unconditionally to
            # minimize resource leak
            for i in pds:
                try:
                    delete_disk(i, cfg)
                except Exception as e:
                    logging.error(getattr(e, 'message', repr(e)))
        finally:
            disks = get_disks(cfg, dry_run)
            for i in pds:
                if i in disks:
                    raise UserReportError(returncode=CLUSTER_ERROR,
                                          message=f'ElasticBLAST was not able to delete persistent disk "{i}". Leaving  it may cause additional charges from the cloud provider. You can verify that the disk still exists using this command:\ngcloud compute disks list --project {cfg.gcp.project} | grep {i}\nand delete it with:\ngcloud compute disks delete {i} --project {cfg.gcp.project}')


def get_gke_clusters(cfg: ElasticBlastConfig) -> List[str]:
    """Return a list of GKE cluster names.

    Arguments:
        cfg: configuration object

    Raises:
        util.SafeExecError on problems with command line gcloud
        RuntimeError on problems parsing gcloud JSON output"""
    cmd = f'gcloud container clusters list --format json --project {cfg.gcp.project}'
    p = safe_exec(cmd)
    try:
        clusters = json.loads(p.stdout.decode())
    except Exception as err:
        raise RuntimeError(f'Error when parsing JSON listing of GKE clusters: {str(err)}')
    return [i['name'] for i in clusters]


def get_gke_credentials(cfg: ElasticBlastConfig) -> None:
    """Connect to a GKE cluster.

    Arguments:
        cfg: configuration object

    Raises:
        util.SafeExecError on problems with command line gcloud"""
    cmd: List[str] = 'gcloud container clusters get-credentials'.split()
    cmd.append(cfg.cluster.name)
    cmd.append('--project')
    cmd.append(f'{cfg.gcp.project}')
    cmd.append('--zone')
    cmd.append(f'{cfg.gcp.zone}')
    if cfg.cluster.dry_run:
        logging.info(cmd)
    else:
        safe_exec(cmd)


def check_cluster(cfg: ElasticBlastConfig):
    """ Check if cluster specified by configuration is running.
    Returns cluster status - RUNNING, PROVISIONING, STOPPING, or ERROR -
    if there is such cluster, empty string otherwise.
    All possible exceptions will be passed to upper level.
    """
    cluster_name = cfg.cluster.name
    # FIXME: Consider using
    # gcloud container clusters describe CLUSTER_NAME --format value(status) --project=PROJECT --zone=ZONE
    # The difference is that for non-existing name it will throw an exception, but for long cluster list
    # can be faster (depends on gcloud implementation)
    cmd = f'gcloud container clusters list --format=value(status) --filter name={cluster_name} --project {cfg.gcp.project}'
    retval = ''
    if cfg.cluster.dry_run:
        logging.info(cmd)
    else:
        out = safe_exec(cmd)
        retval = out.stdout.decode('utf-8').strip()
    return retval


def start_cluster(cfg: ElasticBlastConfig):
    """ Starts cluster as specified by configuration.
    All possible exceptions will be passed to upper level.

    Per https://cloud.google.com/kubernetes-engine/docs/how-to/creating-a-regional-cluster#create-regional-single-zone-nodepool
    this function creates a (standard GKE) regional cluster with a single-zone node pool
    """

    cluster_name = ''
    machine_type = ''
    num_nodes = 1

    # .. get values from config and raise exception if missing
    if cfg.cluster.name is not None:
        cluster_name = cfg.cluster.name
    else:
        raise ValueError('Configuration error: missing cluster name in [cluster] sections')
    if cfg.cluster.machine_type is not None:
        machine_type = cfg.cluster.machine_type
    else:
        raise ValueError('Configuration error: missing machine-type in [cluster] sections')
    if cfg.cluster.num_nodes is not None:
        num_nodes = cfg.cluster.num_nodes
    else:
        raise ValueError('Configuration error: missing num-nodes in [cluster] sections')

    # ask for cheaper nodes
    use_preemptible = cfg.cluster.use_preemptible
    use_local_ssd = cfg.cluster.use_local_ssd
    dry_run = cfg.cluster.dry_run

    actual_params = ["gcloud", "container", "clusters", "create", cluster_name]
    actual_params.append('--project')
    actual_params.append(f'{cfg.gcp.project}')
    actual_params.append('--zone')
    actual_params.append(f'{cfg.gcp.zone}')

    actual_params.append('--machine-type')
    actual_params.append(machine_type)

    actual_params.append('--num-nodes')
    actual_params.append(str(ELB_DFLT_MIN_NUM_NODES))
    # Autoscaling configuration
    actual_params.append('--enable-autoscaling')
    actual_params.append('--min-nodes')
    actual_params.append(str(ELB_DFLT_MIN_NUM_NODES))
    actual_params.append('--max-nodes')
    actual_params.append(str(num_nodes))

    if use_preemptible:
        actual_params.append('--preemptible')

    # https://cloud.google.com/stackdriver/pricing
    if cfg.cluster.enable_stackdriver:
        actual_params.append('--enable-stackdriver-kubernetes')

    # ATT: hardcoded parameters
    # specifies GCP API in use
    actual_params.append('--scopes')
    scopes = 'compute-rw,storage-rw,cloud-platform,logging-write,monitoring-write'
    actual_params.append(scopes)

    # FIXME: labels, in future will be provided by config or run-time
    labels = cfg.cluster.labels
    actual_params.append('--labels')
    actual_params.append(labels)

    if use_local_ssd:
        actual_params.append('--local-ssd-count')
        actual_params.append('1')

    if cfg.gcp.network is not None:
        actual_params.append(f'--network={cfg.gcp.network}')
    if cfg.gcp.subnet is not None:
        actual_params.append(f'--subnetwork={cfg.gcp.subnet}')

    start = timer()
    if dry_run:
        logging.info(' '.join(actual_params))
    else:
        safe_exec(actual_params)
    end = timer()
    logging.debug(f'RUNTIME cluster-create {end-start} seconds')

    if use_local_ssd:
        # Label nodes in the cluster for affinity
        cmd = "kubectl get nodes -o jsonpath={.items[*]['metadata.name']}"
        if dry_run:
            logging.info(cmd)
            res = ' '.join([f'gke-node-{i}' for i in range(num_nodes)])
        else:
            proc = safe_exec(cmd)
            res = proc.stdout.decode()
        for i, name in enumerate(res.split()):
            cmd = f'kubectl label nodes {name} ordinal={i}'
            if dry_run:
                logging.info(cmd)
            else:
                safe_exec(cmd)
    return cluster_name


def delete_cluster(cfg: ElasticBlastConfig):
    cluster_name = cfg.cluster.name
    actual_params = ["gcloud", "container", "clusters", "delete", cluster_name]
    actual_params.append('--project')
    actual_params.append(f'{cfg.gcp.project}')
    actual_params.append('--zone')
    actual_params.append(f'{cfg.gcp.zone}')
    actual_params.append('--quiet')
    start = timer()
    if cfg.cluster.dry_run:
        logging.info(actual_params)
    else:
        safe_exec(actual_params)
    end = timer()
    logging.debug(f'RUNTIME cluster-delete {end-start} seconds')
    return cluster_name


def check_prerequisites(cfg: ElasticBlastConfig) -> None:
    """ Check that necessary tools, gcloud, gsutil, and kubectl
    are available if necessary.
    If execution of one of these tools is unsuccessful
    it will throw UserReportError exception."""
    if cfg.cloud_provider.cloud == CSP.GCP:
        try:
            safe_exec('gcloud --version')
        except SafeExecError as e:
            message = f"Required pre-requisite 'gcloud' doesn't work, check installation of GCP SDK.\nDetails: {e.message}"
            raise UserReportError(DEPENDENCY_ERROR, message)
        try:
            # client=true prevents kubectl from addressing server which can be down at the moment
            safe_exec('kubectl version --client=true')
        except SafeExecError as e:
            message = f"Required pre-requisite 'kubectl' doesn't work, check Kubernetes installation.\nDetails: {e.message}"
            raise UserReportError(DEPENDENCY_ERROR, message)
    # FIXME: query files supplied in query-list files should be checked too
    # when EB-780 is done
    # For status checking and cluster deletion blast config is not required.
    queries = cfg.blast.queries_arg if cfg.blast else None
    if (queries and len([i for i in queries.split() if i.startswith('gs://')])) or \
           cfg.cluster.results.startswith('gs://'):
        # Check we have gsutil available
        try:
            safe_exec('gsutil --version')
        except SafeExecError as e:
            message = f"Required pre-requisite 'gsutil' doesn't work, check installation of GCP SDK.\nDetails: {e.message}\nNote: this is because your query is located on GS, you may try another location"
            raise UserReportError(DEPENDENCY_ERROR, message)


def remove_split_query(cfg: ElasticBlastConfig) -> None:
    """ Remove split query from user's results bucket """
    remove_ancillary_data(cfg, ELB_QUERY_BATCH_DIR)


def remove_ancillary_data(cfg: ElasticBlastConfig, bucket_prefix: str) -> None:
    """ Removes ancillary data from the end user's result bucket
    cfg: Configuration object
    bucket_prefix: path that follows the users' bucket name (looks like a file system directory)
    """
    dry_run = cfg.cluster.dry_run
    if cfg.cloud_provider.cloud == CSP.GCP:
        out_path = os.path.join(cfg.cluster.results, bucket_prefix, '*')
        cmd = f'gsutil -mq rm {out_path}'
        if dry_run:
            logging.info(cmd)
        else:
            # This command is a part of clean-up process, there is no benefit in reporting
            # its failure except logging it
            try:
                safe_exec(cmd)
            except SafeExecError as e:
                message = e.message.strip().translate(str.maketrans('\n', '|'))
                logging.warning(message)
    elif cfg.cloud_provider.cloud == CSP.AWS:
        # TODO: implement clean up of S3 bucket from split queries here. EB-508
        pass
