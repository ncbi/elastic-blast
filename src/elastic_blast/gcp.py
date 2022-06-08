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

Authors: Greg Boratyn boratyng@ncbi.nlm.nih.gov
         Yuriy Merezhuk merezhuk@ncbi.nlm.nih.gov
"""

import os
from pathlib import Path
from subprocess import check_call
from tempfile import TemporaryDirectory
import time
import logging
import json
from timeit import default_timer as timer
from typing import Any, DefaultDict, Dict, Optional, List, Tuple
import uuid
from collections import defaultdict
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import MemoryStr, QuerySplittingResults

from .subst import substitute_params

from .filehelper import open_for_write_immediate, open_for_read
from .jobs import read_job_template, write_job_files
from .util import ElbSupportedPrograms, safe_exec, UserReportError, SafeExecError
from .util import validate_gcp_disk_name, get_blastdb_info, get_usage_reporting

from . import kubernetes
from .constants import CLUSTER_ERROR, ELB_NUM_JOBS_SUBMITTED, GCP_APIS, ELB_METADATA_DIR, K8S_JOB_SUBMIT_JOBS
from .constants import ELB_STATE_DISK_ID_FILE, DEPENDENCY_ERROR
from .constants import ELB_QUERY_BATCH_DIR, ELB_DFLT_MIN_NUM_NODES
from .constants import K8S_JOB_CLOUD_SPLIT_SSD, K8S_JOB_INIT_PV
from .constants import K8S_JOB_BLAST, K8S_JOB_GET_BLASTDB, K8S_JOB_IMPORT_QUERY_BATCHES
from .constants import K8S_JOB_LOAD_BLASTDB_INTO_RAM, K8S_JOB_RESULTS_EXPORT, K8S_UNINITIALIZED_CONTEXT
from .constants import ELB_DOCKER_IMAGE_GCP, ELB_QUERY_LENGTH, INPUT_ERROR
from .constants import ElbExecutionMode, ElbStatus
from .constants import GKE_CLUSTER_STATUS_PROVISIONING, GKE_CLUSTER_STATUS_RECONCILING
from .constants import GKE_CLUSTER_STATUS_RUNNING, GKE_CLUSTER_STATUS_RUNNING_WITH_ERROR
from .constants import GKE_CLUSTER_STATUS_STOPPING, GKE_CLUSTER_STATUS_ERROR
from .constants import STATUS_MESSAGE_ERROR
from .elb_config import ElasticBlastConfig
from .elasticblast import ElasticBlast

class ElasticBlastGcp(ElasticBlast):
    """ Implementation of core ElasticBLAST functionality in GCP. """
    def __init__(self, cfg: ElasticBlastConfig, create=False, cleanup_stack: List[Any]=None):
        super().__init__(cfg, create, cleanup_stack)
        self.query_files: List[str] = []
        self.cluster_initialized = False
        self.apis_enabled = False
        self.auto_shutdown = not 'ELB_DISABLE_AUTO_SHUTDOWN' in os.environ

    def cloud_query_split(self, query_files: List[str]) -> None:
        """ Submit the query sequences for splitting to the cloud.
            Initialize cluster with cloud split job
            Parameters:
                query_files     - list files containing query sequence data to split
        """
        if self.dry_run:
            return
        self.query_files = query_files
        logging.debug("Initialize cluster with cloud split")
        self._initialize_cluster()
        self.cluster_initialized = True

    def wait_for_cloud_query_split(self) -> None:
        """ Wait for cloud split """
        if not self.query_files:
            # This is QuerySplitMode.CLIENT - no need to wait
            return
        k8s_ctx = self._get_gke_credentials()
        kubectl = f'kubectl --context={k8s_ctx}'
        job_to_wait = K8S_JOB_CLOUD_SPLIT_SSD if self.cfg.cluster.use_local_ssd else K8S_JOB_INIT_PV

        while True:
            cmd = f"{kubectl} get job {job_to_wait} -o jsonpath=" "'{.items[?(@.status.active)].metadata.name}'"
            if self.dry_run:
                logging.debug(cmd)
                return
            else:
                logging.debug(f'Waiting for job {job_to_wait}')
                proc = safe_exec(cmd)
                res = proc.stdout.decode()
            if not res:
                # Job's not active, check it did not fail
                cmd = f"{kubectl} get job {job_to_wait} -o jsonpath=" "'{.items[?(@.status.failed)].metadata.name}'"
                proc = safe_exec(cmd)
                res = proc.stdout.decode()
                if res:
                    if job_to_wait == K8S_JOB_INIT_PV:
                        # Assume BLASTDB error, as it is more likely to occur than copying files to PV when importing queries
                        msg = 'BLASTDB initialization failed, please run '
                        msg += f'"elastic-blast status --gcp-project {self.cfg.gcp.project} '
                        msg += f'--gcp-region {self.cfg.gcp.region} --gcp-zone '
                        msg += f'{self.cfg.gcp.zone} --results {self.cfg.cluster.name}" '
                        msg += 'for further details'
                    else:
                        msg = 'Cloud query splitting or upload of its results from SSD failed'
                    raise UserReportError(returncode=CLUSTER_ERROR, message=msg)
                else:
                    return
            time.sleep(30)

    def upload_query_length(self, query_length: int) -> None:
        """ Save query length in a metadata file in GS """
        if query_length <= 0: return
        fname = os.path.join(self.cfg.cluster.results, ELB_METADATA_DIR, ELB_QUERY_LENGTH)
        with open_for_write_immediate(fname) as f:
            f.write(str(query_length))
        # Note: if cloud split is used this file is uploaded
        # by the run script in the 1st stage

    def _check_job_number_limit(self, queries: Optional[List[str]], query_length) -> None:
        """ Check that resulting number of jobs does not exceed Kubernetes limit """
        if not queries:
            # Nothing to check, the job number is still unknown
            return
        k8s_job_limit = kubernetes.get_maximum_number_of_allowed_k8s_jobs(self.dry_run)
        if len(queries) > k8s_job_limit:
            batch_len = self.cfg.blast.batch_len
            suggested_batch_len = int(query_length / k8s_job_limit) + 1
            msg = 'Your ElasticBLAST search has failed and its computing resources will be deleted.\n' \
                  f'The batch size specified ({batch_len}) led to creating {len(queries)} kubernetes jobs, which exceeds the limit on number of jobs ({k8s_job_limit}).' \
                  f' Please increase the batch-len parameter to at least {suggested_batch_len} and repeat the search.'
            raise UserReportError(INPUT_ERROR, msg)

    def submit(self, query_batches: List[str], query_length, one_stage_cloud_query_split: bool) -> None:
        """ Submit query batches to cluster
            Parameters:
                query_batches               - list of bucket names of queries to submit
                query_length                - total query length
                one_stage_cloud_query_split - do the query split in the cloud as a part
                                              of executing a regular job """
        # Can't use one stage cloud split for GCP, should never happen
        assert(not one_stage_cloud_query_split)
        if not self.cluster_initialized:
            self._check_job_number_limit(query_batches, query_length)
            self.query_files = []  # No cloud split
            logging.debug("Initialize cluster with NO cloud split")
            self._initialize_cluster()
            self.cluster_initialized = True
        if self.cloud_job_submission:
            kubernetes.submit_job_submission_job(self.cfg)
        else:
            self._generate_and_submit_jobs(query_batches)
            if self.cfg.cluster.num_nodes != 1:
                logging.info('Enable autoscaling')
                cmd = f'gcloud container clusters update {self.cfg.cluster.name} --enable-autoscaling --node-pool default-pool --min-nodes 0 --max-nodes {self.cfg.cluster.num_nodes} --project {self.cfg.gcp.project} --zone {self.cfg.gcp.zone}'
                if self.dry_run:
                    logging.info(cmd)
                else:
                    safe_exec(cmd)
                logging.info('Done enabling autoscaling')

        self.cleanup_stack.clear()
        self.cleanup_stack.append(lambda: kubernetes.collect_k8s_logs(self.cfg))

    def check_status(self, extended=False) -> Tuple[ElbStatus, Dict[str, int], Dict[str, str]]:
        """ Check execution status of ElasticBLAST search
        Parameters:
            extended - do we need verbose information about jobs
        Returns:
            tuple of
                status - cluster status, ElbStatus
                counts - job counts for all job states
                verbose_result - a dictionary with enrties: label, detailed info about jobs
        """
        try:
            return self._check_status(extended)
        except SafeExecError as err:
            # cluster is not valid, return empty result
            msg = err.message.strip()
            logging.info(msg)
            return ElbStatus.UNKNOWN, defaultdict(int), {STATUS_MESSAGE_ERROR: msg} if msg else {}

    def _check_status(self, extended=False) -> Tuple[ElbStatus, Dict[str, int], Dict[str, str]]:
        # We cache only status from gone cluster - it can't change anymore
        if self.cached_status:
            return self.cached_status, self.cached_counts, {STATUS_MESSAGE_ERROR: self.cached_failure_message} if self.cached_failure_message else {}
        counts: DefaultDict[str, int] = defaultdict(int)
        self._enable_gcp_apis()
        status = self._status_from_results()
        if status != ElbStatus.UNKNOWN:
            return status, self.cached_counts, {STATUS_MESSAGE_ERROR: self.cached_failure_message} if self.cached_failure_message else {}

        gke_status = check_cluster(self.cfg)
        if not gke_status:
            return ElbStatus.UNKNOWN, {}, {STATUS_MESSAGE_ERROR: f'Cluster "{self.cfg.cluster.name}" was not found'}

        logging.debug(f'GKE status: {gke_status}')
        if gke_status in [GKE_CLUSTER_STATUS_RECONCILING, GKE_CLUSTER_STATUS_PROVISIONING]:
            return ElbStatus.SUBMITTING, {}, {}

        if gke_status == GKE_CLUSTER_STATUS_STOPPING:
            # TODO: This behavior is consistent with current tests, consider returning a value
            # as follows, and changing test in tests/app/test_elasticblast.py::test_cluster_error
            # return ElbStatus.DELETING, {}, ''
            raise UserReportError(returncode=CLUSTER_ERROR,
                            message=f'Cluster "{self.cfg.cluster.name}" exists, but is not responding. '
                                'It may be still initializing, please try checking status again in a few minutes.')

        k8s_ctx = self._get_gke_credentials()
        selector = 'app=blast'
        kubectl = f'kubectl --context={k8s_ctx}'

        # if we need name of the job in the future add NAME:.metadata.name to custom-columns
        # get status of jobs (pending/running, succeeded, failed)
        cmd = f'{kubectl} get jobs -o custom-columns=STATUS:.status.conditions[0].type -l {selector}'.split()
        if self.dry_run:
            logging.debug(cmd)
        else:
            proc = safe_exec(cmd)
            for line in proc.stdout.decode().split('\n'):
                if not line or line.startswith('STATUS'):
                    continue
                if line.startswith('Complete'):
                    counts['succeeded'] += 1
                elif line.startswith('Failed'):
                    counts['failed'] += 1
                else:
                    counts['pending'] += 1
                
        # get number of running pods
        cmd = f'{kubectl} get pods -o custom-columns=STATUS:.status.phase -l {selector}'.split()
        if self.dry_run:
            logging.info(cmd)
        else:
            proc = safe_exec(cmd)
            for line in proc.stdout.decode().split('\n'):
                if line == 'Running':
                    counts['running'] += 1

        # correct number of pending jobs: running jobs were counted twice,
        # as running and pending
        counts['pending'] -= counts['running']
        status = ElbStatus.UNKNOWN
        if counts['failed'] > 0:
            status = ElbStatus.FAILURE
        elif counts['running'] > 0 or counts['pending'] > 0:
            status = ElbStatus.RUNNING
        elif counts['succeeded']:
            status = ElbStatus.SUCCESS
        else:
            # check init-pv and submit-jobs status
            status = ElbStatus.SUBMITTING
            pending, succeeded, failed = self._job_status_by_app('setup')
            if failed > 0:
                status = ElbStatus.FAILURE
            elif pending == 0:
                pending, succeeded, failed = self._job_status_by_app('submit')
                if failed > 0:
                    status = ElbStatus.FAILURE

        return status, counts, {}
    
    def _job_status_by_app(self, app):
        """ get status of jobs (pending/running, succeeded, failed) by app """
        pending = 0
        succeeded = 0
        failed = 0
        selector = f'app={app}'
        k8s_ctx = self._get_gke_credentials()
        kubectl = f'kubectl --context={k8s_ctx}'
        cmd = f'{kubectl} get jobs -o custom-columns=STATUS:.status.conditions[0].type -l {selector}'.split()
        if self.dry_run:
            logging.debug(cmd)
        else:
            try:
                proc = safe_exec(cmd)
            except SafeExecError as err:
                logging.debug(f'Error "{err.message}" in command "{cmd}"')
                return 0, 0, 0
            for line in proc.stdout.decode().split('\n'):
                if not line or line.startswith('STATUS'):
                    continue
                if line.startswith('Complete'):
                    succeeded += 1
                elif line.startswith('Failed'):
                    failed += 1
                else:
                    pending += 1
        return pending, succeeded, failed


    def delete(self):
        enable_gcp_api(self.cfg)
        delete_cluster_with_cleanup(self.cfg)

    def _initialize_cluster(self):
        """ Creates a k8s cluster, connects to it and initializes the persistent disk """
        cfg, query_files, clean_up_stack = self.cfg, self.query_files, self.cleanup_stack
        pd_size = MemoryStr(cfg.cluster.pd_size).asGB()
        disk_limit, disk_usage = self.get_disk_quota()
        disk_quota = disk_limit - disk_usage
        if pd_size > disk_quota:
            raise UserReportError(INPUT_ERROR, f'Requested disk size {pd_size}G is larger than allowed ({disk_quota}G) for region {cfg.gcp.region}\n'
                'Please adjust parameter [cluster] pd-size to less than {disk_quota}G, run your request in another region, or\n'
                'request a disk quota increase (see https://cloud.google.com/compute/quotas)')
        logging.info('Starting cluster')
        clean_up_stack.append(lambda: logging.debug('Before creating cluster'))
        clean_up_stack.append(lambda: delete_cluster_with_cleanup(cfg))
        clean_up_stack.append(lambda: kubernetes.collect_k8s_logs(cfg))
        if self.cloud_job_submission:
            subs = self.job_substitutions()
            job_template = read_job_template(cfg=cfg)
            s = substitute_params(job_template, subs)
            bucket_job_template = os.path.join(cfg.cluster.results, ELB_METADATA_DIR, 'job.yaml.template')
            with open_for_write_immediate(bucket_job_template) as f:
                f.write(s)
        start_cluster(cfg)
        clean_up_stack.append(lambda: logging.debug('After creating cluster'))

        self._get_gke_credentials()

        self._label_nodes()

        if self.cloud_job_submission or self.auto_shutdown:
            kubernetes.enable_service_account(cfg)

        logging.info('Initializing storage')
        clean_up_stack.append(lambda: logging.debug('Before initializing storage'))
        kubernetes.initialize_storage(cfg, query_files,
            ElbExecutionMode.NOWAIT if self.cloud_job_submission else ElbExecutionMode.WAIT)
        clean_up_stack.append(lambda: logging.debug('After initializing storage'))

        if not self.auto_shutdown:
            logging.debug('Disabling janitor')
        else:
            kubernetes.submit_janitor_cronjob(cfg)

    def _label_nodes(self):
        """ Label nodes by ordinal numbers for proper initialization.

            When we use local SSD the storage of each node should be
            initialized individually (as opposed to the case of persistent
            volumes). For this we create number of jobs and assign every init-ssd
            job to corresponding node using affinity label of form ordinal:{number}.
            See src/elastic_blast/templates/job-init-local-ssd.yaml.template
        """
        use_local_ssd = self.cfg.cluster.use_local_ssd
        dry_run = self.cfg.cluster.dry_run
        k8s_ctx = self._get_gke_credentials()
        kubectl = f'kubectl --context={k8s_ctx}'
        if use_local_ssd:
            # Label nodes in the cluster for affinity
            cmd = kubectl + " get nodes -o jsonpath={.items[*]['metadata.name']}"
            if dry_run:
                logging.info(cmd)
                res = ' '.join([f'gke-node-{i}' for i in range(self.cfg.cluster.num_nodes)])
            else:
                proc = safe_exec(cmd)
                res = proc.stdout.decode()
            for i, name in enumerate(res.split()):
                cmd = f'{kubectl} label nodes {name} ordinal={i}'
                if dry_run:
                    logging.info(cmd)
                else:
                    safe_exec(cmd)

    def job_substitutions(self) -> Dict[str, str]:
        """ Prepare substitution dictionary for job generation """
        cfg = self.cfg
        usage_reporting = get_usage_reporting()

        db, _, db_label = get_blastdb_info(cfg.blast.db)

        blast_program = cfg.blast.program

        # prepare substitution for current template
        # TODO consider template using cfg variables directly as, e.g. ${blast.program}
        subs = {
            'ELB_BLAST_PROGRAM': blast_program,
            'ELB_DB': db,
            'ELB_DB_LABEL': db_label,
            'ELB_MEM_REQUEST': str(cfg.cluster.mem_request),
            'ELB_MEM_LIMIT': str(cfg.cluster.mem_limit),
            'ELB_BLAST_OPTIONS': cfg.blast.options,
            # FIXME: EB-210
            'ELB_BLAST_TIMEOUT': str(cfg.timeouts.blast_k8s * 60),
            'ELB_RESULTS': cfg.cluster.results,
            'ELB_NUM_CPUS': str(cfg.cluster.num_cpus),
            'ELB_DB_MOL_TYPE': str(ElbSupportedPrograms().get_db_mol_type(blast_program)),
            'ELB_DOCKER_IMAGE': ELB_DOCKER_IMAGE_GCP,
            'ELB_TIMEFMT': '%s%N',  # timestamp in nanoseconds
            'BLAST_ELB_JOB_ID': uuid.uuid4().hex,
            'BLAST_USAGE_REPORT': str(usage_reporting).lower(),
            'K8S_JOB_GET_BLASTDB' : K8S_JOB_GET_BLASTDB,
            'K8S_JOB_LOAD_BLASTDB_INTO_RAM' : K8S_JOB_LOAD_BLASTDB_INTO_RAM,
            'K8S_JOB_IMPORT_QUERY_BATCHES' : K8S_JOB_IMPORT_QUERY_BATCHES,
            'K8S_JOB_SUBMIT_JOBS' : K8S_JOB_SUBMIT_JOBS,
            'K8S_JOB_BLAST' : K8S_JOB_BLAST,
            'K8S_JOB_RESULTS_EXPORT' : K8S_JOB_RESULTS_EXPORT
        }
        return subs


    def _generate_and_submit_jobs(self, queries: List[str]):
        cfg, clean_up_stack = self.cfg, self.cleanup_stack
        subs = self.job_substitutions()
        job_template_text = read_job_template(cfg=cfg)
        with TemporaryDirectory() as job_path:
            job_files = write_job_files(job_path, 'batch_', job_template_text, queries, **subs)
            logging.debug(f'Generated {len(job_files)} job files')
            if len(job_files) > 0:
                logging.debug(f'Job #1 file: {job_files[0]}')
                logging.debug('Command to run in the pod:')
                with open(job_files[0]) as f:
                    for line in f:
                        if line.find('-query') >= 0:
                            logging.debug(line.strip())
                            break

            logging.info('Submitting jobs to cluster')
            clean_up_stack.append(lambda: logging.debug('Before submission computational jobs'))
            # Should never happen, cfg.appstate.k8s_ctx should always be initialized properly
            # by the time of this call 
            assert(cfg.appstate.k8s_ctx)
            start = timer()
            job_names = kubernetes.submit_jobs(cfg.appstate.k8s_ctx, Path(job_path), dry_run=self.dry_run)
            end = timer()
            logging.debug(f'RUNTIME submit-jobs {end-start} seconds')
            logging.debug(f'SPEED to submit-jobs {len(job_names)/(end-start):.2f} jobs/second')
            clean_up_stack.append(lambda: logging.debug('After submission computational jobs'))
            if job_names:
                logging.debug(f'Job #1 name: {job_names[0]}')
            # Signal janitor job to start checking for results
            with open_for_write_immediate(os.path.join(cfg.cluster.results, ELB_METADATA_DIR, ELB_NUM_JOBS_SUBMITTED)) as f:
                f.write(str(len(job_names)))


    def get_disk_quota(self) -> Tuple[float, float]:
        """ Get the Persistent Disk SSD quota (SSD_TOTAL_GB)
            Returns tuple of limit and usage in GB """
        cmd = f'gcloud compute regions describe {self.cfg.gcp.region} --project {self.cfg.gcp.project} --format json'
        limit = 1e9
        usage = 0.0
        if self.cfg.cluster.dry_run:
            logging.info(cmd)
        else:
            # The execution of this command requires serviceusage.quotas.get permission
            # so it can be unsuccessful for some users
            p = safe_exec(cmd)
            if p.stdout:
                res = json.loads(p.stdout.decode())
                if 'quotas' in res:
                    for quota in res['quotas']:
                        if quota['metric'] == 'SSD_TOTAL_GB':
                            limit = float(quota['limit'])
                            usage = float(quota['usage'])
                            break
        return limit, usage

    def _enable_gcp_apis(self) -> None:
        """ Enables GCP APIs only once per object initialization """
        if not self.apis_enabled:
            enable_gcp_api(self.cfg)
            self.apis_enabled = True

    def _get_gke_credentials(self) -> str:
        """ Memoized get_gke_credentials """
        if not self.cfg.appstate.k8s_ctx:
            self.cfg.appstate.k8s_ctx = get_gke_credentials(self.cfg)
        return self.cfg.appstate.k8s_ctx

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

    # determine the course of action based on cluster status
    while True:
        status = check_cluster(cfg)
        if not status:
            msg = f'Cluster {cfg.cluster.name} was not found'
            if cfg.cluster.dry_run:
                logging.error(msg)
                return
            else:
                # TODO: to avoid this hack make delete_cluster_with_cleanup
                # a method of ElasticBlastGcp
                elastic_blast = ElasticBlastGcp(cfg, False)
                status = elastic_blast._status_from_results()
                if status == ElbStatus.UNKNOWN:
                    raise UserReportError(returncode=CLUSTER_ERROR, message=msg)
                # Check for status of gone cluster, delete data if
                # necessary
                remove_split_query(cfg)
                return
                
        logging.debug(f'Cluster status "{status}"')

        if status == GKE_CLUSTER_STATUS_RUNNING or status == GKE_CLUSTER_STATUS_RUNNING_WITH_ERROR:
            break
        # if error, there is something wrong with the cluster, kubernetes will
        # likely not work
        if status == GKE_CLUSTER_STATUS_ERROR:
            try_kubernetes = False
            break
        # if cluster is provisioning or undergoing software updates, wait
        # until it is active,
        if status == GKE_CLUSTER_STATUS_PROVISIONING or status == GKE_CLUSTER_STATUS_RECONCILING:
            time.sleep(10)
            continue
        # if cluster is already being deleted, nothing to do, exit with an error
        if status == GKE_CLUSTER_STATUS_STOPPING:
            raise UserReportError(returncode=CLUSTER_ERROR,
                                  message=f"cluster '{cfg.cluster.name}' is already being deleted")

        # for unrecognized cluster status exit the loop and the code below
        # will delete the cluster
        logging.warning(f'Unrecognized cluster status {status}')
        break

    if try_kubernetes:
        try:
            cfg.appstate.k8s_ctx = get_gke_credentials(cfg)
            kubernetes.check_server(cfg.appstate.k8s_ctx, dry_run)
        except Exception as e:
            logging.warning(f'Connection to Kubernetes cluster failed.\tDetails: {e}')
            # Can't do anything kubernetes without cluster credentials
            try_kubernetes = False

    if try_kubernetes:
        k8s_ctx = cfg.appstate.k8s_ctx
        # This should never happen when calling the elastic-blast script, as
        # the k8s context is set as part of calling gcloud container clusters get credentials
        # This check is to pacify the mypy type checker and to alert those
        # using the API directly of missing pre-conditions
        assert(k8s_ctx)

        try:
            # get cluster's persistent disk in case they leak
            pds = kubernetes.get_persistent_disks(k8s_ctx, dry_run)
        except Exception as e:
            logging.warning(f'kubernetes.get_persistent_disks failed.\tDetails: {e}')

        try:
            # delete all k8s jobs, persistent volumes and volume claims
            # this should delete persistent disks
            deleted = kubernetes.delete_all(k8s_ctx, dry_run)
            logging.debug(f'Deleted k8s objects {" ".join(deleted)}')
            disks = get_disks(cfg, dry_run)
            for i in pds:
                if i in disks:
                    logging.debug(f'PD {i} still present after deleting k8s jobs and PVCs')
                else:
                    logging.debug(f'PD {i} was deleted by deleting k8s PVC')
        except Exception as e:
            # nothing to do the above fails, the code below will take care of
            # persistent disk leak
            logging.warning(f'kubernetes.delete_all failed.\tDetails: {e}')

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
                    msg = f'ElasticBLAST was not able to delete persistent disk "{i}". ' \
                        'Leaving it may cause additional charges from the cloud provider. ' \
                        'You can verify that the disk still exists using this command:\n' \
                        f'gcloud compute disks list --project {cfg.gcp.project} | grep {i}\n' \
                        f'and delete it with:\ngcloud compute disks delete {i} --project {cfg.gcp.project} --zone {cfg.gcp.zone}'
                    logging.error(msg)
                    # Remove the exception for now, as we want to delete the cluster always!
                    #raise UserReportError(returncode=CLUSTER_ERROR, msg)

    remove_split_query(cfg)
    delete_cluster(cfg)


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


def get_gke_credentials(cfg: ElasticBlastConfig) -> str:
    """Connect to a GKE cluster.

    Arguments:
        cfg: configuration object

    Returns:
        The kubernetes current context

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

    cmd = 'kubectl config current-context'.split()
    retval = K8S_UNINITIALIZED_CONTEXT
    if cfg.cluster.dry_run:
        logging.info(cmd)
    else:
        p = safe_exec(cmd)
        retval = p.stdout.decode().strip()
    return retval


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
    actual_params.append('--no-enable-autoupgrade')
    #actual_params.append('--no-enable-ip-alias')
    actual_params.append('--project')
    actual_params.append(f'{cfg.gcp.project}')
    actual_params.append('--zone')
    actual_params.append(f'{cfg.gcp.zone}')

    actual_params.append('--machine-type')
    actual_params.append(machine_type)

    actual_params.append('--num-nodes')
    # Autoscaling for clusters with local SSD works only by shrinking
    # so to support it we start cluster with maximum nodes.
    # Thus the nodes are properly initialized and autoscaler
    # later can remove them if/when they're not needed.
    if use_local_ssd:
        actual_params.append(str(cfg.cluster.num_nodes))
    else:
        actual_params.append(str(ELB_DFLT_MIN_NUM_NODES))

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

    if cfg.gcp.gke_version:
        actual_params.append('--cluster-version')
        actual_params.append(f'{cfg.gcp.gke_version}')
        actual_params.append('--node-version')
        actual_params.append(f'{cfg.gcp.gke_version}')

    start = timer()
    if dry_run:
        logging.info(' '.join(actual_params))
    else:
        safe_exec(actual_params)
    end = timer()
    logging.debug(f'RUNTIME cluster-create {end-start} seconds')

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


def check_prerequisites() -> None:
    """ Check that necessary tools, gcloud, gsutil, and kubectl
    are available if necessary.
    If execution of one of these tools is unsuccessful
    it will throw UserReportError exception."""
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
    # Check we have gsutil available
    try:
        safe_exec('gsutil --version')
    except SafeExecError as e:
        message = f"Required pre-requisite 'gsutil' doesn't work, check installation of GCP SDK.\nDetails: {e.message}\nNote: this is because your query is located on GS, you may try another location"
        raise UserReportError(DEPENDENCY_ERROR, message)


def remove_split_query(cfg: ElasticBlastConfig) -> None:
    """ Remove split query from user's results bucket """
    _remove_ancillary_data(cfg, ELB_QUERY_BATCH_DIR)


def _remove_ancillary_data(cfg: ElasticBlastConfig, bucket_prefix: str) -> None:
    """ Removes ancillary data from the end user's result bucket
    cfg: Configuration object
    bucket_prefix: path that follows the users' bucket name (looks like a file system directory)
    """
    dry_run = cfg.cluster.dry_run
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

