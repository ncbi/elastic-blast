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
elb/util.py - Utility functions for ElasticBLAST

Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
Created: Tue 07 Apr 2020 03:43:24 PM EDT
"""

import os
import re
import logging
import argparse
import subprocess
import datetime
import json
from functools import reduce
from pkg_resources import resource_exists
from typing import List, Union, Callable
from .constants import MolType, GCS_DFLT_BUCKET
from .constants import DEPENDENCY_ERROR, AWS_MAX_TAG_LENGTH, GCP_MAX_LABEL_LENGTH
from .constants import AWS_MAX_JOBNAME_LENGTH, CSP
from .constants import ELB_DFLT_LOGLEVEL, ELB_DFLT_LOGFILE
from .base import DBSource

RESOURCES = [
    'job-cloud-split-local-ssd.yaml.template',
    'job-init-local-ssd.yaml.template',
    'storage-gcp-ssd.yaml',
    'pvc.yaml.template',
    'job-init-pv.yaml.template',
    'elb-janitor-rbac.yaml',
    'elb-janitor-cronjob.yaml.template',
    'job-submit-jobs.yaml.template',
    'blast-batch-job.yaml.template',
    'blast-batch-job-local-ssd.yaml.template'
]
# Not used by elastic-blast tool:
# storage-gcp.yaml
# cloudformation-admin-iam.yaml
# Used directly (without pkg_resources) in aws.py
# elastic-blast-cf.yaml
# Used from bucket resource
# elastic-blast-janitor-cf.yaml
def validate_installation():
    for r in RESOURCES:
        if not resource_exists('elastic_blast', os.path.join('templates', r)):
            raise UserReportError(DEPENDENCY_ERROR,
                f'Resource {r} is missing from the package. Please re-install ElasticBLAST')



class ElbSupportedPrograms:
    """Auxiliary class to validate supported BLAST programs

    Must match https://elbdoc.readthedocs.io/en/latest/configuration.html#blast-program
    """
    _programs = [
        'blastp',
        'blastn',
        'blastx',
        'psiblast',
        'rpsblast',
        'rpstblastn',
        'tblastn',
        'tblastx'
    ]

    def get(self):
        return self._programs

    def check(self, program):
        if program not in self._programs:
            raise ValueError(f"{program} is not a supported BLAST program")

    def get_db_mol_type(self, program: str) -> MolType:
        ''' Returns the expected molecule type for the program passed in as an argument.
        '''
        p = program.lower()
        if p not in self._programs:
            raise NotImplementedError(f'Invalid BLAST program "{program}"')

        retval = MolType.UNKNOWN
        if p == 'blastn' or p == 'tblastn' or p == 'tblastx':
            retval = MolType.NUCLEOTIDE
        elif re.search(r'^blast[px]$', p) or re.search(r'^(psi|rps)blast$', p) or p == 'rpstblastn':
            retval = MolType.PROTEIN
        else:
            raise NotImplementedError(f'Invalid BLAST program "{program}"')
        return retval


    def get_query_mol_type(self, program: str) -> MolType:
        ''' Returns the expected query molecule type for the program passed in
            as an argument.
        '''
        p = program.lower()
        if p not in self._programs:
            raise NotImplementedError(f'Invalid BLAST program "{program}"')

        retval = MolType.UNKNOWN
        if p in ['blastn', 'blastx', 'tblastx', 'rpstblastn']:
            retval = MolType.NUCLEOTIDE
        elif p in ['blastp', 'tblastn', 'psiblast', 'rpsblast']:
            retval = MolType.PROTEIN
        else:
            raise NotImplementedError(f'Invalid BLAST program "{program}"')
        return retval


def get_query_batch_size(program: str) -> int:
    """ Return the query batch size for use in ElasticBLAST

    program: BLAST program name
    returns: integer or -1 in case of invalid/unrecognized input

    """
    if not issubclass(type(program), str):
        return -1

    try:
        ElbSupportedPrograms().check(program.lower())
    except ValueError:
        return -1

    # TODO: should we differentiate between default blast[px] and blast[px]-fast?
    switcher = {
        "blastp":       10000,
        "blastn":       5000000,
        "blastx":       20004,
        "psiblast":     100000,
        "rpsblast":     100000,
        "rpstblastn":   100000,
        "tblastn":      20000,
        "tblastx":      100000
    }
    if 'ELB_BATCH_LEN' in os.environ:
        return int(str(os.getenv('ELB_BATCH_LEN')))
    return switcher.get(program.lower(), -1)


class ElasticBlastBaseException(Exception):
    """Base class for exceptions generated by elastic-blast code.
    Attributes:
        returncode: Error code
        message: Error message"""

    def __init__(self, returncode: int, message: str):
        """Initialize parameters:"""
        self.returncode = returncode
        self.message = message

    def __str__(self):
        """Conversion to a string"""
        return self.message


class SafeExecError(ElasticBlastBaseException):
    """Exception thrown by safe_exec function caused by errors returned by
    command line programs/scripts run via subprocess.
    Attributes:
        returncode: Return code from the process run by the subprocess module
        message: Error message"""
    pass


def safe_exec(cmd: Union[List[str], str]) -> subprocess.CompletedProcess:
    """Wrapper around subprocess.run that raises SafeExecError on errors from
    command line with error messages assembled from all available information"""
    if isinstance(cmd, str):
        cmd = cmd.split()
    if not isinstance(cmd, list):
        raise ValueError('safe_exec "cmd" argument must be a list or string')

    try:
        logging.debug(' '.join(cmd))
        p = subprocess.run(cmd, check=True, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        msg = f'The command "{" ".join(e.cmd)}" returned with exit code {e.returncode}\n{e.stderr.decode()}\n{e.stdout.decode()}'
        if e.output is not None:
            '\n'.join([msg, f'{e.output.decode()}'])
            raise SafeExecError(e.returncode, msg)
    except PermissionError as e:
        raise SafeExecError(e.errno, str(e))
    except FileNotFoundError as e:
        raise SafeExecError(e.errno, e.strerror)
    return p


def get_blastdb_info(blastdb: str):
    """Get BLAST database short name, path (if applicable), and label
    for Kubernetes. Gets user provided database from configuration.
    For custom database finds short name from full path, and provides
    correct path for db retrieval.
    For standard database the short name is the name given by the user,
    and path name is empty.
    Example
    cfg.blast.db = pdb_nt -> 'pdb_nt', '', 'pdb-nt'
    cfg.blast.db = gs://example/pdb_nt -> 'pdb_nt', 'gs://example/pdb_nt', 'pdb-nt'
    """
    db = blastdb
    db_path = ''
    if db.startswith('gs://'):
        # Custom database, just check the presence
        try:
            proc = safe_exec(f'gsutil ls {db}.*')
        except SafeExecError:
            raise ValueError(f'Error requesting for {db}.*')
        output = proc.stdout.decode()
        if not output:
            raise ValueError(f'There are no files at the bucket {db}.*')
        fnames: List[str] = output.split('\n')
        res = reduce(lambda x, y: x or y.endswith('tar.gz'), fnames, False)
        if res:
            db_path = db + '.tar.gz'
        else:
            db_path = db + '.*'
        db = os.path.basename(db)
    return db, db_path, sanitize_for_k8s(db)


def get_blastdb_size(db: str, db_source: DBSource) -> float:
    """Request blast database size from GCP using gcp module
    If applied to custom db, just check the presence
    Returns the size in GB, if not found raises ValueError exception

    cfg: application configuration object
    """
    if db.startswith('gs://'):
        # Custom database, just check the presence
        try:
            safe_exec(f'gsutil ls {db}.*')
        except SafeExecError:
            raise ValueError(f'BLAST database {db} was not found')
        # TODO: find a way to check custom DB size w/o transferring it to user machine
        return 1000000
    if db_source == DBSource.GCP:
        return gcp_get_blastdb_size(db)
    elif db_source == DBSource.AWS:
        return 1000000   # FIXME
    raise NotImplementedError("Not implemented for sources other than GCP")


def gcp_get_blastdb_latest_path() -> str:
    """Get latest path of GCP-based blastdb repository"""
    cmd = f'gsutil cat {GCS_DFLT_BUCKET}/latest-dir'
    proc = safe_exec(cmd)
    return os.path.join(GCS_DFLT_BUCKET, proc.stdout.decode().rstrip())


def gcp_get_blastdb_size(db: str) -> float:
    """Request blast database size from GCP using gsutil
    Returns the size in GB, if not found raises ValueError exception

    db: database name
    """
    latest_path = gcp_get_blastdb_latest_path()
    cmd = f'gsutil cat {latest_path}/blastdb-manifest.json'
    proc = safe_exec(cmd)
    blastdb_metadata = json.loads(proc.stdout.decode())
    if not db in blastdb_metadata:
        raise ValueError(f'BLAST database {db} was not found')
    return blastdb_metadata[db]['size']


def check_positive_int(val: str) -> int:
    """Function to check the passed value is a positive integer"""
    try:
        retval = int(val)
    except ValueError:
        raise ValueError(f'"{val}" is not a number')
    if retval <= 0:
        raise ValueError(f"('{retval}') is not a positive integer")
    return retval


class K8sTimestampFormatter(logging.Formatter):
    """ Class to support formatting timestamps in a way reported by
    Kubernetes logs.
    Timestamps are in UTC, microseconds can be used in the format string
    as '%f'. """
    # To satisfy typecheks we can't reuse converter - so we introduce
    # another one
    my_converter = datetime.datetime.utcfromtimestamp

    def formatTime(self, record, datefmt=None):
        ct = self.my_converter(record.created)
        if datefmt:
            s = ct.strftime(datefmt)
        else:
            t = ct.strftime("%Y-%m-%d %H:%M:%S")
            s = "%s.%06d" % (t, record.msecs)
        return s


def config_logging(args: argparse.Namespace) -> None:
    """Configures logging module.

    Assumes command line arguments has logfile and loglevel fields.
    loglevel should be one of "DEBUG", "INFO", "WARNING", "ERROR", or
    "CRITICAL"
    """

    logformat_for_file = "%(asctime)s %(levelname)s: %(message)s"
    logformat_for_stderr = "%(levelname)s: %(message)s"
    datefmt = '%Y-%m-%dT%H:%M:%S.%fZ'

    if not hasattr(args, 'loglevel'):
        if 'ELB_LOGLEVEL' in os.environ:
            args.loglevel = os.environ['ELB_LOGLEVEL']
        else:
            args.loglevel = ELB_DFLT_LOGLEVEL

    if not hasattr(args, 'logfile'):
        if 'ELB_LOGFILE' in os.environ:
            args.logfile = os.environ['ELB_LOGFILE']
        else:
            args.logfile = ELB_DFLT_LOGFILE

    if args.logfile == 'stderr':
        logger = logging.getLogger()
        logger.setLevel(_str2ll(args.loglevel))
        handler = logging.StreamHandler()
        formatter = K8sTimestampFormatter(fmt=logformat_for_file, datefmt=datefmt)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    else:
        logger = logging.getLogger()
        logger.setLevel(_str2ll(args.loglevel))

        # to stderr
        handler = logging.StreamHandler()
        handler.setLevel(logging.WARNING)
        handler.setFormatter(logging.Formatter(logformat_for_stderr))
        logger.addHandler(handler)

        # to a file
        fhandler = logging.FileHandler(args.logfile, mode='a')
        fhandler.setLevel(_str2ll(args.loglevel))
        formatter = K8sTimestampFormatter(fmt=logformat_for_file, datefmt=datefmt)
        fhandler.setFormatter(formatter)
        logger.addHandler(fhandler)

    logging.logThreads = False
    logging.logProcesses = False
    #logging._srcfile = None

    # Hide DEBUG boto logs for now
    for _ in ['boto3', 'botocore', 'urllib3', 's3transfer', 'awslimitchecker']:
        logging.getLogger(_).setLevel(logging.CRITICAL)


def _str2ll(level: str) -> int:
    """ Converts the log level argument to a numeric value.

    Throws an exception if conversion can't be done.
    Copied from the logging howto documentation
    """
    retval = getattr(logging, level.upper(), None)
    if not isinstance(retval, int):
        raise ValueError(f'Invalid log level: {level}')
    return retval


class UserReportError(ElasticBlastBaseException):
    """Exception which is reported as a user visible error, needs to be caught
    at the main function.
    Attributes:
        returncode: Return code from elastic-blast application as described in
                    the user manual
        message: Error message"""
    pass


def sanitize_for_k8s(input_string: str) -> str:
    """ Changes the input_string so that it is composed of valid characters for a k8s job"""
    return re.sub(r'_', '-', input_string.lower(), flags=re.ASCII)


def sanitize_aws_batch_job_name(input_name: str) -> str:
    """ Changes the input_name so that it is composed of valid AWS Batch job name characters"""
    return re.sub(r'[\W\-]', '-', input_name.strip(), flags=re.ASCII)[:AWS_MAX_JOBNAME_LENGTH]

# def convert_labels_to_aws_tags(labels: str) -> List[ {} ]:
def convert_labels_to_aws_tags(labels: str):
    """ Converts the input string into a list of tags suitable to tag AWS
    resources."""
    retval = []
    for token in labels.split(','):
        k, v = token.split('=')
        # Change some keys to follow NCBI guidelines and AWS conventions
        if k == 'owner': k = 'Owner'
        if k == 'project': k = 'Project'
        if k == 'name': k ='Name'
        retval.append({'Key': k, 'Value': v})
    return retval


def convert_memory_to_mb(size: str) -> int:
    """ Convert memory to MB for usage in AWS::Batch::JobDefinition ContainerProperties.
    Documentation:
    https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-batch-jobdefinition-containerproperties.html#cfn-batch-jobdefinition-containerproperties-memory
    """
    sz = size.lower()
    if sz.endswith('g'):
        return int(float(size[0:-1]) * 1000)
    elif sz.endswith('m'):
        return int(size[0:-1])
    elif sz.endswith('t'):
        return int(float(size[0:-1])*1000*1000)
    else:  # Assume GB, per gcloud docs
        return int(int(sz)*1000)


def convert_disk_size_to_gb(size: str) -> int:
    """ Convert disk size for usage in AWS Ebs::VolumeSize CloudFormation template
    Relevant documentation:
    https://cloud.google.com/sdk/gcloud/reference/container/clusters/create#--disk-size
    https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-ec2-launchtemplate-blockdevicemapping-ebs.html#cfn-ec2-launchtemplate-blockdevicemapping-ebs-volumesize
    """
    sz = size.lower()
    if sz.endswith('g'):
        rv = float(size[0:-1])
        return int(1 if rv < 1.0 else rv)
    elif sz.endswith('m'):
        rv = float(size[0:-1])/1000
        return int(1 if rv < 1.0 else rv)
    elif sz.endswith('t'):
        return int(float(size[0:-1])*1000)
    else:  # Assume GB, per gcloud docs
        return int(sz)


def validate_gke_cluster_name(val: str) -> None:
    """Test whether a given string is a legal GKE cluster name

    Raises:
        ValueError if the string is not a legal GKE cluster name"""

    # ERROR: (gcloud.container.clusters.create) ResponseError: code=400,
    # message=Invalid value for field "cluster.name": "invalid_CLUSTER". Must be
    # a match of regex '(?:[a-z](?:[-a-z0-9]{0,38}[a-z0-9])?)' (only
    # alphanumerics and '-' allowed, must start with a letter and end with an
    # alphanumeric, and must be no longer than 40 characters).
    if re.fullmatch(r'(?:[a-z](?:[-a-z0-9]{0,38}[a-z0-9])?)', val) is None:
        raise ValueError(f'"{val}" is not a valid GKE cluster name. The string must be less than 40 characters and can only contain lowercase letters, digits, and dashes.')


def validate_gcp_disk_name(val: str) -> None:
    """Test whether a given string is a legal GCE disk name

    Raises:
        ValueError id the string is not a legal GCE disk name"""
    if re.fullmatch(r'(?:[a-z](?:[-a-z0-9]{0,61}[a-z0-9])?)', val) is None:
        raise ValueError(f'"{val}" is not a valid GCE disk name. The string must be less than 61 characters long and can only contain lowercase letters, digits, and dashes.')


def validate_gcp_string(val: str) -> None:
    """Test whether a given string is a legal GCP id: containes only lowercase
    letters, digits, underscores, and dashes.

    Raises:
        ValueError if the string is not a legal GCP id"""
    if re.match(r'^[a-z0-9_\-]+$', val) is None:
        raise ValueError(f'"{val}" is not a legal GCP id. The string can only contain lowercase letters, digits, underscores, and dashes.')


def check_aws_region_for_invalid_characters(val: str) -> None:
    """Test whether a given string is an acceptable AWS region name:
    alphanumeric characters, plus dashes.

    Raises:
        ValueError if the string is not a legal AWS region name"""
    if re.match(r'^[A-Za-z0-9\-]+$', val) is None:
        raise ValueError(f'{val} is not a legal AWS region name. The string can only contain letters, numbers, and dashes.')


def clean_up(clean_up_stack: List[Callable]) -> List[str]:
    """Execute a list of cleanup procedures provided as a stack of Callable objects"""
    logging.debug('Clean up with stack %s',
                  ', '.join(map(repr, clean_up_stack)))
    messages = []
    while clean_up_stack:
        try:
            while clean_up_stack:
                logging.debug('start cleanup stage')
                stage = clean_up_stack[-1]
                try:
                    stage()
                except KeyboardInterrupt:
                    raise
                except Exception as err:
                    logging.error(f'cleanup stage failed: {err}')
                    messages.append(str(err))
                else:
                    logging.debug('end cleanup stage')
                clean_up_stack.pop()
        except KeyboardInterrupt:
            logging.error('Application cleanup is in progress, please wait until it completes')

    return messages


def get_usage_reporting() -> bool:
    """ Use environment variable to get Usage Reporting status 
    as described in https://www.ncbi.nlm.nih.gov/books/NBK563686
    """
    usage_reporting = os.environ.get('BLAST_USAGE_REPORT', 'true')
    if usage_reporting.lower() == 'false':
        return False
    return True


def gcp_get_regions() -> List[str]:
    """ Retrieves a list of available GCP region names """
    cmd = "gcloud compute regions list --format json"
    retval = []
    try:
        p = safe_exec(cmd)
        region_info = json.loads(p.stdout.decode())
        retval = [i['name'] for i in region_info]
    except Exception as err:
        logging.debug(err)
    return retval


def get_resubmission_error_msg(results: str, cloud: CSP) -> str:
    """ Gets a formatted error message for the case when an ElasticBLAST
    has already been submitted
    """
    retval = 'An ElasticBLAST search that will write results to '
    retval += f'{results} has already been submitted.\n'
    retval += 'Please resubmit your search with a different value '
    retval += 'for "results" configuration parameter, or save '
    retval += 'the ElasticBLAST results and then either delete '
    retval += 'the previous ElasticBLAST search by running '
    retval += 'elastic-blast delete, or run the command '
    if cloud == CSP.AWS:
        retval += f'aws s3 rm --recursive --only-show-errors {results}'
    else:
        retval += f'gsutil -qm rm -r {results}'
    return retval
