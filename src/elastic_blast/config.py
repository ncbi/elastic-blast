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
src/elb/config.py - Functionality to configure ElasticBLAST.

Documentation: https://elbdoc.readthedocs.io/en/stable/configuration.html

Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
Created: Wed 22 Apr 2020 07:41:40 PM EDT
"""

import os
import re
import argparse
import logging
import configparser
import getpass
from hashlib import md5
from .util import check_positive_int, get_query_batch_size
from .util import ElbSupportedPrograms
from .util import validate_gcp_string, validate_gke_cluster_name
from .util import validate_aws_region
from .constants import APP_STATE, CFG_BLAST, CFG_BLAST_BATCH_LEN, CFG_BLAST_DB, CFG_BLAST_DB_MEM_MARGIN, CFG_BLAST_DB_SRC, CFG_BLAST_MEM_LIMIT, CFG_BLAST_MEM_REQUEST, CFG_BLAST_OPTIONS, CFG_BLAST_PROGRAM, CFG_BLAST_QUERY, CFG_BLAST_RESULTS, CFG_CLOUD_PROVIDER, CFG_CLUSTER, CFG_CLUSTER_BID_PERCENTAGE, CFG_CLUSTER_DISK_TYPE, CFG_CLUSTER_DRY_RUN, CFG_CLUSTER_EXP_USE_LOCAL_SSD, CFG_CLUSTER_MACHINE_TYPE, CFG_CLUSTER_NAME, CFG_CLUSTER_NUM_CPUS, CFG_CLUSTER_NUM_NODES, CFG_CLUSTER_PD_SIZE, CFG_CLUSTER_PROVISIONED_IOPS, CFG_CLUSTER_RUN_LABEL, CFG_CLUSTER_USE_PREEMPTIBLE, CFG_CP_AWS_REGION, CFG_CP_GCP_NETWORK, CFG_CP_GCP_PROJECT, CFG_CP_GCP_REGION, CFG_CP_GCP_SUBNETWORK, CFG_CP_GCP_ZONE, CFG_CP_NAME, CFG_TIMEOUTS, CFG_TIMEOUT_BLAST_K8S_JOB, CFG_TIMEOUT_INIT_PV
from .constants import ELB_DFLT_OUTFMT, ELB_BLASTDB_MEMORY_MARGIN, ELB_DFLT_USE_PREEMPTIBLE
from .constants import ELB_DFLT_GCP_PD_SIZE, ELB_DFLT_GCP_MACHINE_TYPE, ELB_DFLT_AWS_MACHINE_TYPE
from .constants import ELB_DFLT_BLAST_K8S_TIMEOUT, ELB_DFLT_INIT_PV_TIMEOUT, ELB_DFLT_NUM_NODES
from .constants import ELB_DFLT_BLASTDB_SOURCE, INPUT_ERROR, CSP
from .constants import ELB_DFLT_AWS_DISK_TYPE, ELB_DFLT_AWS_PD_SIZE, ELB_DFLT_AWS_PROVISIONED_IOPS
from .constants import ELB_DFLT_AWS_SPOT_BID_PERCENTAGE
from .constants import APP_STATE_RESULTS_MD5, SYSTEM_MEMORY_RESERVE
from .constants import ELB_S3_PREFIX, ELB_GCS_PREFIX
from .constants import ELB_DFLT_AWS_REGION, ELB_DFLT_GCP_REGION
from .util import UserReportError
from .filehelper import parse_bucket_name_key
from typing import List


def _set_sections(cfg: configparser.ConfigParser) -> None:
    """Sets the top level sections for the configuration object"""
    if not cfg.has_section(CFG_CLOUD_PROVIDER):
        cfg.add_section(CFG_CLOUD_PROVIDER)
    if not cfg.has_section(CFG_CLUSTER):
        cfg.add_section(CFG_CLUSTER)
    if not cfg.has_section(CFG_BLAST):
        cfg.add_section(CFG_BLAST)
    if not cfg.has_section(CFG_TIMEOUTS):
        cfg.add_section(CFG_TIMEOUTS)
    if not cfg.has_section(APP_STATE):
        cfg.add_section(APP_STATE)


def _load_config_from_environment(cfg: configparser.ConfigParser) -> None:
    """Selected environment variables can be used to configure ElasticBLAST"""
    if 'ELB_GCP_PROJECT' in os.environ:
        cfg[CFG_CLOUD_PROVIDER][CFG_CP_GCP_PROJECT] = os.environ['ELB_GCP_PROJECT']
    if 'ELB_GCP_REGION' in os.environ:
        cfg[CFG_CLOUD_PROVIDER][CFG_CP_GCP_REGION] = os.environ['ELB_GCP_REGION']
    if 'ELB_GCP_ZONE' in os.environ:
        cfg[CFG_CLOUD_PROVIDER][CFG_CP_GCP_ZONE] = os.environ['ELB_GCP_ZONE']
    if 'ELB_BATCH_LEN' in os.environ:
        cfg[CFG_BLAST][CFG_BLAST_BATCH_LEN] = os.environ['ELB_BATCH_LEN']
    if 'ELB_CLUSTER_NAME' in os.environ:
        cfg[CFG_CLUSTER][CFG_CLUSTER_NAME] = os.environ['ELB_CLUSTER_NAME']
    if 'ELB_RESULTS' in os.environ:
        cfg[CFG_BLAST][CFG_BLAST_RESULTS] = os.environ['ELB_RESULTS']
    if 'ELB_USE_PREEMPTIBLE' in os.environ:
        cfg[CFG_CLUSTER][CFG_CLUSTER_USE_PREEMPTIBLE] = os.environ['ELB_USE_PREEMPTIBLE']
    if 'ELB_BID_PERCENTAGE' in os.environ:
        cfg[CFG_CLUSTER][CFG_CLUSTER_BID_PERCENTAGE] = os.environ['ELB_BID_PERCENTAGE']


def configure(args: argparse.Namespace) -> configparser.ConfigParser:
    """Sets up the application's configuration.

    The order of precedence for configuration settings is as follows (lowest to highest):
    1. Application defaults
    2. Configuration file
    3. Environment variables (ELB_*)
    4. Command line parameters
    """
    retval = configparser.ConfigParser(empty_lines_in_values=False)
    _set_sections(retval)
    if hasattr(args, 'cfg') and args.cfg:
        if not os.path.isfile(args.cfg):
            raise FileNotFoundError(f'{args.cfg}')
        logging.debug(f'Reading {args.cfg}')
        retval.read(args.cfg)

    # If set in config file - ignore it and calculate from results later
    if CFG_CLUSTER_NAME in retval[CFG_CLUSTER]:
        retval.remove_option(CFG_CLUSTER, CFG_CLUSTER_NAME)

    _load_config_from_environment(retval)

    # These command line options override the config value settings
    if hasattr(args, CFG_BLAST_RESULTS) and args.results:
        retval[CFG_BLAST][CFG_BLAST_RESULTS] = args.results
    if hasattr(args, CFG_BLAST_PROGRAM) and args.program:
        retval[CFG_BLAST][CFG_BLAST_PROGRAM] = args.program
    if hasattr(args, 'query') and args.query:
        retval[CFG_BLAST][CFG_BLAST_QUERY] = args.query
    if hasattr(args, CFG_BLAST_DB) and args.db:
        retval[CFG_BLAST][CFG_BLAST_DB] = args.db
    if hasattr(args, 'blast_opts') and args.blast_opts:
        if args.blast_opts[0] == '--':
            args.blast_opts.pop(0)
        # quote arguments with spaces in them
        blast_opts = map(lambda x: x if x.find(' ') < 0 else "'"+x+'"', args.blast_opts)
        retval[CFG_BLAST][CFG_BLAST_OPTIONS] = ' '.join(blast_opts)
    if hasattr(args, CFG_BLAST_RESULTS) and getattr(args, CFG_BLAST_RESULTS):
        retval[CFG_BLAST][CFG_BLAST_RESULTS] = getattr(args, CFG_BLAST_RESULTS)

    if hasattr(args, 'num_nodes') and args.num_nodes:
        retval[CFG_CLUSTER][CFG_CLUSTER_NUM_NODES] = str(args.num_nodes)
    if hasattr(args, 'num_cpus') and args.num_cpus:
        retval[CFG_CLUSTER][CFG_CLUSTER_NUM_CPUS] = str(args.num_cpus)
    if hasattr(args, 'machine_type') and args.machine_type:
        retval[CFG_CLUSTER][CFG_CLUSTER_MACHINE_TYPE] = args.machine_type
    if hasattr(args, 'mem_limit') and args.mem_limit:
        retval[CFG_BLAST][CFG_BLAST_MEM_LIMIT] = args.mem_limit

    if hasattr(args, 'aws_region') and args.aws_region:
        retval[CFG_CLOUD_PROVIDER][CFG_CP_AWS_REGION] = args.aws_region
    if hasattr(args, 'gcp_project') and args.gcp_project:
        retval[CFG_CLOUD_PROVIDER][CFG_CP_GCP_PROJECT] = args.gcp_project
    if hasattr(args, 'gcp_region') and args.gcp_region:
        retval[CFG_CLOUD_PROVIDER][CFG_CP_GCP_REGION] = args.gcp_region
    if hasattr(args, 'gcp_zone') and args.gcp_zone:
        retval[CFG_CLOUD_PROVIDER][CFG_CP_GCP_ZONE] = args.gcp_zone
    if hasattr(args, 'gcp_zone') and args.gcp_zone:
        retval[CFG_CLOUD_PROVIDER][CFG_CP_GCP_ZONE] = args.gcp_zone

    # If results bucket was provided, set the default region in the
    # corresponding cloud service provider if it wasn't specified by the user
    if CFG_BLAST_RESULTS in retval[CFG_BLAST]:
        if retval[CFG_BLAST][CFG_BLAST_RESULTS].startswith(ELB_S3_PREFIX):
            if CFG_CP_AWS_REGION not in retval[CFG_CLOUD_PROVIDER]:
                retval[CFG_CLOUD_PROVIDER][CFG_CP_AWS_REGION] = ELB_DFLT_AWS_REGION
        elif retval[CFG_BLAST][CFG_BLAST_RESULTS].startswith(ELB_GCS_PREFIX):
            if CFG_CP_GCP_REGION not in retval[CFG_CLOUD_PROVIDER]:
                retval[CFG_CLOUD_PROVIDER][CFG_CP_GCP_REGION] = ELB_DFLT_GCP_REGION
    
    # Exception to prevent unnecessary API calls and ensure testability
    # of some functionality without credentials
    if hasattr(args, 'subcommand') and args.subcommand == 'run-summary' and hasattr(args, 'read_logs') and args.read_logs:
        retval[CFG_CLOUD_PROVIDER][CFG_CP_AWS_REGION] = ELB_DFLT_AWS_REGION
        retval[CFG_BLAST][CFG_BLAST_RESULTS] = os.path.join(ELB_S3_PREFIX, 'dummy')

    if hasattr(args, 'dry_run') and args.dry_run:
        retval[CFG_CLUSTER][CFG_CLUSTER_DRY_RUN] = 'yes'
    if hasattr(args, 'run_label') and args.run_label:
        retval[CFG_CLUSTER][CFG_CLUSTER_RUN_LABEL] = args.run_label
        raise NotImplementedError('run-label is currently not implemented')  # FIXME: EB-132

    return retval


def _validate_csp(cfg: configparser.ConfigParser) -> None:
    """ Validate the Cloud Service Provider from configuration file
    Throws a UserReportError in case of invalid configuration.
    """
    if CFG_CLOUD_PROVIDER not in cfg:
        report_config_error(['Cloud provider configuration is missing'])

    # are gcp or aws entries present in cloud-provider config
    gcp = sum([i.startswith('gcp') for i in cfg[CFG_CLOUD_PROVIDER]]) > 0
    aws = sum([i.startswith('aws') for i in cfg[CFG_CLOUD_PROVIDER]]) > 0

    msg = []

    # both and none are forbidden
    if gcp and aws:
        msg.append('Cloud provider config contains entries for more than one cloud provider. Only one cloud provider can be used')
    if not gcp and not aws:
        msg.append('Cloud provider configuration is missing')

    if CFG_CP_NAME in cfg[CFG_CLOUD_PROVIDER]:
        logging.debug(f'Cloud Service Provider {cfg[CFG_CLOUD_PROVIDER][CFG_CP_NAME]}')
    if msg:
        report_config_error(msg)


def report_config_error(msg: List[str]) -> None:
    """Raise UserReportError with given error message."""
    err_msg = '\n'.join(['Elastic-BLAST configuration error(s):'] + msg + [
        'Configuration can be set in a config file provided with --cfg option or environment variables. Please, see documentation for details.'])
    raise UserReportError(returncode=INPUT_ERROR, message=err_msg)


def validate_cloud_storage_object_uri(uri: str) -> None:
    """Validate cloud storage object uri for GS and S3.
    Only bucket name is checked, because object key can be almost anything."""
    # get bucket name
    bucket, _ = parse_bucket_name_key(uri)
    if uri.startswith(ELB_S3_PREFIX):
        # S3 bucket name must contain only lowercase letters, numbers, dots,
        # and dashes, start and end with a letter or a number, and be between
        # 3 and 63 characters long;
        # https://docs.aws.amazon.com/AmazonS3/latest/dev/BucketRestrictions.html
        # bucket name can also be provided as ARN
        if re.fullmatch(r'^[a-z0-9][a-zA-Z0-9._-]{1,61}[a-z0-9]$|^arn:(aws).*:s3:[a-z-0-9]+:[0-9]{12}:accesspoint[/:][a-zA-Z0-9-]{1,63}$|^arn:(aws).*:s3-outposts:[a-z-0-9]+:[0-9]{12}:outpost[/:][a-zA-Z0-9-]{1,63}[/:]accesspoint[/:][a-zA-Z0-9-]{1,63}$', bucket) is None:
            raise ValueError('An S3 bucket name must contain only lowercase letters, numbers, dashes (-), and dots (.), must begin and end with a letter or a number, and must be between 3 and 63 characters long.')
    # separate test for object key
    elif uri.startswith(ELB_GCS_PREFIX):
        # GS bucket name must contain only lowercase letters, numbers, dashes,
        # and underscores, and start and end with a letter or a number
        # https://cloud.google.com/storage/docs/naming-buckets
        if re.fullmatch(r'^[a-z0-9][a-z0-9._-]+[a-z0-9]$', bucket) is None:
            raise ValueError('A GS bucket name must contain only lowercase letters, numbers, dashes (-), underscores (_), and dots (.)')
    else:
        raise ValueError(f'An object URI must start with {ELB_GCS_PREFIX} or ${ELB_S3_PREFIX}')
