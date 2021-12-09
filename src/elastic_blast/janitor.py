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

# Script to submit ElasticBLAST jobs by an AWS Batch job
#
# Author: Christiam Camacho camacho@ncbi.nlm.nih.gov


import argparse
import logging
import os
from botocore.exceptions import ClientError # type: ignore
from tempfile import NamedTemporaryFile
from pathlib import Path
from pprint import pformat
from elastic_blast.constants import ElbCommand, ELB_DFLT_LOGLEVEL, ElbStatus
from elastic_blast.constants import CSP, ELB_S3_PREFIX
from elastic_blast.constants import ELB_METADATA_DIR, ELB_META_CONFIG_FILE
from elastic_blast.constants import ELB_STATUS_SUCCESS, ELB_STATUS_FAILURE
from elastic_blast.elasticblast import ElasticBlast
from elastic_blast.aws import ElasticBlastAws
from elastic_blast.elb_config import ElasticBlastConfig
from elastic_blast.util import config_logging
from elastic_blast.filehelper import open_for_read
from elastic_blast import VERSION

from elastic_blast.filehelper import upload_file_to_gcs, check_for_read
from elastic_blast.object_storage_utils import copy_file_to_s3


DESC = 'ElasticBLAST Janitor module to clean up after itself'

def copy_to_results_bucket_if_not_present(filename: str, bucket: str):
    """ Wrapper function to copy a file to cloud object storage """
    try:
        check_for_read(bucket)
    except FileNotFoundError:
        if bucket.startswith(ELB_S3_PREFIX):
            copy_file_to_s3(bucket, Path(filename))
        else:
            upload_file_to_gcs(filename, bucket)


def janitor(elb: ElasticBlast) -> None:
    """ ElasticBLAST Janitor function: cleans up ElasticBLAST resources """
    st, _, _ = elb.check_status()
    results = elb.cfg.cluster.results
    cluster_name = elb.cfg.cluster.name
    if st == ElbStatus.SUCCESS:
        with NamedTemporaryFile() as f:
            copy_to_results_bucket_if_not_present(f.name, os.path.join(results, ELB_METADATA_DIR, ELB_STATUS_SUCCESS))
        logging.debug(f'ElasticBLAST search with results on {results} is DONE, deleting it (cluster name {cluster_name})')
        elb.delete()
    elif st == ElbStatus.FAILURE:
        with NamedTemporaryFile() as f:
            copy_to_results_bucket_if_not_present(f.name, os.path.join(results, ELB_METADATA_DIR, ELB_STATUS_FAILURE))
        logging.debug(f'ElasticBLAST search with results on {results} has FAILED, deleting it (cluster name {cluster_name})')
        elb.delete()
    elif st == ElbStatus.CREATING:
        logging.debug(f'ElasticBLAST search on {results} is still being initialized (cluster name {cluster_name})')
    elif st == ElbStatus.SUBMITTING:
        logging.debug(f'ElasticBLAST search on {results} is performing job submission (cluster name {cluster_name})')
    elif st == ElbStatus.RUNNING:
        logging.debug(f'ElasticBLAST search with results on {results} is still running (cluster name {cluster_name})')
    elif st == ElbStatus.DELETING:
        logging.debug(f'ElasticBLAST search on {results} is being deleted (cluster name {cluster_name})')
    elif st == ElbStatus.UNKNOWN:
        if elb.dry_run:
            logging.warning(f'Unknown status on {results} because of dry-run option (cluster name {cluster_name})')
        else:
            logging.warning(f'Unknown or expired ElasticBLAST search with results on {results} (cluster name {cluster_name})')



def main():
    """Main function, provided for testing """
    parser = create_arg_parser()
    args = parser.parse_args()
    config_logging(args)
    try:
        logging.info(f"ElasticBLAST Janitor {VERSION}")

        cfg_uri = os.path.join(args.results, ELB_METADATA_DIR, ELB_META_CONFIG_FILE)
        logging.debug(f"Loading {cfg_uri}")
        with open_for_read(cfg_uri) as f:
            cfg_json = f.read()
        cfg = ElasticBlastConfig.from_json(cfg_json)
        logging.debug(f'{cfg.to_json()}')
        cfg.validate(ElbCommand.STATUS)
        eb = ElasticBlastAws(cfg, False)

        eb.dry_run = args.dry_run
        janitor(eb)
    except ClientError as ex:
        if ex.response['Error']['Code'] == 'NoSuchKey':
            logging.fatal(f'Results bucket {args.results} does not contain an ElasticBLAST configuration')
        return 1
    return 0


def create_arg_parser():
    """ Create the command line options parser object for this script. """
    parser = argparse.ArgumentParser(description=DESC)
    parser.add_argument('--results', metavar='STR', type=str, help='Results bucket', required=True)
    parser.add_argument("--dry-run", action='store_true', help="Do not perform any actions")
    parser.add_argument("--logfile", default='stderr', type=str, help=f"Default: stderr")
    parser.add_argument("--loglevel", default=ELB_DFLT_LOGLEVEL,
                        help=f"Default: {ELB_DFLT_LOGLEVEL}",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    return parser

if __name__ == '__main__':
    import sys, traceback
    try:
        sys.exit(main())
    except Exception as e:
        print(e, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


# vim: set syntax=python ts=4 et :
