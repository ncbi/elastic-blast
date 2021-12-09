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
# Author: Greg Boratyn boratyng@ncbi.nlm.nih.gov


import argparse
import logging
import os
from elastic_blast.base import QuerySplittingResults
from elastic_blast.filehelper import harvest_query_splitting_results, open_for_read
from elastic_blast.constants import ElbCommand, ELB_DFLT_LOGLEVEL
from elastic_blast.constants import ELB_METADATA_DIR, ELB_META_CONFIG_FILE
from elastic_blast.aws import ElasticBlastAws, handle_aws_error
from elastic_blast.elb_config import ElasticBlastConfig
from elastic_blast.util import config_logging
from elastic_blast.base import MemoryStr
from elastic_blast import VERSION

DESC = 'Helper script to submit ElasticBLAST jobs remotely'

@handle_aws_error
def main():
    """Main function"""
    parser = create_arg_parser()
    args = parser.parse_args()

    config_logging(args)
    logging.info(f"ElasticBLAST submit_jobs.py {VERSION}")

    cfg_uri = os.path.join(args.results, ELB_METADATA_DIR, ELB_META_CONFIG_FILE)
    logging.debug(f"Loading {cfg_uri}")
    with open_for_read(cfg_uri) as f:
        cfg_json = f.read()
    cfg = ElasticBlastConfig.from_json(cfg_json)
    logging.debug(f'AWS region: {cfg.aws.region}')
    cfg.validate(ElbCommand.SUBMIT)
    eb = ElasticBlastAws(cfg, False)

    bucket = cfg.cluster.results
    logging.info(f'Bucket: {bucket}')
    qr = harvest_query_splitting_results(bucket)
    logging.debug(f'Submitting jobs for query batches: {" ".join(qr.query_batches)}')
    eb.client_submit(qr.query_batches, False)


def create_arg_parser():
    """ Create the command line options parser object for this script. """
    parser = argparse.ArgumentParser(description=DESC)
    parser.add_argument('--results', metavar='STR', type=str, help='Results bucket', required=True)
    parser.add_argument("--logfile", default='stderr', type=str,
                        help=f"Default: stderr")
    parser.add_argument("--loglevel", default='DEBUG',
                        help=f"Default: DEBUG",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])


    return parser

if __name__ == '__main__':
    main()


# vim: set syntax=python ts=4 et :
