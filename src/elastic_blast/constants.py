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
src/elb/constants.py - Definitions for constants used in ElasticBLAST

Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
Created: Thu 21 May 2020 06:34:22 AM EDT
"""

from enum import Enum, auto


class CSP(Enum):
    """ Defines the supported Cloud Service Providers """
    GCP = auto()
    AWS = auto()
    def __repr__(self):
        return f"'{self.name}'"


class ElbCommand(Enum):
    """Defines elastic-blast command"""
    SUBMIT = 'submit'
    STATUS = 'status'
    DELETE = 'delete'
    RUN_SUMMARY = 'run-summary'


class ElbStatus(Enum):
    """ Defines the status of an ElasticBLAST search """
    CREATING = auto()
    DELETING = auto()
    SUBMITTING = auto()
    SUCCESS = auto()
    FAILURE = auto()
    RUNNING = auto()
    UNKNOWN = auto()

    def __str__(self):
        """ Convert value to a string """
        return self.name


class QuerySplitMode(Enum):
    """ Query split mode - client, cloud 1 stage, cloud 2 stage """
    CLIENT = auto()
    CLOUD_ONE_STAGE = auto()
    CLOUD_TWO_STAGE = auto()

class AwsPricing(Enum):
    """ Defines pricing model used by AWS """
    ON_DEMAND = auto()
    SPOT = auto()
    UNSUPPORTED = auto()

class ElbExecutionMode(Enum):
    """ Defines execution mode of some cluster operations """
    WAIT = auto()
    NOWAIT = auto()

# Number of seconds to wait after the job that initializes the persistent
# volume completes. This is to prevent mount errors in the subsequent BLAST k8s
# jobs
ELB_PAUSE_AFTER_INIT_PV = 150

# How much RAM is recommended relative to the BLASTDB size
ELB_BLASTDB_MEMORY_MARGIN = 1.1

# How much memory on an instance is reserved for system and framework (k8s or
# AWS Batch) in GB
SYSTEM_MEMORY_RESERVE = 2 # FIXME: Interim value so that release 0.0.25 can go through

# Memory to reserve for BLAST hits in GB
MEMORY_FOR_BLAST_HITS = 2

# Default BLAST output format
ELB_DFLT_OUTFMT = 11

ELB_DFLT_USE_PREEMPTIBLE = False

ELB_DFLT_GCP_PD_SIZE = '3000G'

ELB_DFLT_GCP_MACHINE_TYPE = 'n1-highmem-32'
ELB_DFLT_AWS_MACHINE_TYPE = 'm5.8xlarge'
ELB_AWS_ARM_INSTANCE_TYPE_REGEX = r'^a1|^[a-z][1-9]g'

ELB_DFLT_GCP_NUM_CPUS = 15
ELB_DFLT_AWS_NUM_CPUS = 16

ELB_DFLT_NUM_NODES = 1
ELB_DFLT_MIN_NUM_NODES = 1

ELB_S3_PREFIX = 's3://'
ELB_GCS_PREFIX = 'gs://'
ELB_HTTP_PREFIX = 'http'
ELB_FTP_PREFIX = 'ftp://'

ELB_UNKNOWN_NUMBER_OF_QUERY_SPLITS = -1
ELB_UNKNOWN_MAX_NUMBER_OF_CONCURRENT_JOBS = -1

ELB_UNKNOWN = 'Unknown'

# Ancillary ElasticBLAST "directories" and files in output bucket
ELB_QUERY_BATCH_DIR = 'query_batches'
ELB_QUERY_BATCH_FILE_PREFIX = 'batch_'
ELB_METADATA_DIR = 'metadata'
ELB_STATE_DISK_ID_FILE = 'disk-id.txt'
ELB_LOG_DIR = 'logs'
ELB_BACKEND_LOG = 'backends.log'
ELB_TAXIDLIST_FILE = 'taxidlist.txt'
ELB_META_CONFIG_FILE = 'elastic-blast-config.json'
ELB_AWS_JOB_IDS = 'job-ids.json'
ELB_QUERY_LENGTH = 'query_length.txt'
ELB_GCP_BATCH_LIST = 'batch_list.txt'
# this file contents should match the number of lines in ELB_GCP_BATCH_LIST 
ELB_NUM_JOBS_SUBMITTED = 'num_jobs_submitted.txt'

# These values indicate that a field has not been configured by the end user
ELB_NOT_INITIALIZED_NUM = 2**32
ELB_NOT_INITIALIZED_MEM = '4294967296T'

# Timeouts in minutes
ELB_DFLT_BLAST_K8S_TIMEOUT = 10080  # 1 week
ELB_DFLT_INIT_PV_TIMEOUT = 45

ELB_DFLT_BLASTDB_SOURCE = 'gcp'

ELB_DFLT_BLAST_JOB_TEMPLATE = 'resource:templates/blast-batch-job.yaml.template'
ELB_LOCAL_SSD_BLAST_JOB_TEMPLATE = 'resource:templates/blast-batch-job-local-ssd.yaml.template'
GCS_DFLT_BUCKET = 'gs://blast-db'

GCP_APIS = ['serviceusage', 'container', 'storage-api', 'storage-component']
# https://cloud.google.com/kubernetes-engine/docs/how-to/creating-managing-labels#requirements
GCP_MAX_NUM_LABELS = 64
# https://cloud.google.com/kubernetes-engine/docs/how-to/creating-managing-labels#requirements
GCP_MAX_LABEL_LENGTH = 63 
# https://docs.aws.amazon.com/acm/latest/userguide/tags-restrictions.html
AWS_MAX_NUM_LABELS = 50
# https://docs.aws.amazon.com/acm/latest/userguide/tags-restrictions.html
AWS_MAX_TAG_LENGTH = 255
# https://docs.aws.amazon.com/batch/latest/APIReference/API_SubmitJob.html#API_SubmitJob_RequestSyntax
AWS_MAX_JOBNAME_LENGTH = 128

# Kubernetes job submission retry parameters
ELB_K8S_JOB_SUBMISSION_MAX_RETRIES=5    # Try up to this many times
ELB_K8S_JOB_SUBMISSION_TIMEOUT=600      # or a maximum of this many seconds
ELB_K8S_JOB_SUBMISSION_MIN_WAIT=1       # Randomly wait between 1 and ...
ELB_K8S_JOB_SUBMISSION_MAX_WAIT=5       # ... 5 seconds


# Exit codes
INPUT_ERROR = 1             # used errors in query, configuration/CLI, or BLAST options
BLASTDB_ERROR = 2
BLAST_ENGINE_ERROR = 3
OUT_OF_MEMORY_ERROR = 4
TIMEOUT_ERROR = 5
PERMISSIONS_ERROR = 6
# Used for missing external dependencies or availability of cloud resources
DEPENDENCY_ERROR = 7
CLUSTER_ERROR = 8
INTERRUPT_ERROR = 9
NOT_READY_ERROR = 10
UNKNOWN_ERROR = 255

class MolType(Enum):
    """Sequence molecular type"""
    PROTEIN = 'prot'
    NUCLEOTIDE = 'nucl'
    UNKNOWN = 'unknown'

    @classmethod
    def valid_choices(self):
        """ Return a list of valid choices, suitable for the choices argument in argparse"""
        return [str(self.PROTEIN), str(self.NUCLEOTIDE)]

    def __str__(self):
        """Convert value to a string"""
        return self.value


ELB_DFLT_GCP_REGION = 'us-east4'
ELB_DFLT_AWS_REGION = 'us-east-1'

ELB_DOCKER_VERSION = '1.0.0'
ELB_QS_DOCKER_VERSION = '0.0.6'
ELB_JANITOR_DOCKER_VERSION = '0.1.1'
ELB_JOB_SUBMIT_DOCKER_VERSION = '1.1.2'

ELB_DOCKER_IMAGE_GCP = f'gcr.io/ncbi-sandbox-blast/ncbi/elb:{ELB_DOCKER_VERSION}'
ELB_DOCKER_IMAGE_AWS = f'public.ecr.aws/ncbi-elasticblast/elasticblast-elb:{ELB_DOCKER_VERSION}'

ELB_QS_DOCKER_IMAGE_GCP = f'gcr.io/ncbi-sandbox-blast/ncbi/elasticblast-query-split:{ELB_QS_DOCKER_VERSION}'
ELB_QS_DOCKER_IMAGE_AWS = f'public.ecr.aws/ncbi-elasticblast/elasticblast-query-split:{ELB_QS_DOCKER_VERSION}'

ELB_JANITOR_DOCKER_IMAGE_GCP = f'gcr.io/ncbi-sandbox-blast/ncbi/elasticblast-janitor:{ELB_JANITOR_DOCKER_VERSION}'

ELB_CJS_DOCKER_IMAGE_GCP = f'gcr.io/ncbi-sandbox-blast/ncbi/elasticblast-job-submit:{ELB_JOB_SUBMIT_DOCKER_VERSION}'
ELB_CJS_DOCKER_IMAGE_AWS = f'public.ecr.aws/ncbi-elasticblast/elasticblast-job-submit:{ELB_JOB_SUBMIT_DOCKER_VERSION}'

ELB_DFLT_AWS_DISK_TYPE = 'gp3'
ELB_DFLT_AWS_PD_SIZE = '1000G'
# Only relevant if the disk-type is set to io2
ELB_DFLT_AWS_PROVISIONED_IOPS = '2000'
ELB_DFLT_AWS_SPOT_BID_PERCENTAGE = '100'

# Config sections
CFG_CLOUD_PROVIDER = 'cloud-provider'
CFG_CLUSTER = 'cluster'
CFG_BLAST = 'blast'
CFG_TIMEOUTS = 'timeouts'
# Config keys
# Cloud provider
CFG_CP_NAME = 'name'
CFG_CP_GCP_PROJECT = 'gcp-project'
CFG_CP_GCP_REGION = 'gcp-region'
CFG_CP_GCP_ZONE = 'gcp-zone'
CFG_CP_GCP_NETWORK = 'gcp-network'
CFG_CP_GCP_SUBNETWORK = 'gcp-subnetwork'
CFG_CP_AWS_REGION = 'aws-region'
CFG_CP_AWS_KEY_PAIR = 'aws-key-pair'
CFG_CP_AWS_VPC = 'aws-vpc'
CFG_CP_AWS_SUBNET = 'aws-subnet'
CFG_CP_AWS_SECURITY_GROUP = 'aws-security-group'
CFG_CP_AWS_JOB_ROLE = 'aws-job-role'
CFG_CP_AWS_INSTANCE_ROLE = 'aws-instance-role'
CFG_CP_AWS_BATCH_SERVICE_ROLE = 'aws-batch-service-role'
CFG_CP_AWS_SPOT_FLEET_ROLE = 'aws-spot-fleet-role'
CFG_CP_AWS_AUTO_SHUTDOWN_ROLE = 'aws-auto-shutdown-role'
# Cluster
CFG_CLUSTER_DRY_RUN = 'dry-run'
CFG_CLUSTER_NAME = 'name'
CFG_CLUSTER_MACHINE_TYPE = 'machine-type'
CFG_CLUSTER_LABELS = 'labels'
CFG_CLUSTER_NUM_NODES = 'num-nodes'
CFG_CLUSTER_NUM_CPUS = 'num-cpus'
CFG_CLUSTER_DISK_TYPE = 'disk-type'
CFG_CLUSTER_PD_SIZE = 'pd-size'
CFG_CLUSTER_PROVISIONED_IOPS = 'provisioned-iops'
CFG_CLUSTER_USE_PREEMPTIBLE = 'use-preemptible'
CFG_CLUSTER_BID_PERCENTAGE = 'bid-percentage'
CFG_CLUSTER_EXP_USE_LOCAL_SSD = 'exp-use-local-ssd'
CFG_CLUSTER_ENABLE_STACKDRIVER = 'enable-stackdriver'
# Blast
CFG_BLAST_PROGRAM = 'program'
CFG_BLAST_DB = 'db'
CFG_BLAST_DB_SRC = 'blastdb-src'
CFG_BLAST_DB_MEM_MARGIN = 'db-memory-margin'
CFG_BLAST_RESULTS = 'results'
CFG_BLAST_QUERY = 'queries'
CFG_BLAST_OPTIONS = 'options'
CFG_BLAST_BATCH_LEN = 'batch-len'
CFG_BLAST_MEM_REQUEST = 'mem-request'
CFG_BLAST_MEM_LIMIT = 'mem-limit'
CFG_BLAST_TAXIDLIST = 'taxidlist'
# Timeouts
CFG_TIMEOUT_INIT_PV = 'init-pv'
CFG_TIMEOUT_BLAST_K8S_JOB = 'blast-k8s-job'

# State piggybacked in Config object
APP_STATE = 'app-state'
APP_STATE_DISK_ID = 'disk-id'
APP_STATE_RESULTS_MD5 = 'results-md5'

AWS_ROLE_PREFIX = 'arn:aws:iam::'

AWS_JANITOR_ROLE_NAME = 'ncbi-elasticblast-janitor-role'

# Kubernetes job names

K8S_JOB_GET_BLASTDB = 'get-blastdb'
K8S_JOB_LOAD_BLASTDB_INTO_RAM = 'load-blastdb-into-ram'
K8S_JOB_IMPORT_QUERY_BATCHES = 'import-query-batches'
K8S_JOB_SUBMIT_JOBS = 'submit-jobs'
K8S_JOB_BLAST = 'blast'
K8S_JOB_RESULTS_EXPORT = 'results-export'

# Number of jobs per directory after which the jobs are submitted individually to minimize timeouts
K8S_MAX_JOBS_PER_DIR = 100

K8S_UNINITIALIZED_CONTEXT = 'uninitialized-k8s-context'

# GKE status names
GKE_CLUSTER_STATUS_PROVISIONING = 'PROVISIONING'
GKE_CLUSTER_STATUS_RECONCILING = 'RECONCILING'
GKE_CLUSTER_STATUS_RUNNING = 'RUNNING'
GKE_CLUSTER_STATUS_RUNNING_WITH_ERROR = 'RUNNING_WITH_ERROR'
GKE_CLUSTER_STATUS_STOPPING = 'STOPPING'
GKE_CLUSTER_STATUS_ERROR = 'ERROR'

# File names of the sentinel files which indicate status reported by janitor
ELB_STATUS_SUCCESS = "SUCCESS.txt"
ELB_STATUS_FAILURE = "FAILURE.txt"

# https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/#cron-schedule-syntax
ELB_DFLT_JANITOR_SCHEDULE_GCP = "*/5 * * * *"
# https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-create-rule-schedule.html
ELB_DFLT_JANITOR_SCHEDULE_AWS = "cron(*/5 * * * ? *)"

ELB_AWS_JANITOR_LAMBDA_DEPLOYMENT_BUCKET = 'elb-camacho'
ELB_AWS_JANITOR_LAMBDA_DEPLOYMENT_KEY = 'functions/'
ELB_AWS_JANITOR_CFN_TEMPLATE = 'https://elb-camacho.s3.amazonaws.com/templates/elastic-blast-janitor-cf.yaml'

# extension for files containing list of query files
QUERY_LIST_EXT = '.query-list'

ELB_DFLT_NUM_BATCHES_FOR_TESTING = 100
ELB_DFLT_LOGLEVEL = 'DEBUG'
ELB_DFLT_LOGFILE = 'elastic-blast.log'
