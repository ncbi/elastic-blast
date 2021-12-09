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
import math
from timeit import default_timer as timer
from typing import List, Tuple
from pprint import pformat
from elastic_blast import elasticblast
from elastic_blast.elasticblast_factory import ElasticBlastFactory

from elastic_blast.resources.quotas.quota_check import check_resource_quotas
from elastic_blast.aws import check_cluster as aws_check_cluster
from elastic_blast.filehelper import open_for_read, open_for_read_iter, open_for_write_immediate
from elastic_blast.filehelper import check_for_read, check_dir_for_write, cleanup_temp_bucket_dirs
from elastic_blast.filehelper import get_length, harvest_query_splitting_results
from elastic_blast.object_storage_utils import write_to_s3
from elastic_blast.split import FASTAReader
from elastic_blast.gcp import enable_gcp_api
from elastic_blast.gcp import check_cluster as gcp_check_cluster
from elastic_blast.gcp_traits import get_machine_properties
from elastic_blast.util import get_blastdb_size, UserReportError
from elastic_blast.constants import ELB_AWS_JOB_IDS, ELB_METADATA_DIR, ELB_STATE_DISK_ID_FILE, QuerySplitMode
from elastic_blast.constants import ELB_QUERY_BATCH_DIR, BLASTDB_ERROR, INPUT_ERROR
from elastic_blast.constants import PERMISSIONS_ERROR, CLUSTER_ERROR, CSP, QUERY_LIST_EXT
from elastic_blast.constants import ElbCommand, ELB_META_CONFIG_FILE
from elastic_blast.constants import ELB_S3_PREFIX, ELB_GCS_PREFIX
from elastic_blast.taxonomy import setup_taxid_filtering
from elastic_blast.config import validate_cloud_storage_object_uri
from elastic_blast.elb_config import ElasticBlastConfig


def get_query_split_mode(cfg: ElasticBlastConfig, query_files):
    """ Determine query split mode """
    if 'ELB_USE_CLIENT_SPLIT' in os.environ:
        return QuerySplitMode.CLIENT
    # Case for cloud split on AWS: one file on S3
    #                      on GCP: one file on GCS
    if len(query_files) == 1 and (
            cfg.cloud_provider.cloud == CSP.AWS and query_files[0].startswith(ELB_S3_PREFIX)
            or
            cfg.cloud_provider.cloud == CSP.GCP and query_files[0].startswith(ELB_GCS_PREFIX)):
        if cfg.cloud_provider.cloud == CSP.AWS and \
           'ELB_USE_1_STAGE_CLOUD_SPLIT' in os.environ:
            return QuerySplitMode.CLOUD_ONE_STAGE
        else:
            return QuerySplitMode.CLOUD_TWO_STAGE

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


def write_config_to_metadata(cfg):
    """ Serialize configuration object (not ElasticBLAST configuration file)
        and write to results bucket as metadata """
    if cfg.cluster.dry_run:
        return
    # FIXME: refactor this code into object_storage_utils
    cfg_text = cfg.to_json()
    dst = os.path.join(cfg.cluster.results, ELB_METADATA_DIR, ELB_META_CONFIG_FILE)
    if cfg.cloud_provider.cloud == CSP.AWS:
        write_to_s3(dst, cfg_text)
    else:
        with open_for_write_immediate(dst) as f:
            f.write(cfg_text)


# TODO: use cfg only when args.wait, args.sync, and args.run_label are replicated in cfg
def submit(args, cfg, clean_up_stack):
    """ Entry point to submit an ElasticBLAST search
    """
    dry_run = cfg.cluster.dry_run
    cfg.validate(ElbCommand.SUBMIT, dry_run)

    # For now, checking resources is only implemented for AWS
    if cfg.cloud_provider.cloud == CSP.AWS:
        check_resource_quotas(cfg)
    else:
        enable_gcp_api(cfg)
    
    if check_running_cluster(cfg):
        msg = 'An ElasticBLAST search that will write results to '
        msg += f'{cfg.cluster.results} has already been submitted.\n'
        msg += 'Please resubmit your search with a different value '
        msg += 'for "results" configuration parameter, or save '
        msg += 'the ElasticBLAST results and then either delete '
        msg += 'the previous ElasticBLAST search by running '
        msg += 'elastic-blast delete, or run the command '
        if cfg.cloud_provider.cloud == CSP.AWS:
            msg += f'aws s3 rm --recursive {cfg.cluster.results}'
        else:
            msg += f'gsutil rm -r {cfg.cluster.results}'
        raise UserReportError(CLUSTER_ERROR, msg);

    query_files = assemble_query_file_list(cfg)
    check_submit_data(query_files, cfg)
    write_config_to_metadata(cfg)

    #mode_str = "synchronous" if args.sync else "asynchronous"
    #logging.info(f'Running ElasticBLAST on {cfg.cloud_provider.cloud.name} in {mode_str} mode')

    queries = None
    query_length = 0

    query_split_mode = get_query_split_mode(cfg, query_files)
    logging.debug(f'Query split mode {query_split_mode.name}')

    # query splitting
    if query_split_mode == QuerySplitMode.CLIENT:
        clean_up_stack.append(cleanup_temp_bucket_dirs)
        queries, query_length = split_query(query_files, cfg)
    elif query_split_mode == QuerySplitMode.CLOUD_ONE_STAGE:
        queries = prepare_1_stage(cfg, query_files)

    # setup taxonomy filtering, if requested
    setup_taxid_filtering(cfg)

    # check database availability
    try:
        get_blastdb_size(cfg.blast.db, cfg.cluster.db_source)
    except ValueError as err:
        raise UserReportError(returncode=BLASTDB_ERROR, message=str(err))

    elastic_blast = ElasticBlastFactory(cfg, True, clean_up_stack)
    elastic_blast.upload_workfiles()

    # query splitting
    if query_split_mode in (QuerySplitMode.CLOUD_ONE_STAGE, QuerySplitMode.CLIENT):
        elastic_blast.upload_query_length(query_length)
    elif query_split_mode == QuerySplitMode.CLOUD_TWO_STAGE:
        elastic_blast.cloud_query_split(query_files)
        if 'ELB_NO_SEARCH' in os.environ: return 0
        if not elastic_blast.cloud_job_submission:
            elastic_blast.wait_for_cloud_query_split()
            qs_res = harvest_query_splitting_results(cfg.cluster.results, dry_run)
            queries = qs_res.query_batches
            query_length = qs_res.query_length

    # update config file in metadata
    write_config_to_metadata(cfg)
    # job submission
    elastic_blast.submit(queries, query_length, query_split_mode == QuerySplitMode.CLOUD_ONE_STAGE)
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


def split_query(query_files: List[str], cfg: ElasticBlastConfig) -> Tuple[List[str], int]:
    """ Split query and provide callback for clean up of the intermediate split queries
        Parameters:
           query_fies - A list of query files
           cfg - configuration with parameters for query source, results bucket, and batch length
        Returns a tuple with a list of fully qualified names with split queries and the total query length.
    """
    dry_run = cfg.cluster.dry_run
    logging.info('Splitting queries into batches')
    num_concurrent_blast_jobs = cfg.get_max_number_of_concurrent_blast_jobs()
    logging.debug(f'Maximum number of concurrent BLAST jobs: {num_concurrent_blast_jobs}')
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
        if len(queries) < num_concurrent_blast_jobs:
            adjusted_batch_len = int(query_length/num_concurrent_blast_jobs)
            msg = f'The provided elastic-blast configuration is sub-optimal as the query was split into {len(queries)} batch(es) and elastic-blast can run up to {num_concurrent_blast_jobs} concurrent BLAST jobs. elastic-blast changed the batch-len parameter to {adjusted_batch_len} to maximize resource utilization and improve performance.'
            logging.info(msg)
            reader = FASTAReader(open_for_read_iter(query_files), adjusted_batch_len, out_path)
            query_length, queries = reader.read_and_cut()
            logging.info(f'Re-computed {len(queries)} batches, {query_length} base/residue total')
    end = timer()
    logging.debug(f'RUNTIME split-queries {end-start} seconds')
    return (queries, query_length)


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
