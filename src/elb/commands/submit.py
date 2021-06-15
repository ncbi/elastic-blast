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
import os
import logging
from tempfile import TemporaryDirectory
from pathlib import Path
from timeit import default_timer as timer
import uuid
from typing import List, Tuple

from elb.resources.quotas.quota_check import check_resource_quotas
from elb.aws import ElasticBlastAws
from elb.aws import check_cluster as aws_check_cluster
from elb.filehelper import open_for_read, open_for_read_iter, copy_to_bucket
from elb.filehelper import check_for_read, check_dir_for_write, cleanup_temp_bucket_dirs
from elb.split import FASTAReader
from elb.jobs import read_job_template, write_job_files
from elb.gcp import get_gke_credentials, delete_cluster_with_cleanup
from elb.gcp import enable_gcp_api, start_cluster
from elb.gcp import check_cluster as gcp_check_cluster
from elb.gcp import remove_split_query
from elb.gcp_traits import get_machine_properties
from elb.kubernetes import initialize_storage, submit_jobs
from elb.kubernetes import get_logs, get_maximum_number_of_allowed_k8s_jobs
from elb.status import get_status
from elb.util import get_blastdb_size, UserReportError, ElbSupportedPrograms
from elb.util import get_blastdb_info
from elb.util import get_usage_reporting
from elb.constants import ELB_AWS_JOB_IDS, ELB_METADATA_DIR, ELB_STATE_DISK_ID_FILE, K8S_JOB_BLAST, K8S_JOB_GET_BLASTDB, K8S_JOB_RESULTS_EXPORT
from elb.constants import K8S_JOB_IMPORT_QUERY_BATCHES, K8S_JOB_LOAD_BLASTDB_INTO_RAM
from elb.constants import ELB_QUERY_BATCH_DIR, BLASTDB_ERROR, INPUT_ERROR
from elb.constants import PERMISSIONS_ERROR, CLUSTER_ERROR, CSP
from elb.constants import ELB_DOCKER_IMAGE, QUERY_LIST_EXT
from elb.constants import ElbCommand
from elb.taxonomy import setup_taxid_filtering
from elb.config import validate_cloud_storage_object_uri
from elb.elb_config import ElasticBlastConfig

# TODO: use cfg only when args.wait, args.sync, and args.run_label are replicated in cfg
def submit(args, cfg, clean_up_stack):
    """ Entry point to submit an ElasticBLAST search
    """
    dry_run = cfg.cluster.dry_run
    cfg.validate(ElbCommand.SUBMIT)

    # For now, checking resources is only implemented for AWS
    if cfg.cloud_provider.cloud == CSP.AWS:
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

    #mode_str = "synchronous" if args.sync else "asynchronous"
    #logging.info(f'Running ElasticBLAST on {cfg.cloud_provider.cloud.name} in {mode_str} mode')

    # split FASTA query into batches
    clean_up_stack.append(cleanup_temp_bucket_dirs)
    queries, query_length = split_query(query_files, cfg)

    # setup taxonomy filtering, if requested
    setup_taxid_filtering(cfg)

    # FIXME: this is a temporary code arrangement
    if cfg.cloud_provider.cloud == CSP.AWS:
        elastic_blast = ElasticBlastAws(cfg, create=True)
        upload_split_query_to_bucket(cfg, clean_up_stack, dry_run)
        elastic_blast.upload_query_length(query_length)
        elastic_blast.submit(queries)
        return 0


    k8s_job_limit = get_maximum_number_of_allowed_k8s_jobs(dry_run)

    # check database availability
    try:
        get_blastdb_size(cfg.blast.db, cfg.blast.db_source)
    except ValueError as err:
        raise UserReportError(returncode=BLASTDB_ERROR, message=str(err))

    # check_memory_requirements(cfg)  # FIXME: EB-281, EB-313

    usage_reporting = get_usage_reporting()

    db, db_path, db_label = get_blastdb_info(cfg.blast.db)

    # Job generation
    job_template_text = read_job_template(cfg=cfg)
    program = cfg.blast.program

    # prepare substitution for current template
    # TODO consider template using cfg variables directly as, e.g. ${blast.program}
    subs = {
        'ELB_BLAST_PROGRAM': program,
        'ELB_DB': db,
        'ELB_DB_LABEL': db_label,
        'ELB_MEM_REQUEST': str(cfg.blast.mem_request),
        'ELB_MEM_LIMIT': str(cfg.blast.mem_limit),
        'ELB_BLAST_OPTIONS': cfg.blast.options,
        # FIXME: EB-210
        'ELB_BLAST_TIMEOUT': str(cfg.timeouts.blast_k8s * 60),
        'BUCKET': cfg.cluster.results,
        'ELB_NUM_CPUS': str(cfg.cluster.num_cpus),
        'ELB_DB_MOL_TYPE': ElbSupportedPrograms().get_molecule_type(program),
        'ELB_DOCKER_IMAGE': ELB_DOCKER_IMAGE,
        'ELB_TIMEFMT': '%s%N',  # timestamp in nanoseconds
        'BLAST_ELB_JOB_ID': uuid.uuid4().hex,
        'BLAST_USAGE_REPORT': str(usage_reporting).lower(),
        'K8S_JOB_GET_BLASTDB' : K8S_JOB_GET_BLASTDB,
        'K8S_JOB_LOAD_BLASTDB_INTO_RAM' : K8S_JOB_LOAD_BLASTDB_INTO_RAM,
        'K8S_JOB_IMPORT_QUERY_BATCHES' : K8S_JOB_IMPORT_QUERY_BATCHES,
        'K8S_JOB_BLAST' : K8S_JOB_BLAST,
        'K8S_JOB_RESULTS_EXPORT' : K8S_JOB_RESULTS_EXPORT

    }
    with TemporaryDirectory() as job_path:
        job_files = write_job_files(job_path, 'batch_', job_template_text, queries, **subs)
        if len(job_files) > k8s_job_limit:
            batch_len = cfg.blast.batch_len
            suggested_batch_len = int(query_length / k8s_job_limit) + 1
            msg = f'The batch size specified ({batch_len}) led to creating {len(job_files)} kubernetes jobs, which exceeds the limit on number of jobs ({k8s_job_limit}). Please increase the batch-len parameter to at least {suggested_batch_len}.'
            raise UserReportError(INPUT_ERROR, msg)
        logging.debug('Generated %d job files', len(job_files))
        logging.debug(f'Job #1 file: {job_files[0]}')
        logging.debug('Command to run in the pod:')
        with open(job_files[0]) as f:
            for line in f:
                if line.find('-query') >= 0:
                    logging.debug(line.strip())
                    break

        upload_split_query_to_bucket(cfg, clean_up_stack, dry_run)
        initialize_cluster(cfg, db, db_path, clean_up_stack)

        logging.info('Submitting jobs to cluster')
        clean_up_stack.append(lambda: logging.debug('Before submission computational jobs'))
        job_names = submit_jobs(Path(job_path), dry_run=dry_run)
        clean_up_stack.append(lambda: logging.debug('After submission computational jobs'))
        if job_names:
            logging.debug(f'Job #1 name: {job_names[0]}')

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


def initialize_cluster(cfg: ElasticBlastConfig, db: str, db_path: str, clean_up_stack):
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
    initialize_storage(cfg, db, db_path)
    clean_up_stack.append(lambda: logging.debug('After initializing storage'))


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
    is considered a list of files, otherwise it is a FASTA file with queries.
    This function initializes global variable config.query_files."""
    msg = []
    query_files = []
    for query_file in cfg.blast.queries_arg.split():
        if query_file.endswith(QUERY_LIST_EXT):
            with open_for_read(query_file) as f:
                for line in f:
                    if len(line.rstrip()) == 0:
                        continue
                    query_file_from_list = line.rstrip()
                    if query_file_from_list.startswith('gs://') or \
                           query_file_from_list.startswith('s3://'):
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
