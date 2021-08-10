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
elb/commands/submit.py - Command to submit ElasticBLAST searches

Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
Created: Wed 22 Apr 2020 06:31:30 AM EDT
"""
import os, re
import logging
import math
from tempfile import TemporaryDirectory, NamedTemporaryFile
from pathlib import Path
from timeit import default_timer as timer
import uuid
from typing import List, Tuple, Any
from pprint import pformat

from elastic_blast.resources.quotas.quota_check import check_resource_quotas
from elastic_blast.aws import ElasticBlastAws
from elastic_blast.aws import check_cluster as aws_check_cluster
from elastic_blast.filehelper import open_for_read, open_for_read_iter, copy_to_bucket
from elastic_blast.filehelper import check_for_read, check_dir_for_write, cleanup_temp_bucket_dirs
from elastic_blast.filehelper import get_length, harvest_query_splitting_results
from elastic_blast.filehelper import upload_file_to_gcs
from elastic_blast.object_storage_utils import write_to_s3
from elastic_blast.split import FASTAReader
from elastic_blast.jobs import read_job_template, write_job_files
from elastic_blast.gcp import get_gke_credentials, delete_cluster_with_cleanup
from elastic_blast.gcp import enable_gcp_api, start_cluster
from elastic_blast.gcp import check_cluster as gcp_check_cluster
from elastic_blast.gcp import remove_split_query
from elastic_blast.gcp_traits import get_machine_properties
from elastic_blast.kubernetes import initialize_storage, submit_jobs
from elastic_blast.kubernetes import get_logs, get_maximum_number_of_allowed_k8s_jobs
from elastic_blast.status import get_status
from elastic_blast.util import get_blastdb_size, UserReportError, ElbSupportedPrograms
from elastic_blast.util import get_blastdb_info
from elastic_blast.util import get_usage_reporting
from elastic_blast.constants import ELB_AWS_JOB_IDS, ELB_METADATA_DIR, ELB_STATE_DISK_ID_FILE, K8S_JOB_BLAST, K8S_JOB_GET_BLASTDB, K8S_JOB_RESULTS_EXPORT, QuerySplitMode
from elastic_blast.constants import K8S_JOB_IMPORT_QUERY_BATCHES, K8S_JOB_LOAD_BLASTDB_INTO_RAM
from elastic_blast.constants import ELB_QUERY_BATCH_DIR, BLASTDB_ERROR, INPUT_ERROR
from elastic_blast.constants import PERMISSIONS_ERROR, CLUSTER_ERROR, CSP
from elastic_blast.constants import ELB_DOCKER_IMAGE_GCP, QUERY_LIST_EXT
from elastic_blast.constants import ElbCommand, ELB_METADATA_DIR, ELB_META_CONFIG_FILE
from elastic_blast.constants import ELB_S3_PREFIX, ELB_GCS_PREFIX
from elastic_blast.taxonomy import setup_taxid_filtering
from elastic_blast.config import validate_cloud_storage_object_uri
from elastic_blast.elb_config import ElasticBlastConfig


def get_query_split_mode(cfg: ElasticBlastConfig, query_files):
    """ Determine query split mode """
    # Case for cloud split on AWS: one file on S3
    # TODO EB-1156: add one file on GCP
    eligible_for_cloud_query_split = False
    if cfg.cloud_provider.cloud == CSP.AWS and len(query_files) == 1 and \
       query_files[0].startswith(ELB_S3_PREFIX):
        eligible_for_cloud_query_split = True

    use_1_stage_cloud_split = False
    use_2_stage_cloud_split = False

    if eligible_for_cloud_query_split:
        if 'ELB_USE_1_STAGE_CLOUD_SPLIT' in os.environ:
            use_1_stage_cloud_split = True
        if 'ELB_USE_2_STAGE_CLOUD_SPLIT' in os.environ:
            use_2_stage_cloud_split = True

    if use_1_stage_cloud_split and use_2_stage_cloud_split:
        err = 'Cannot configure both 1- and 2-stage cloud query splitting'
        raise UserReportError(returncode=INPUT_ERROR, message=str(err))

    if use_1_stage_cloud_split:
        return QuerySplitMode.CLOUD_ONE_STAGE
    elif use_2_stage_cloud_split:
        return QuerySplitMode.CLOUD_TWO_STAGE
    else:
        return QuerySplitMode.CLIENT


def prepare_1_stage(cfg: ElasticBlastConfig, query_files):
    """ Prepare data for 1 stage cloud query split on AWS """
    query_file = query_files[0]
    # Get file length as approximation of sequence length
    query_length = get_length(query_file)
    if query_file.endswith('.gz'):
        query_length = query_length * 4 # approximation again
    batch_len = cfg.blast.batch_len
    nbatch = math.ceil(query_length/batch_len)
    queries = nbatch * [query_file]
    return queries


def generate_and_submit_jobs(cfg, queries, clean_up_stack):
    dry_run = cfg.cluster.dry_run

    usage_reporting = get_usage_reporting()

    db, db_path, db_label = get_blastdb_info(cfg.blast.db)

    # Job generation
    blast_program = cfg.blast.program

    # prepare substitution for current template
    # TODO consider template using cfg variables directly as, e.g. ${blast.program}
    subs = {
        'ELB_BLAST_PROGRAM': blast_program,
        'ELB_DB': db,
        'ELB_DB_LABEL': db_label,
        'ELB_MEM_REQUEST': str(cfg.blast.mem_request),
        'ELB_MEM_LIMIT': str(cfg.blast.mem_limit),
        'ELB_BLAST_OPTIONS': cfg.blast.options,
        # FIXME: EB-210
        'ELB_BLAST_TIMEOUT': str(cfg.timeouts.blast_k8s * 60),
        'BUCKET': cfg.cluster.results,
        'ELB_NUM_CPUS': str(cfg.cluster.num_cpus),
        'ELB_DB_MOL_TYPE': str(ElbSupportedPrograms().get_db_mol_type(blast_program)),
        'ELB_DOCKER_IMAGE': ELB_DOCKER_IMAGE_GCP,
        'ELB_TIMEFMT': '%s%N',  # timestamp in nanoseconds
        'BLAST_ELB_JOB_ID': uuid.uuid4().hex,
        'BLAST_USAGE_REPORT': str(usage_reporting).lower(),
        'K8S_JOB_GET_BLASTDB' : K8S_JOB_GET_BLASTDB,
        'K8S_JOB_LOAD_BLASTDB_INTO_RAM' : K8S_JOB_LOAD_BLASTDB_INTO_RAM,
        'K8S_JOB_IMPORT_QUERY_BATCHES' : K8S_JOB_IMPORT_QUERY_BATCHES,
        'K8S_JOB_BLAST' : K8S_JOB_BLAST,
        'K8S_JOB_RESULTS_EXPORT' : K8S_JOB_RESULTS_EXPORT
    }

    job_template_text = read_job_template(cfg=cfg)
    with TemporaryDirectory() as job_path:
        job_files = write_job_files(job_path, 'batch_', job_template_text, queries, **subs)
        logging.debug('Generated %d job files', len(job_files))
        logging.debug(f'Job #1 file: {job_files[0]}')
        logging.debug('Command to run in the pod:')
        with open(job_files[0]) as f:
            for line in f:
                if line.find('-query') >= 0:
                    logging.debug(line.strip())
                    break

        logging.info('Submitting jobs to cluster')
        clean_up_stack.append(lambda: logging.debug('Before submission computational jobs'))
        job_names = submit_jobs(Path(job_path), dry_run=dry_run)
        clean_up_stack.append(lambda: logging.debug('After submission computational jobs'))
        if job_names:
            logging.debug(f'Job #1 name: {job_names[0]}')


def check_job_number_limit(cfg, queries, query_length):
    dry_run = cfg.cluster.dry_run

    k8s_job_limit = get_maximum_number_of_allowed_k8s_jobs(dry_run)
    if len(queries) > k8s_job_limit:
        batch_len = cfg.blast.batch_len
        suggested_batch_len = int(query_length / k8s_job_limit) + 1
        msg = f'The batch size specified ({batch_len}) led to creating {len(queries)} kubernetes jobs, which exceeds the limit on number of jobs ({k8s_job_limit}). Please increase the batch-len parameter to at least {suggested_batch_len}.'
        raise UserReportError(INPUT_ERROR, msg)


# TODO: use cfg only when args.wait, args.sync, and args.run_label are replicated in cfg
def submit(args, cfg, clean_up_stack):
    """ Entry point to submit an ElasticBLAST search
    """
    dry_run = cfg.cluster.dry_run
    cfg.validate(ElbCommand.SUBMIT, dry_run)

    # For now, checking resources is only implemented for AWS
    if cfg.cloud_provider.cloud == CSP.AWS:
        if not dry_run:
            check_resource_quotas(cfg)
    else:
        enable_gcp_api(cfg)
    
    if check_running_cluster(cfg):
        raise UserReportError(CLUSTER_ERROR,
            'An ElasticBLAST search that will write results to '
            f'{cfg.cluster.results} has already been submitted.\n'
            'Please resubmit your search with a different value '
            'for "results" configuration parameter or delete '
            'the previous ElasticBLAST search by running elastic-blast delete.')

    query_files = assemble_query_file_list(cfg)
    check_submit_data(query_files, cfg)
    if not dry_run:
        # FIXME: refactor this code into object_storage_utils
        cfg_text = pformat(cfg.asdict())
        dst = os.path.join(cfg.cluster.results, ELB_METADATA_DIR, ELB_META_CONFIG_FILE)
        if cfg.cloud_provider.cloud == CSP.AWS:
            write_to_s3(dst, cfg_text)
        else:
            with NamedTemporaryFile('wt') as tmpcfg:
                tmpcfg.write(cfg_text)
                tmpcfg.flush()
                upload_file_to_gcs(tmpcfg.name, dst)

    #mode_str = "synchronous" if args.sync else "asynchronous"
    #logging.info(f'Running ElasticBLAST on {cfg.cloud_provider.cloud.name} in {mode_str} mode')

    queries = None
    query_length = 0

    query_split_mode = get_query_split_mode(cfg, query_files)

    if query_split_mode == QuerySplitMode.CLIENT:
        clean_up_stack.append(cleanup_temp_bucket_dirs)
        queries, query_length = split_query(query_files, cfg)
    elif query_split_mode == QuerySplitMode.CLOUD_ONE_STAGE:
        queries = prepare_1_stage(query_files)

    # setup taxonomy filtering, if requested
    setup_taxid_filtering(cfg)

    # check database availability
    try:
        get_blastdb_size(cfg.blast.db, cfg.blast.db_source)
    except ValueError as err:
        raise UserReportError(returncode=BLASTDB_ERROR, message=str(err))

    # FIXME: this is a temporary code arrangement
    if cfg.cloud_provider.cloud == CSP.AWS:
        elastic_blast = ElasticBlastAws(cfg, create=True)
        if query_split_mode == QuerySplitMode.CLOUD_TWO_STAGE:
            elastic_blast.split_query(query_files)
            elastic_blast.wait_for_cloud_query_split()
            if 'ELB_NO_SEARCH' in os.environ: return 0
            qs_res = harvest_query_splitting_results(cfg.cluster.results, dry_run)
            queries = qs_res.query_batches
        upload_split_query_to_bucket(cfg, clean_up_stack, dry_run)
        elastic_blast.upload_query_length(query_length)
        elastic_blast.submit(queries, query_split_mode == QuerySplitMode.CLOUD_ONE_STAGE)
        return 0

    # This is the rest of GCP submit code which will be wrapped into methods
    # of ElasticBlastGcp similar to ElasticBlastAws 

    if query_split_mode == QuerySplitMode.CLIENT:
        check_job_number_limit(cfg, queries, query_length)

    # check_memory_requirements(cfg)  # FIXME: EB-281, EB-313

    upload_split_query_to_bucket(cfg, clean_up_stack, dry_run)
    # TODO: pass 2 stage cloud query split flag to initialize_cluster,
    # get query batches into queries variable back (analog of harvest_query_splitting_results)
    initialize_cluster(cfg, [], clean_up_stack)

    generate_and_submit_jobs(cfg, queries, clean_up_stack)


    # Sync mode disabled per EB-700
    #if args.sync:
    #    while True:
    #        try:
    #            pending, running, succeeded, failed = get_status(args.run_label, dry_run=dry_run)
    #        except RuntimeError as e:
    #            returncode = e.args[0]
    #            logging.error(f'Error while getting job status: {e.args[1]}, returncode: {returncode}')
    #            # TODO: maybe analyze situation in more details here. It happens when kubectl can't be found
    #            # or cluster connection can't be established. If the latter, maybe try to get GKE credentials again
    #        except ValueError as e:
    #            returncode = 1
    #            logging.error(f'Error while getting job status: {e}')
    #            # This error happens when run-label is malformed, it will not repair, so exit here
    #            break
    #        else:
    #            if pending + running:
    #                logging.debug(f'Pending {pending}, Running {running}, Succeeded {succeeded}, Failed {failed}')
    #            else:
    #                logging.info(f'Done: {succeeded} jobs succeeded, {failed} jobs failed')
    #                break
    #        time.sleep(20)  # TODO: make this a parameter (granularity)
    #    logging.info('Deleting cluster')
    #else:
    clean_up_stack.clear()
    clean_up_stack.append(lambda: collect_k8s_logs(cfg))
    return 0


def check_running_cluster(cfg: ElasticBlastConfig) -> bool:
    """ Check that the cluster with same name as configured is
        not already running and that results bucket doesn't have
        metadata directory

        Returns: true if cluster is running or results are used
                 false if neither cluster is running nor results
                 are present
    """
    if cfg.cluster.dry_run:
        return False
    metadata_dir = os.path.join(cfg.cluster.results, ELB_METADATA_DIR)
    if cfg.cloud_provider.cloud == CSP.AWS:
        metadata_file = os.path.join(metadata_dir, ELB_AWS_JOB_IDS)
    else:
        metadata_file = os.path.join(metadata_dir, ELB_STATE_DISK_ID_FILE)
    try:
        check_for_read(metadata_file)
        return True
    except FileNotFoundError:
        pass
    if cfg.cloud_provider.cloud == CSP.AWS:
        return aws_check_cluster(cfg)
    else:
        status = gcp_check_cluster(cfg)
        if status:
            logging.error(f'Previous instance of cluster {cfg.cluster.name} is still {status}')
            return True
        return False


def initialize_cluster(cfg: ElasticBlastConfig, query_files, clean_up_stack):
    """ Creates a k8s cluster, connects to it and initializes the persistent disk"""
    logging.info('Starting cluster')
    clean_up_stack.append(lambda: logging.debug('Before creating cluster'))
    clean_up_stack.append(lambda: delete_cluster_with_cleanup(cfg))
    clean_up_stack.append(lambda: collect_k8s_logs(cfg))
    start_cluster(cfg)
    clean_up_stack.append(lambda: logging.debug('After creating cluster'))

    get_gke_credentials(cfg)

    logging.info('Initializing storage')
    clean_up_stack.append(lambda: logging.debug('Before initializing storage'))
    initialize_storage(cfg, query_files)
    clean_up_stack.append(lambda: logging.debug('After initializing storage'))


def are_files_on_localhost(query_files: List[str]) -> bool:
    """ Return true if all files refer to a local file, otherwise false.
        Does not check for file existence, as this is checked in
        check_submit_data->check_for_read
    """
    pattern = re.compile(r'^(gs://|s3://|ftp://|https://|http://)')
    for query_file in query_files:
        if pattern.match(query_file):
            return False
    return True


def check_submit_data(query_files: List[str], cfg: ElasticBlastConfig) -> None:
    """ Check that the query files are present and readable and that results bucket is writeable
        Parameters:
           query_files - list of query files
           cfg - configuration holding information about source query and results bucket
    """
    dry_run = cfg.cluster.dry_run
    try:
        for query_file in query_files:
            check_for_read(query_file, dry_run)
    except FileNotFoundError:
        raise UserReportError(INPUT_ERROR, f'Query input {query_file} is not readable or does not exist')
    bucket = cfg.cluster.results
    try:
        check_dir_for_write(bucket, dry_run)
    except PermissionError:
        raise UserReportError(PERMISSIONS_ERROR, f'Cannot write into bucket {bucket}')


def upload_split_query_to_bucket(cfg: ElasticBlastConfig, clean_up_stack, dry_run):
    """Upload split query to bucket as staging before they're copied to a k8s persistent volume"""
    clean_up_stack.append(lambda: logging.debug('Before copying split jobs to bucket'))
    clean_up_stack.append(lambda: remove_split_query(cfg))
    copy_to_bucket(dry_run)
    clean_up_stack.append(lambda: logging.debug('After copying split jobs to bucket'))


def split_query(query_files: List[str], cfg: ElasticBlastConfig) -> Tuple[List[str], int]:
    """ Split query and provide callback for clean up of the intermediate split queries
        Parameters:
           query_fies - A list of query files
           cfg - configuration with parameters for query source, results bucket, and batch length
        Returns a tuple with a list of fully qualified names with split queries and the total query length.
    """
    dry_run = cfg.cluster.dry_run
    logging.info('Splitting queries into batches')
    batch_len = cfg.blast.batch_len
    out_path = os.path.join(cfg.cluster.results, ELB_QUERY_BATCH_DIR)
    start = timer()
    query_length = 0
    if dry_run:
        queries = [os.path.join(out_path, f'batch_{x:03d}.fa') for x in range(10)]
        logging.info(f'Splitting queries and writing batches to {out_path}')
    else:
        reader = FASTAReader(open_for_read_iter(query_files), batch_len, out_path)
        query_length, queries = reader.read_and_cut()
        logging.info(f'{len(queries)} batches, {query_length} base/residue total')
    end = timer()
    logging.debug(f'RUNTIME split-queries {end-start} seconds')
    return (queries, query_length)


def check_memory_requirements(cfg: ElasticBlastConfig):
    """ Using configuration cfg ensure that the memory required by database
        (database size plus margin) is available on machine type of configured cluster"""
    db = cfg.blast.db
    try:
        dbsize = get_blastdb_size(cfg.blast.db, cfg.blast.db_source)
    except ValueError as err:
        raise UserReportError(returncode=BLASTDB_ERROR, message=str(err))
    db_mem_margin = cfg.blast.db_mem_margin
    db_mem_req = dbsize * db_mem_margin
    machine_type = cfg.cluster.machine_type
    machine_mem = get_machine_properties(machine_type).memory
    if machine_mem < db_mem_req:
        raise RuntimeError(f'Database {db} requires {db_mem_req:.3f}GB RAM for processing, machine {machine_type} provides only {machine_mem:.3f}GB')


def collect_k8s_logs(cfg: ElasticBlastConfig):
    """ Collect logs from Kubernetes logs for several label/container combinations.
      Parameters:
        cfg - configuration with parameters, now only dry-run is used
    """
    dry_run = cfg.cluster.dry_run
    # TODO use named constants for labels and containers
    # also modify corresponding YAML templates and their substitution
    get_logs('app=setup', [K8S_JOB_GET_BLASTDB, K8S_JOB_IMPORT_QUERY_BATCHES], dry_run)
    get_logs('app=blast', [K8S_JOB_BLAST, K8S_JOB_RESULTS_EXPORT], dry_run)


def assemble_query_file_list(cfg: ElasticBlastConfig) -> List[str]:
    """Assemble a list of query files. cfg.blast.queries_arg is a list of
    space-separated files. if a file has extension constants.QUERY_LIST_EXT, it
    is considered a list of files, otherwise it is a FASTA file with queries."""
    msg = []
    query_files = []
    for query_file in cfg.blast.queries_arg.split():
        if query_file.endswith(QUERY_LIST_EXT):
            with open_for_read(query_file) as f:
                for line in f:
                    if len(line.rstrip()) == 0:
                        continue
                    query_file_from_list = line.rstrip()
                    if query_file_from_list.startswith(ELB_GCS_PREFIX) or \
                           query_file_from_list.startswith(ELB_S3_PREFIX):
                        try:
                            validate_cloud_storage_object_uri(query_file_from_list)
                        except ValueError as err:
                            msg.append(f'Incorrect query file URI "{query_file_from_list}" in list file "{query_file}": {err}')
                    query_files.append(query_file_from_list)
        else:
            query_files.append(query_file)

    if msg:
        raise UserReportError(returncode=INPUT_ERROR, message=('\n'.join(msg)))

    return query_files
