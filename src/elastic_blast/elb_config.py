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
elb/elb_config.py - ElasticBLAST config

Author: Greg Boratyn (boratyng@ncbi.nlm.nih.gov)
Created: Tue 09 Feb 2021 03:52:31 PM EDT
"""

import os
from dataclasses import dataclass
from dataclasses import InitVar, field, fields, asdict
from dataclasses_json import dataclass_json, LetterCase, config
import getpass
from hashlib import md5
import configparser
import re
import time
import datetime
import socket
import logging
import shlex
from collections import defaultdict
import json
import boto3 # type: ignore
from enum import Enum
from typing import Optional, List, Dict, Any
from typing import cast
from . import VERSION
from .constants import CSP, ElbCommand
from .constants import ELB_DFLT_NUM_NODES
from .constants import ELB_DFLT_USE_PREEMPTIBLE
from .constants import ELB_DFLT_GCP_PD_SIZE, ELB_DFLT_AWS_PD_SIZE
from .constants import ELB_DFLT_GCP_MACHINE_TYPE, ELB_DFLT_AWS_MACHINE_TYPE
from .constants import ELB_DFLT_INIT_PV_TIMEOUT, ELB_DFLT_BLAST_K8S_TIMEOUT
from .constants import ELB_DFLT_AWS_SPOT_BID_PERCENTAGE
from .constants import ELB_DFLT_AWS_DISK_TYPE, ELB_DFLT_OUTFMT
from .constants import ELB_BLASTDB_MEMORY_MARGIN
from .constants import CFG_CLOUD_PROVIDER
from .constants import CFG_CP_GCP_PROJECT, CFG_CP_GCP_REGION, CFG_CP_GCP_ZONE
from .constants import CFG_CP_GCP_NETWORK, CFG_CP_GCP_SUBNETWORK
from .constants import CFG_CP_GCP_GKE_VERSION
from .constants import CFG_CP_AWS_REGION, CFG_CP_AWS_VPC, CFG_CP_AWS_SUBNET
from .constants import CFG_CP_AWS_JOB_ROLE, CFG_CP_AWS_BATCH_SERVICE_ROLE
from .constants import CFG_CP_AWS_INSTANCE_ROLE, CFG_CP_AWS_SPOT_FLEET_ROLE
from .constants import CFG_CP_AWS_SECURITY_GROUP, CFG_CP_AWS_KEY_PAIR
from .constants import CFG_BLAST, CFG_BLAST_PROGRAM, CFG_BLAST_DB
from .constants import CFG_BLAST_DB_SRC, CFG_BLAST_RESULTS, CFG_BLAST_QUERY
from .constants import CFG_BLAST_OPTIONS, CFG_BLAST_BATCH_LEN
from .constants import CFG_BLAST_MEM_REQUEST, CFG_BLAST_MEM_LIMIT
from .constants import CFG_BLAST_DB_MEM_MARGIN
from .constants import CFG_CLUSTER, CFG_CLUSTER_NAME, CFG_CLUSTER_MACHINE_TYPE
from .constants import CFG_CLUSTER_NUM_NODES, CFG_CLUSTER_NUM_CPUS
from .constants import CFG_CLUSTER_PD_SIZE, CFG_CLUSTER_USE_PREEMPTIBLE
from .constants import CFG_CLUSTER_DRY_RUN, CFG_CLUSTER_DISK_TYPE
from .constants import CFG_CLUSTER_PROVISIONED_IOPS, CFG_CLUSTER_BID_PERCENTAGE
from .constants import CFG_CLUSTER_LABELS, CFG_CLUSTER_EXP_USE_LOCAL_SSD
from .constants import CFG_CLUSTER_ENABLE_STACKDRIVER
from .constants import CFG_TIMEOUTS, CFG_TIMEOUT_INIT_PV
from .constants import CFG_TIMEOUT_BLAST_K8S_JOB
from .constants import INPUT_ERROR, ELB_NOT_INITIALIZED_MEM, ELB_NOT_INITIALIZED_NUM
from .constants import GCP_MAX_LABEL_LENGTH, AWS_MAX_TAG_LENGTH
from .constants import GCP_MAX_NUM_LABELS, AWS_MAX_NUM_LABELS
from .constants import SYSTEM_MEMORY_RESERVE, ELB_AWS_ARM_INSTANCE_TYPE_REGEX
from .constants import ELB_DFLT_AWS_NUM_CPUS, ELB_DFLT_GCP_NUM_CPUS
from .constants import ELB_S3_PREFIX, ELB_GCS_PREFIX, ELB_UNKNOWN_MAX_NUMBER_OF_CONCURRENT_JOBS
from .constants import AWS_ROLE_PREFIX, CFG_CP_AWS_AUTO_SHUTDOWN_ROLE
from .constants import BLASTDB_ERROR, ELB_UNKNOWN, ELB_JANITOR_SCHEDULE
from .constants import ELB_DFLT_GCP_REGION, ELB_DFLT_GCP_ZONE
from .constants import ELB_DFLT_AWS_REGION, ELB_UNKNOWN_GCP_PROJECT
from .util import validate_gcp_string, check_aws_region_for_invalid_characters
from .util import validate_gke_cluster_name, ElbSupportedPrograms
from .util import get_query_batch_size
from .util import UserReportError, safe_exec
from .util import gcp_get_regions, sanitize_for_k8s
from .gcp_traits import get_machine_properties as gcp_get_machine_properties
from .aws_traits import get_machine_properties as aws_get_machine_properties
from .aws_traits import get_regions as aws_get_regions
from .aws_traits import create_aws_config
from .base import InstanceProperties, PositiveInteger, Percentage
from .base import ParamInfo, ConfigParserToDataclassMapper, DBSource, MemoryStr
from .config import validate_cloud_storage_object_uri, _validate_csp
from .db_metadata import DbMetadata, get_db_metadata
from .tuner import get_mem_limit, get_machine_type, get_mt_mode, get_batch_length
from .tuner import MTMode


# Config parameter types

class CloudURI(str):
    """A subclass of str that only accepts valid cloud bucket URIs and
    computes md5 hash value of the URI. The value
    is validated before object creation. The hashed value is available via
    class attribute md5 or via method compute_md5"""
    def __new__(cls, value):
        """Constructor, validates that argumant is a valid cloud bucket uri"""
        validate_cloud_storage_object_uri(str(value))
        # canonicalize path
        canonical_value = str(value)[:-1] if str(value)[-1] == '/' else value
        return super(cls, cls).__new__(cls, canonical_value)

    def __init__(self, value):
        """Initialize md5 hashed cloud URI"""
        self.md5 = None
        self.compute_md5()

    def compute_md5(self) -> str:
        """Compute hashed URI and store hashed value in object attribute"""
        if self.md5:
            return self.md5
        else:
            digest = md5(self.encode())
            short_digest = digest.hexdigest()[0:9]
            self.md5 = short_digest
        return self.md5

    def get_cloud_provider(self) -> CSP:
        """Find URI's cloud provider"""
        if self.startswith(ELB_S3_PREFIX):
            return CSP.AWS
        elif self.startswith(ELB_GCS_PREFIX):
            return CSP.GCP
        else:
            raise ValueError(f'Unrecognized cloud bucket prefix in: "{self}". Object URI must start with {ELB_GCS_PREFIX} or {ELB_S3_PREFIX}.')


class GCPString(str):
    """A subclass of str that only accepts valid GCP names. The value
    is screend for invalid characters before object creation"""
    def __new__(cls, value):
        """Constructor, validates that argumant is a valid GCP name"""
        validate_gcp_string(str(value))
        return super(cls, cls).__new__(cls, value)

    def validate(self, dry_run: bool = False):
        """ Validate the value of this object is one of the valid GCP
        regions. """
        if dry_run: return
        regions = gcp_get_regions()
        if not regions:
            raise RuntimeError(f'Got no GCP regions')
        if self not in regions:
            msg = f'{self} is not a valid GCP region'
            raise ValueError(msg)


class AWSRegion(str):
    """A subclass of str that only accepts valid AWS strings. The value
    is screened for invalid characters before object creation"""
    def __new__(cls, value):
        """Constructor, validates that argumant is a valid GCP name"""
        check_aws_region_for_invalid_characters(str(value))
        return super(cls, cls).__new__(cls, value)

    def validate(self, dry_run: bool = False):
        """ Validate the value of this object is one of the valid AWS
        regions. Requires AWS credentials to invoke proper APIs """
        if dry_run: return
        regions = aws_get_regions()
        if str(self) not in regions:
            msg = f'{str(self)} is not a valid AWS region'
            raise ValueError(msg)


class BLASTProgram(str):
    """A subclass of str that only accepts BLAST programs supported by
    ElastcBLAST as str. The value is validated before object creation"""
    def __new__(cls, value):
        """Constructor, validates that argumant is a valid GCP name"""
        sp = ElbSupportedPrograms()
        str_value = str(value).lower()
        sp.check(str_value)
        return super(cls, cls).__new__(cls, str_value)


# Classes that define config sections
# Classes that inherit from ConfigParserToDataMapper can be initialized
# from a ConfigParser object. They must define mapping attribute where
# each config parameter, defined as a dataclass atribute is mapped to an
# parameter in the ConfigParser object.
# Note that parameters may be in different ConfigParser sections than a
# corresponding class.

@dataclass
class CloudProviderBaseConfig:
    """Base class for cloud provider config. It contains values common for
    all cloud providers. All Cloud provider coonfig classes should inherit
    from it."""
    # name of a cloud provider, must be initialized by a child class
    cloud: CSP = field(init=False)
    region: str


@dataclass_json(letter_case=LetterCase.KEBAB)
@dataclass
class GCPConfig(CloudProviderBaseConfig, ConfigParserToDataclassMapper):
    """GCP config for ElasticBLAST"""
    region: GCPString = GCPString(ELB_DFLT_GCP_REGION)
    project: GCPString = GCPString(ELB_UNKNOWN_GCP_PROJECT)
    zone: GCPString = GCPString(ELB_DFLT_GCP_ZONE)
    network: Optional[str] = None
    subnet: Optional[str] = None
    user: Optional[str] = None
    # FIXME: This is a temporary fix for EB-1530. gke_version should be set to
    # None once the proper fix is implemented.
    gke_version: Optional[str] = '1.21'

    # mapping to class attributes to ConfigParser parameters so that objects
    # can be initialized from ConfigParser objects
    mapping = {'project': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_GCP_PROJECT),
               'region': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_GCP_REGION),
               'zone': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_GCP_ZONE),
               'cloud': None,
               'user': None,
               'network': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_GCP_NETWORK),
               'subnet': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_GCP_SUBNETWORK),
               'gke_version': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_GCP_GKE_VERSION)}
 
    def __post_init__(self):
        self.cloud = CSP.GCP
        self.user = ELB_UNKNOWN

        p = safe_exec('gcloud config get-value account')
        if p.stdout:
            self.user = p.stdout.decode('utf-8').rstrip()

        if self.project == ELB_UNKNOWN_GCP_PROJECT:
            proj = get_gcp_project()
            if not proj:
                raise ValueError(f'GCP project is unset, please invoke gcloud config set project REPLACE_WITH_YOUR_PROJECT_NAME_HERE')
            else:
                self.project = GCPString(proj)

    def validate(self, errors: List[str], task: ElbCommand):
        """Validate config"""
        if bool(self.network) != bool(self.subnet):
            errors.append('Both gcp-network and gcp-subnetwork need to be specified if one of them is specified')

@dataclass_json(letter_case=LetterCase.KEBAB)
@dataclass
class AWSConfig(CloudProviderBaseConfig, ConfigParserToDataclassMapper):
    """AWS config for ElasticBLAST"""
    region: AWSRegion = AWSRegion(ELB_DFLT_AWS_REGION)
    vpc: Optional[str] = None
    subnet: Optional[str] = None
    security_group: Optional[str] = None
    key_pair: Optional[str] = None
    job_role: Optional[str] = None
    instance_role: Optional[str] = None
    batch_service_role: Optional[str] = None
    spot_fleet_role: Optional[str] = None
    auto_shutdown_role: Optional[str] = None
    user : Optional[str] = None

    mapping = {'region': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_AWS_REGION),
               'vpc': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_AWS_VPC),
               'subnet': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_AWS_SUBNET),
               'security_group': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_AWS_SECURITY_GROUP),
               'key_pair': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_AWS_KEY_PAIR),
               'job_role': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_AWS_JOB_ROLE),
               'instance_role': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_AWS_INSTANCE_ROLE),
               'batch_service_role': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_AWS_BATCH_SERVICE_ROLE),
               'spot_fleet_role': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_AWS_SPOT_FLEET_ROLE),
               'auto_shutdown_role': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_AWS_AUTO_SHUTDOWN_ROLE),
               'cloud': None,
               'user': None}


    def __post_init__(self):
        self.cloud = CSP.AWS
        self.user = boto3.client('sts').get_caller_identity()['Arn']

    def validate(self, errors: List[str], task: ElbCommand):
        """Validate config"""
        # All roles must begin with AWS_ROLE_PREFIX
        if self.instance_role and not str(self.instance_role).startswith(AWS_ROLE_PREFIX):
            errors.append(f'{CFG_CLOUD_PROVIDER}.{CFG_CP_AWS_INSTANCE_ROLE} must start with {AWS_ROLE_PREFIX}')
        if self.batch_service_role and not str(self.batch_service_role).startswith(AWS_ROLE_PREFIX):
            errors.append(f'{CFG_CLOUD_PROVIDER}.{CFG_CP_AWS_BATCH_SERVICE_ROLE} must start with {AWS_ROLE_PREFIX}')
        if self.spot_fleet_role and not str(self.spot_fleet_role).startswith(AWS_ROLE_PREFIX):
            errors.append(f'{CFG_CLOUD_PROVIDER}.{CFG_CP_AWS_SPOT_FLEET_ROLE} must start with {AWS_ROLE_PREFIX}')
        if self.auto_shutdown_role and not str(self.auto_shutdown_role).startswith(AWS_ROLE_PREFIX):
            errors.append(f'{CFG_CLOUD_PROVIDER}.{CFG_CP_AWS_AUTO_SHUTDOWN_ROLE} must start with {AWS_ROLE_PREFIX}')


@dataclass_json(letter_case=LetterCase.KEBAB)
@dataclass
class BlastConfig(ConfigParserToDataclassMapper):
    """ElasticBLAST BLAST parameters"""
    program: BLASTProgram  # maybe enum?
    db: str
    queries_arg: str
    batch_len: PositiveInteger = PositiveInteger(ELB_NOT_INITIALIZED_NUM)
    queries: List[str] = field(default_factory=list, init=False)
    options: str = f'-outfmt {ELB_DFLT_OUTFMT}'
    taxidlist: Optional[str] = None
    db_mem_margin: float = ELB_BLASTDB_MEMORY_MARGIN
    user_provided_batch_len: bool = False

    # database metadata, not part of config
    db_metadata: Optional[DbMetadata] = None

    mapping = {'program': ParamInfo(CFG_BLAST, CFG_BLAST_PROGRAM),
               'db': ParamInfo(CFG_BLAST, CFG_BLAST_DB),
               'queries_arg': ParamInfo(CFG_BLAST, CFG_BLAST_QUERY),
               'queries': None,
               'batch_len': ParamInfo(CFG_BLAST, CFG_BLAST_BATCH_LEN),
               'options': ParamInfo(CFG_BLAST, CFG_BLAST_OPTIONS),
               # taxid list is parsed from BLAST options
               'taxidlist': None,
               'db_mem_margin': ParamInfo(CFG_BLAST, CFG_BLAST_DB_MEM_MARGIN),
               'db_metadata': None,
               'user_provided_batch_len': None}
               

    def __post_init__(self):
        if self.options.find('-outfmt') < 0:
            self.options += f' -outfmt {ELB_DFLT_OUTFMT}'


    def validate(self, errors: List[str], task: ElbCommand):
        """Validate config"""
        if task != ElbCommand.SUBMIT:
            return

        UNSUPPORTED_OPTIONS = set([
            '-remote',
            '-seqidlist',
            '-negative_seqidlist',
            '-gilist',
            '-negative_gilist',
            '-filtering_db',
            '-use_index',
            '-index_name',
            '-in_pssm',
            '-in_msa'
        ])
        for query_file in self.queries_arg.split():
            if query_file.startswith(ELB_S3_PREFIX) or query_file.startswith(ELB_GCS_PREFIX):
                try:
                    validate_cloud_storage_object_uri(query_file)
                except ValueError as err:
                    errors.append(f'Incorrect queries URI "{query_file}": {str(err)}')
        try:
            options = shlex.split(self.options)
            unsupported_options = set(options).intersection(UNSUPPORTED_OPTIONS)
            if unsupported_options:
                unsup_opts_str = ', '.join(map(lambda x: "'" + x + "'", unsupported_options))
                if len(unsupported_options) == 1:
                    msg = f"The BLAST+ option {unsup_opts_str} is not supported in ElasticBLAST. Please remove this command line option from your configuration and try again."
                else:
                    msg = f"The BLAST+ options {unsup_opts_str} are not supported in ElasticBLAST. Please remove these command line options from your configuration and try again."
                errors.append(msg) 
        except ValueError as err:
            errors.append(f'Incorrect BLAST options: {str(err)} in "{self.options}"')

        if self.db_mem_margin < 1.0:
            errors.append(f'Incorrect value for blast.db_mem_margin: "{self.db_mem_margin}", must be larger than 1')

@dataclass_json(letter_case=LetterCase.KEBAB)
@dataclass
class ClusterConfig(ConfigParserToDataclassMapper):
    """ElasticBLAST cluster config"""
    results: CloudURI
    name: str = ''
    machine_type: str = ''
    pd_size: str = ''
    num_cpus: PositiveInteger = PositiveInteger(ELB_NOT_INITIALIZED_NUM)
    # This field is required only when machine-type == optimal.
    mem_limit: MemoryStr = MemoryStr(ELB_NOT_INITIALIZED_MEM)
    mem_request: Optional[MemoryStr] = None
    num_nodes: PositiveInteger = PositiveInteger(ELB_DFLT_NUM_NODES)
    use_preemptible: bool = ELB_DFLT_USE_PREEMPTIBLE
    disk_type: str = ELB_DFLT_AWS_DISK_TYPE
    iops: Optional[int] = None
    bid_percentage: Percentage = Percentage(ELB_DFLT_AWS_SPOT_BID_PERCENTAGE)
    labels: str = ''
    db_source: DBSource = field(init=False)
    use_local_ssd: bool = False
    enable_stackdriver: bool = False
    dry_run: bool = False
    num_cores_per_instance: int = -1
    instance_memory: Optional[MemoryStr] = None

    mapping = {'results': ParamInfo(CFG_BLAST, CFG_BLAST_RESULTS),
               'name': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_NAME),
               'machine_type': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_MACHINE_TYPE),
               'pd_size': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_PD_SIZE),
               'num_cpus': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_NUM_CPUS),
               'mem_limit': ParamInfo(CFG_BLAST, CFG_BLAST_MEM_LIMIT),
               'mem_request': ParamInfo(CFG_BLAST, CFG_BLAST_MEM_REQUEST),
               'num_nodes': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_NUM_NODES),
               'use_preemptible': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_USE_PREEMPTIBLE),
               'disk_type': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_DISK_TYPE),
               'iops': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_PROVISIONED_IOPS),
               'bid_percentage': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_BID_PERCENTAGE),
               'labels': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_LABELS),
               'db_source': ParamInfo(CFG_BLAST, CFG_BLAST_DB_SRC),
               'use_local_ssd': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_EXP_USE_LOCAL_SSD),
               'enable_stackdriver': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_ENABLE_STACKDRIVER),
               'dry_run': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_DRY_RUN),
               'num_cores_per_instance': None,
               'instance_memory': None
   }
    

    def __post_init__(self):
        # needed for deserialization, because JSON decoder does not know about
        # types defined here, like CloudURL or MemoryStr
        self.re_initialize_values()
        try:
            cloud_provider = self.results.get_cloud_provider()
        except ValueError as err:
            raise UserReportError(returncode=INPUT_ERROR,
                                  message=f'Incorrect results URI: {err}')
        self.db_source = DBSource[cloud_provider.name]

        # default machine type and pd size
        if cloud_provider == CSP.GCP:
            if not self.pd_size:
                self.pd_size = ELB_DFLT_GCP_PD_SIZE
        else:
            if not self.pd_size:
                self.pd_size = ELB_DFLT_AWS_PD_SIZE

        # default number of CPUs
        if self.num_cpus == ELB_NOT_INITIALIZED_NUM:
            if cloud_provider == CSP.GCP:
                self.num_cpus = PositiveInteger(ELB_DFLT_GCP_NUM_CPUS)
            else:
                self.num_cpus = PositiveInteger(ELB_DFLT_AWS_NUM_CPUS)

        # default memory request for a blast search job
        if not self.mem_request:
            self.mem_request = MemoryStr('0.5G')

        # default cluster name
        if not self.name:
            self.name = generate_cluster_name(self.results)

        # Experimental: this is to facilitate performance testing
        if 'ELB_PERFORMANCE_TESTING' in os.environ:
            self.num_nodes = 1


    def validate(self, errors: List[str], task: ElbCommand):
        """Config validation"""
        if task != ElbCommand.SUBMIT:
            return

        if self.machine_type.lower() == 'optimal':
            logging.warning("Optimal AWS instance type is NOT FULLY TESTED - for internal development ONLY")

        if re.search(ELB_AWS_ARM_INSTANCE_TYPE_REGEX, self.machine_type):
            msg = f'You specified "{self.machine_type}" cluster.machine-type, which is not supported by ElasticBLAST. Please change the cluster.machine-type before trying again.'
            errors.append(msg)


@dataclass_json(letter_case=LetterCase.KEBAB)
@dataclass
class TimeoutsConfig(ConfigParserToDataclassMapper):
    """Timeouts config"""
    init_pv: PositiveInteger = PositiveInteger(ELB_DFLT_INIT_PV_TIMEOUT)
    blast_k8s: PositiveInteger = PositiveInteger(ELB_DFLT_BLAST_K8S_TIMEOUT)

    mapping = {'init_pv': ParamInfo(CFG_TIMEOUTS, CFG_TIMEOUT_INIT_PV),
               'blast_k8s': ParamInfo(CFG_TIMEOUTS, CFG_TIMEOUT_BLAST_K8S_JOB)}


@dataclass_json(letter_case=LetterCase.KEBAB)
@dataclass
class AppState:
    """Application state values"""

    # The GCP persistent disk ID
    disk_id: Optional[str] = None
    # The kubernetes context
    k8s_ctx: Optional[str] = None


@dataclass
class ElasticBlastConfig:
    """ElasticBLAST config class.

    Attributes:
        cloud_provider: cloud provider parameters
        asw or gcp: a reference to cloud_parameters for AWS or GCP config
        blast: BLAST parameters
        cluster: cluster parameters
        timeouts: timeouts parameters
    """
    cloud_provider: CloudProviderBaseConfig
    gcp: GCPConfig
    aws: AWSConfig
    blast: BlastConfig
    cluster: ClusterConfig
    timeouts: TimeoutsConfig
    appstate: AppState
    version: str = VERSION

    # FIXME: blast, cluster, and timeouts should be Optional types, but then
    # mypy will insist on checking whether they are None each time they are
    # accessed

    def __init__(self, *args, **kwargs):
        """Constructor. An object can be constructed either with one
        positional parameter: a ConfigParser object and one keyname parameter:
        task or all keyname parameters with required config parameter values
        (see below). The task keyname parameter is always required.

        Examples:
            cfg = configparser.ConfigParser
            ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)

            ElasticBlastConfig(aws_region = 'us-east-1',
                               results = 's3://some-bucket',
                               task = ElbCommand.STATUS)

            ElasticBlastConfig(aws_region = 'us-east-1'
                               program = 'blastn',
                               db = 'nt',
                               queries = 'queries.fa'
                               results = 's3://results',
                               task = ElbCommand.SUBMIT)

        Positional parameters:
            ConfigParser object

        Keyword parameters:
            task: ElasticBLAST task (required parameter)

            aws_region: AWS Region

            gcp_project: GCP project
            gcp_region: GCP project
            gcp_zone: GCP zone

            program: BLAST program
            db: BLAST database
            query: BLAST queries as a str
            results: BLAST results uri

            cluster_name: Cluster name

        Raises:
            ValueError and UserReportError: for incorrect user input
            AttributeError: method called with incorrect arguments
        """
        # AttributeError is raised below because the exceptions would be
        # caused by incorrect code rather than user input.

        # A single argument of value None creates an empty object: all attributes
        # are None. This is used for deserialization.
        if len(args) == 1 and args[0] is None and not kwargs:
            return

        dry_run = False
        if len(args) > 2 or \
               (len(args) > 0 and not isinstance(args[0], configparser.ConfigParser)):
            raise AttributeError('ElasticBlastConfig.__init__ method takes only up to two positional arguments: ConfigParser object and bool dry_run')

        if 'task' not in kwargs:
            raise AttributeError('The task parameter must be specified in ElasticBlastConfig.__init__')

        if len(args) > 0 and len(kwargs) > 1:
            raise AttributeError('ElasticBlastConfig.__init__ takes either up to two positional arguments: ConfigParser object and bool dry_run, and one keyname parameter: ElastiBLAST task or only keyname parameters')

        if not isinstance(kwargs['task'], ElbCommand):
            raise AttributeError('Incorrect type for function argument "task". It must be ElbCommand')

        task: ElbCommand = kwargs['task']

        if len(args) > 0 and isinstance(args[0], configparser.ConfigParser):
            try:
                self._init_from_ConfigParser(args[0], task)
            except ValueError as err:
                raise UserReportError(returncode=INPUT_ERROR,
                                      message=str(err))
            if len(args) > 1 and isinstance(args[1], bool):
                dry_run = args[1]
        else:
            self._init_from_parameters(**kwargs)
            dry_run = kwargs.get('dry_run', False)

        # post-init activities

        try:
            if self.cloud_provider.region:
                self.cloud_provider.region.validate(dry_run)
        except ValueError as err:
            raise UserReportError(returncode=INPUT_ERROR, message=str(err))

        # get database metadata
        if self.blast and not self.blast.db_metadata:
            try:
                self.blast.db_metadata = get_db_metadata(self.blast.db, ElbSupportedPrograms().get_db_mol_type(self.blast.program),
                                                         self.cluster.db_source)
            except FileNotFoundError:
                # database metadata file is not mandatory for a user database (yet) EB-1308
                logging.info('No database metadata')
                if not self.blast.db.startswith(ELB_S3_PREFIX) and not self.blast.db.startswith(ELB_GCS_PREFIX):
                    raise UserReportError(returncode=BLASTDB_ERROR,
                                          message=f'Metadata for BLAST database "{self.blast.db}" was not found. Please, make sure that the database exists and database molecular type corresponds to your blast program: "{self.blast.program}". To get a list of NCBI provided databases, please see https://github.com/ncbi/blast_plus_docs#blast-databases.')
                else:
                    logging.warning('Database metadata file was not provided. We recommend creating and providing a BLAST database metadata file. Benefits include better elastic-blast performance and error checking. Please, see https://blast.ncbi.nlm.nih.gov/doc/elastic-blast/tutorials/create-blastdb-metadata.html for more information and instructions.')

        # set mt_mode
        if self.blast:
            mt_mode = MTMode.ZERO
            if '-mt_mode' in self.blast.options:
                mode = re.findall(r'-mt_mode\s+(\d)', self.blast.options)
                if not mode or int(mode[0]) > 1:
                    raise UserReportError(returncode=INPUT_ERROR,
                                          message=f'Incorrect -mt_mode parameter value "{mode[0]}" in blast.options: "{self.blast.options}". -mt_mode must be either 0 or 1, please see https://www.ncbi.nlm.nih.gov/books/NBK571452/ for details.')
                mt_mode = MTMode(int(mode[0]))
                if self.blast.program in ['tblastx', 'psiblast'] and mt_mode == MTMode.ZERO:
                    raise UserReportError(returncode=INPUT_ERROR,
                                          message=f'{self.blast.program} does not support "-mt_mode" option')
            else:
                mt_mode = get_mt_mode(self.blast.program, self.blast.options,
                                      self.blast.db_metadata)
                if mt_mode == MTMode.ONE:
                    self.blast.options += f' {mt_mode}'

        # select machine type
        if not self.cluster.machine_type:
            if self.blast and self.blast.db_metadata:
                self.cluster.machine_type = get_machine_type(self.cloud_provider.cloud,
                                                             self.blast.db_metadata,
                                                             self.cluster.num_cpus,
                                                             mt_mode,
                                                             self.blast.db_mem_margin,
                                                             self.cloud_provider.region)
            else:
                if self.cloud_provider.cloud == CSP.AWS:
                    self.cluster.machine_type = ELB_DFLT_AWS_MACHINE_TYPE
                else:
                    self.cluster.machine_type = ELB_DFLT_GCP_MACHINE_TYPE

        # Sanity check for instance type and num CPUs
        if self.cluster.machine_type != 'optimal' and not self.cluster.dry_run:
            instance_props = get_instance_props(self.cloud_provider.cloud,
                                                self.cloud_provider.region,
                                                self.cluster.machine_type)
            self.cluster.num_cores_per_instance = instance_props.ncpus
            self.cluster.instance_memory = MemoryStr(f'{instance_props.memory}G')
            if self.cluster.num_cores_per_instance < self.cluster.num_cpus:
                self.cluster.num_cpus = PositiveInteger(self.cluster.num_cores_per_instance)
                if self.cloud_provider.cloud == CSP.GCP:
                    self.cluster.num_cpus = PositiveInteger(self.cluster.num_cores_per_instance - 1)
                logging.debug(f'Requested number of vCPUs lowered to {self.cluster.num_cpus} because of instance type choice {self.cluster.machine_type}')

        # default memory limit for a blast search job
        if self.cluster.mem_limit == ELB_NOT_INITIALIZED_MEM:
            if self.cluster.machine_type == 'optimal':
                msg = 'You specified "optimal" cluster.machine-type, which requires configuring blast.mem-limit. Please provide that configuration parameter or change cluster.machine-type.'
                raise UserReportError(returncode=INPUT_ERROR, message=msg)
            self.cluster.mem_limit = get_mem_limit(self.cloud_provider.cloud,
                                                   self.cluster.machine_type,
                                                   self.cluster.num_cpus,
                                                   cloud_region=self.cloud_provider.region)

        # set batch length
        if self.blast:
            if self.blast.batch_len == ELB_NOT_INITIALIZED_NUM:
                self.blast.batch_len = get_batch_length(self.cloud_provider.cloud,
                                                        self.blast.program,
                                                        mt_mode,
                                                        self.cluster.num_cpus,
                                                        self.blast.db_metadata)
            else:
                logging.debug(f'User provided batch length {self.blast.batch_len}')
                self.blast.user_provided_batch_len = True


        # set resources labels
        self.cluster.labels = create_labels(self.cloud_provider.cloud,
                                            self.cluster.results,
                                            self.blast,
                                            self.cluster.name,
                                            self.cluster.labels)
        self.validate(task, dry_run)


    def __getattr__(self, name):
        """Return None for uninitialized dataclass attributes.
        Raises AttrubuteError for other non-existant class attributes"""
        if name in [i.name for i in fields(self)]:
            return None
        else:
            raise AttributeError(f'"{type(self).__name__}" has no attribute "{name}"')


    def __setattr__(self, name, value):
        """Prevent creation of new attributes to catch misspelled class
        attribute values. Raises AttributeError if a value is being assigned to
        a new class attribute."""
        if not name in [i.name for i in fields(self)]:
            raise AttributeError(f'Attribute {name} does not exit in class {type(self)}')
        super().__setattr__(name, value)


    def _init_from_ConfigParser(self, cfg: configparser.ConfigParser,
                                task: ElbCommand):
        """Initialize an ElasticBlastConfig object from ConfigParser parameter
        values.

        Parameters:
            cfg: ConfigParser object"""

        self._validate_config_parser(cfg)
        _validate_csp(cfg)
        self.cluster = ClusterConfig.create_from_cfg(cfg)

        # determine cloud provider, first by user config, then results bucket
        if sum([i.startswith('aws') for i in cfg[CFG_CLOUD_PROVIDER]]) > 0:
            cloud = CSP.AWS
        elif sum([i.startswith('gcp') for i in cfg[CFG_CLOUD_PROVIDER]]) > 0:
            cloud = CSP.GCP
        else:
            cloud = self.cluster.results.get_cloud_provider()

        if cloud == CSP.AWS:
            self.cloud_provider = AWSConfig.create_from_cfg(cfg)
            # for mypy
            self.aws = cast(AWSConfig, self.cloud_provider)
        else:
            self.cloud_provider = GCPConfig.create_from_cfg(cfg)
            # for mypy
            self.gcp = cast(GCPConfig, self.cloud_provider)

        if task == ElbCommand.SUBMIT:
            self.blast = BlastConfig.create_from_cfg(cfg)

        self.timeouts = TimeoutsConfig.create_from_cfg(cfg)
        self.appstate = AppState()


    def _init_from_parameters(self,
                              task: ElbCommand,
                              results: str,
                              aws_region: Optional[str] = None,
                              gcp_project: Optional[str] = None,
                              gcp_region: Optional[str] = None,
                              gcp_zone: Optional[str] = None,
                              program: Optional[str] = None,
                              db: Optional[str] = None,
                              queries: Optional[str] = None,
                              dry_run: Optional[bool] = None,
                              cluster_name: Optional[str] = None,
                              machine_type: str = ''):
        """Initialize config object from required parameters"""
        if aws_region and (gcp_project or gcp_region or gcp_zone):
            raise ValueError('Cloud provider config contains entries for more than one cloud provider. Only one cloud provider can be used')

        if aws_region:
            self.cloud_provider = AWSConfig(region = AWSRegion(aws_region))
            self.aws = cast(AWSConfig, self.cloud_provider)
        elif gcp_project or gcp_region or gcp_zone:
            if not gcp_project:
                raise ValueError('gcp-project is missing')
            if not gcp_region:
                raise ValueError('gcp-region is missing')
            if not gcp_zone:
                raise ValueError('gcp-zone is missing')
            self.cloud_provider = GCPConfig(project = GCPString(gcp_project),
                                            region = GCPString(gcp_region),
                                            zone = GCPString(gcp_zone))
            self.gcp = cast(GCPConfig, self.cloud_provider)

        self.cluster = ClusterConfig(results = CloudURI(results),
                                     machine_type = machine_type)
        if cluster_name:
            self.cluster.name = cluster_name

        if task == ElbCommand.SUBMIT:
            if not program:
                raise ValueError('BLAST program is missing')
            if not db:
                raise ValueError('BLAST db is missing')
            if not queries:
                raise ValueError('BLAST queries are missing')
            self.blast = BlastConfig(program = BLASTProgram(program),
                                     db = db,
                                     queries_arg = queries)

            self.timeouts = TimeoutsConfig()
            self.appstate = AppState()


    def _validate_config_parser(self, parser: configparser.ConfigParser) -> None:
        """Ensure that each config parser key is mapped to an attribute.

            Arguments:
                parser: ConfigParser object

            Raises:
                UserReportError if parser[section][parameter] is not mapped
                to an ElasticBlastParameter"""
        params = defaultdict(list)
        # for each annotated class attribute, which inherits from
        # ConfigParserToDataclassMapper get attribute to configparser
        # parameter mapping
        for attribute in type(self).__annotations__:
            if issubclass(type(self).__annotations__[attribute], ConfigParserToDataclassMapper):
                mapping = type(self).__annotations__[attribute].mapping.values()
                for p in mapping:
                    if p is not None:
                        params[p.section].append(p.param_name)

        # find configparser parameters not present in the mapping
        for section in parser:
            for param_name in parser[section]:
                if param_name not in params[section]:
                    raise UserReportError(returncode=INPUT_ERROR,
                                          message=f'Unrecognized configuration parameter "{param_name}" in section "{section}". Please, ensure that parameter names are properly spelled and placed in appropriate sections.')


    def validate(self, task: ElbCommand = ElbCommand.SUBMIT, dry_run=False):
        """Validate config"""
        errors: List[str] = []

        if self.cloud_provider.cloud == CSP.GCP:
            self.gcp.validate(errors, task)
            try:
                validate_gke_cluster_name(self.cluster.name)
            except ValueError as err:
                errors.append(str(err))
        else:
            self.aws.validate(errors, task)

        if task == ElbCommand.SUBMIT:
            self.blast.validate(errors, task)

        self.cluster.validate(errors, task)

        if self.cloud_provider.cloud == CSP.GCP and \
               not self.cluster.results.startswith(ELB_GCS_PREFIX):
            errors.append(f'Results bucket must start with "{ELB_GCS_PREFIX}"')
        elif self.cloud_provider.cloud == CSP.AWS and \
             not self.cluster.results.startswith(ELB_S3_PREFIX):
            errors.append(f'Results bucket must start with "{ELB_S3_PREFIX}"')

        if task == ElbCommand.SUBMIT:
            # validate number of CPUs and memory limit for searching a batch
            # of queries
            if not dry_run and self.cluster.machine_type.lower() != 'optimal':
                instance_props = get_instance_props(self.cloud_provider.cloud,
                                                    self.cloud_provider.region,
                                                    self.cluster.machine_type)
                self._validate_num_cpus(instance_props, errors)

                if instance_props.memory - SYSTEM_MEMORY_RESERVE < self.cluster.mem_limit.asGB():
                    errors.append(f'Memory limit "{self.cluster.mem_limit}" exceeds memory available on the selected machine type {self.cluster.machine_type}: {instance_props.memory - SYSTEM_MEMORY_RESERVE}GB. Please, select machine type with more memory or lower memory limit')

                if self.blast.db_metadata:
                    bytes_to_cache_gb = round(self.blast.db_metadata.bytes_to_cache / (1024 ** 3), 1)
                    if instance_props.memory - SYSTEM_MEMORY_RESERVE < bytes_to_cache_gb:
                        errors.append(f'BLAST database {self.blast.db} memory requirements exceed memory available on selected machine type "{self.cluster.machine_type}". Please select machine type with at least {bytes_to_cache_gb + SYSTEM_MEMORY_RESERVE}GB available memory.')

            # validate janitor schedule if provided
            if ELB_JANITOR_SCHEDULE in os.environ:
                try:
                    validate_janitor_schedule(os.environ[ELB_JANITOR_SCHEDULE], self.cloud_provider.cloud)
                except ValueError as err:
                    errors.append(str(err))

        if errors:
            raise UserReportError(returncode=INPUT_ERROR,
                                  message='\n'.join(errors))

    def _validate_num_cpus(self, instance_props: InstanceProperties, errors: List[str]):
        """ Validate that the num_cpus configured will work well with ElasticBLAST """
        if instance_props.ncpus < self.cluster.num_cpus:
            errors.append(f'Requested number of CPUs for a single search job ({self.cluster.num_cpus}) exceeds the number of CPUs ({instance_props.ncpus}) on the selected instance type ({self.cluster.machine_type}). Please, reduce the number of CPUs or select an instance type with more available CPUs.')

        if self.cloud_provider.cloud == CSP.GCP:
            if instance_props.ncpus % self.cluster.num_cpus == 0:
                #msg = f'Requested number of CPUs for a single search job ({self.cluster.num_cpus}) does not optimally use the CPUs available to instance type {self.cluster.machine_type}.'
                if instance_props.ncpus == self.cluster.num_cpus:
                    msg = f'Requested number of CPUs for a single search job ({self.cluster.num_cpus}) does not leave any CPUs for GKE cluster operation for instance type {self.cluster.machine_type}.'

                    if instance_props.ncpus > ELB_DFLT_GCP_NUM_CPUS:
                        msg += f' Please set cluster.num_cpus to {ELB_DFLT_GCP_NUM_CPUS}.'
                    else:
                        msg += f' Please set cluster.num_cpus to {instance_props.ncpus-1}.'
                    errors.append(msg)


    @staticmethod
    def _clean_dict(indict: Dict[str, Any]):
        """Remove unimportant config parameters (mapping and equal to None) from
        the object converted to a dictionary."""
        remove: List[Any] = []
        if 'mapping' in indict:
            remove.append('mapping')
        for key in indict:
            if indict[key] is None:
                remove.append(key)
        for key in remove:
            del indict[key]

        remove = []
        for key_1 in indict:
            if not isinstance(indict[key_1], dict):
                continue
            if 'mapping' in indict[key_1]:
                remove.append((key_1, 'mapping'))
            for key_2 in indict[key_1]:
                if indict[key_1][key_2] is None:
                    remove.append((key_1, key_2))
        for key_1, key_2 in remove:
            del indict[key_1][key_2]


    def asdict(self) -> Dict[str, Any]:
        """Convert ElasticBlastConfig object to a dictionary, removing mapping
        attributes, parameters set to None and cloud_provider, because it is
        the same as aws or gcp"""
        retval = asdict(self)

        # cloud_provider is the same as aws or gcp
        if self.cloud_provider is self.aws or self.cloud_provider is self.gcp:
            del retval['cloud_provider']

        self._clean_dict(retval)
        return retval


    def to_json(self) -> str:
        """Serialize to JSON"""
        config_as_dict = {'blast': self.blast.to_dict(),
                          'cluster': self.cluster.to_dict(),
                          'timeouts': self.timeouts.to_dict(),
                          'appstate': self.appstate.to_dict(), # type: ignore
                          'version': self.version
        }
        if self.cloud_provider.cloud == CSP.AWS:
            config_as_dict['aws'] = self.aws.to_dict()
        else:
            config_as_dict['gcp'] = self.gcp.to_dict()

        self._clean_dict(config_as_dict)
        return json.dumps(config_as_dict, indent=4, cls=JSONEnumEncoder)


    @classmethod
    def from_json(cls, json_str: str):
        """Deserialize from a JSON string"""
        cfg = ElasticBlastConfig(None)
        cfg_dict = json.loads(json_str)
        if 'aws' in cfg_dict:
            cfg.aws = AWSConfig.from_dict(cfg_dict['aws'])  # type: ignore
            cfg.cloud_provider = cfg.aws
        elif 'gcp' in cfg_dict:
            cfg.gcp = GCPConfig.from_dict(cfg_dict['gcp']) # type: ignore
            cfg.cloud_provider = cfg.gcp
        cfg.blast = BlastConfig.from_dict(cfg_dict['blast']) # type: ignore
        cfg.cluster = ClusterConfig.from_dict(cfg_dict['cluster']) # type: ignore
        cfg.timeouts = TimeoutsConfig.from_dict(cfg_dict['timeouts']) # type: ignore
        cfg.appstate = AppState.from_dict(cfg_dict['appstate']) # type: ignore

        # blast.user_provided_batch_len is a boolean with a default value that
        # depends on whether blast.batch_len has the default value, which cannot
        # be checked after BlastConfig object is initialized and must be set
        # here by hand to ensure the correct value
        # FIXME: Changing blast.user_provided_batch_len to blast.default.batch_len
        # may help setting this value correctly in BlastConfig.__post_init__
        cfg.blast.user_provided_batch_len = cfg_dict['blast']['user-provided-batch-len']

        return cfg


    def get_max_number_of_concurrent_blast_jobs(self) -> int:
        """ Computes the maximum number of concurrent BLAST jobs that can run given the
        provided configuration.
        Pre-condition: the object has been initialized
        """
        assert self.cluster.mem_request is not None
        retval = ELB_UNKNOWN_MAX_NUMBER_OF_CONCURRENT_JOBS
        if self.cluster.dry_run:
            return retval

        if self.cluster.num_cores_per_instance == -1 or not self.cluster.instance_memory:
            logging.debug(f'Cannot compute number of concurrent BLAST jobs for instance type {self.cluster.machine_type}')
            return retval
        if self.blast.user_provided_batch_len:
            logging.debug(f'User provided batch length, will not re-compute it')
            return retval

        cpu_num_concurrent_jobs = int(self.cluster.num_cores_per_instance/self.cluster.num_cpus)*self.cluster.num_nodes
        mem_num_concurrent_jobs = ELB_NOT_INITIALIZED_NUM
        # Catch the event that ELB_NOT_INITIALIZED_NUM is changed to a constant with a small value
        assert mem_num_concurrent_jobs >= 2**32
        if self.cloud_provider.cloud == CSP.AWS:
            mem_num_concurrent_jobs = int(self.cluster.instance_memory.asGB() / self.cluster.mem_limit.asGB()) * self.cluster.num_nodes
        elif self.cluster.mem_request: # to pacify mypy
            mem_num_concurrent_jobs = int(self.cluster.instance_memory.asGB() / self.cluster.mem_request.asGB()) * self.cluster.num_nodes
        return min((cpu_num_concurrent_jobs, mem_num_concurrent_jobs))


def generate_cluster_name(results: CloudURI) -> str:
    """ Returns the default cluster name """
    username = sanitize_for_k8s(sanitize_gcp_label(getpass.getuser().lower()))
    return f'elasticblast-{username}-{results.md5}'


def create_labels(cloud_provider: CSP,
                  results: str,
                  blast_conf: Optional[BlastConfig],
                  cluster_name: str,
                  user_provided_labels: str = None) -> str:
    """Generate labels for cloud resources"""
    if cloud_provider == CSP.AWS:
        sanitize = sanitize_aws_tag
    else:
        sanitize = sanitize_gcp_label
    username = sanitize(getpass.getuser())
    elastic_blast_version = sanitize(VERSION)
    if re.search(r'[A-Z]', cluster_name):
        raise UserReportError(INPUT_ERROR, f'cluster name {cluster_name} must have all lower case characters')

    cluster_name = sanitize(cluster_name)
    blast_program = sanitize(blast_conf.program) if blast_conf else '-'
    db = sanitize(blast_conf.db) if blast_conf else '-'
    create_date = sanitize(datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d-%H-%M-%S'))
    hostname = sanitize(socket.gethostname())

    results = sanitize(results)

    custom_labels = {}
    if user_provided_labels:
        kv_pairs = user_provided_labels.split(',')
        for kv in kv_pairs:
            tokens = kv.split('=')
            if len(tokens) != 2:
                msg = f'labels configuration "{kv_pairs}" is incorrect, please refer to the documentation for help'
                raise UserReportError(INPUT_ERROR, msg)
            key = tokens[0]
            value = tokens[1]
            if cloud_provider == CSP.GCP:
                # https://cloud.google.com/kubernetes-engine/docs/how-to/creating-managing-labels
                if re.search(r'[A-Z]', key) or len(key) > GCP_MAX_LABEL_LENGTH:
                    raise UserReportError(INPUT_ERROR, f'Key "{key}" must have all lower case characters and have less than {GCP_MAX_LABEL_LENGTH+1} characters')
                if re.search(r'[A-Z]', value) or len(value) > GCP_MAX_LABEL_LENGTH:
                    raise UserReportError(INPUT_ERROR, f'Value "{value}" must have all lower case characters and have less than {GCP_MAX_LABEL_LENGTH+1} characters')
            elif cloud_provider == CSP.AWS:
                if len(key) > AWS_MAX_TAG_LENGTH:
                    raise UserReportError(INPUT_ERROR, f'Key "{key}" must have less than {AWS_MAX_TAG_LENGTH+1} characters')
            custom_labels[key] = value

    default_labels = {
        'cluster-name' : cluster_name,
        'client-hostname': hostname,
        'project': 'elastic-blast',
        'billingcode': 'elastic-blast',
        'creator': username,
        'created': create_date,
        'owner': username,
        'program': blast_program,
        'db': db,
        'name': cluster_name,
        'results': results,
        'version': elastic_blast_version
    }
    # Change some keys to follow NCBI guidelines and AWS conventions
    if cloud_provider == CSP.AWS:
        default_labels['Project'] = default_labels.pop('project')
        default_labels['Owner'] = default_labels.pop('owner')
        default_labels['Name'] = default_labels.pop('name')

    labels = ''
    for label in default_labels.keys():
        if label in custom_labels.keys():
            custom_value = custom_labels.pop(label)
            labels += f'{label}={custom_value},'
        else:
            labels += f'{label}={default_labels[label]},'

    for label in custom_labels.keys():
        labels += f'{label}={custom_labels[label]},'
    labels = labels.rstrip(',') # Remove the trailing comma

    # Validate the number of labels used
    num_labels = labels.count('=')
    if cloud_provider == CSP.GCP:
        if num_labels > GCP_MAX_NUM_LABELS:
            raise UserReportError(INPUT_ERROR, f'Too many labels are being used ({num_labels}); GCP only supports up to {GCP_MAX_NUM_LABELS}')
    else:
        if num_labels > AWS_MAX_NUM_LABELS:
            raise UserReportError(INPUT_ERROR, f'Too many labels are being used ({num_labels}); AWS only supports up to {AWS_MAX_NUM_LABELS}')


    return labels



def sanitize_gcp_label(input_label: str) -> str:
    """ Changes the input_label so that it is composed of valid GCP label characters"""
    return re.sub(r'\W', '-', input_label.lower(), flags=re.ASCII)[:GCP_MAX_LABEL_LENGTH]


def sanitize_aws_tag(input_label: str) -> str:
    """ Changes the input_label so that it is composed of valid AWS tag characters"""
    # NB: this AWS sanitizer is a bit more restrictive - it replaces '=' to
    # simplify dataflow for GCP
    return re.sub(r'[^\w_\.:/+@]', '-', input_label, flags=re.ASCII)[:AWS_MAX_TAG_LENGTH]


def get_instance_props(cloud_provider: CSP, region: str, machine_type: str) -> InstanceProperties:
    """Get properties of a cloud instance."""
    try:
        if cloud_provider == CSP.GCP:
            instance_props = gcp_get_machine_properties(machine_type)
        else:
            instance_props = aws_get_machine_properties(machine_type, create_aws_config(region))
    except NotImplementedError as err:
        raise UserReportError(returncode=INPUT_ERROR,
                              message=f'Invalid machine type. Machine type name "{machine_type}" is incorrect or not supported by ElasticBLAST: {str(err)}')
    return instance_props


def validate_janitor_schedule(val: str, cloud_provider: CSP) -> None:
    """Validate cron schedule for janitor job. Raises ValueError if validation fails."""
    special = r'@(yearly|annually|monthly|weekly|daily|midnight|hourly)'
    minute = r'\*|(\*|([1-5]?[0-9]))((,(\*|([1-5]?[0-9])))*([/-][1-5]?[0-9])?)*'
    hour = r'\*|(\*|([1-2]?[0-9]))((,(\*|([1-2]?[0-9])))*([/-][1-2]?[0-9])?)*'
    day_of_month_gcp = r'\*|(\*|([1-3]?[0-9]))((,(\*|([1-3]?[0-9])))*([/-][1-3]?[0-9])?)*'
    day_of_month_aws = r'\*|\?|(\*|([1-3]?[0-9]L?W?))((,(\*|([1-3]?[0-9]L?W?)))*([/-][1-3]?[0-9])?)*'
    month = r'\*|(\*|(1?[0-9]))((,(\*|(1?[0-9])))*([/-]1?[0-9])?)*'
    day_of_week_gcp = r'\*|((\*|[0-7]|mon|tue|wed|thu|fri|sat|sun)((,(\*|[0-7]|mon|tue|wed|thu|fri|sat|sun))*([/-]([1-6]|mon|tue|wed|thu|fri|sat|sun))?)*)'
    day_of_week_aws = r'\*|\?|(((\*|[1-7]|MON|TUE|WED|THU|FRI|SAT|SUN)L?)(([,#](([1-7]|MON|TUE|WED|THU|FRI|SAT|SUN)L?))*([/-]([1-6]|MON|TUE|WED|THU|FRI|SAT|SUN))?)*)'
    year = r'\*|(\*|(2[01][0-9]{2}))((,(\*|(2[01][0-9]{2})))*(-2[01][0-9]{2})?(/\d{1,3})?)*'


    if cloud_provider == CSP.GCP:
        pattern = special + '|' + '((' + minute + r')\s(' + hour + r')\s(' + day_of_month_gcp + r')\s(' + month + r')\s(' + day_of_week_gcp + '))'
        url = 'https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/#cron-schedule-syntax'
    else:
        pattern = r'cron\((' + minute + r')\s(' + hour + r')\s(' + day_of_month_aws + r')\s(' + month + r')\s(' + day_of_week_aws + r')\s(' + year + r')\)'
        url = 'https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-create-rule-schedule.html'

    r = re.fullmatch(pattern, val)
    if r is None:
        raise ValueError(f'Invalid value of environment variable {ELB_JANITOR_SCHEDULE} "{val}". The string must match the regular expression "{pattern}". For more information, please see {url}')


class JSONEnumEncoder(json.JSONEncoder):
    """JSON encoder that handles basic types and Enum"""
    def default(self, o):
        """Handle encoding"""
        if issubclass(type(o), Enum):
            return o.name
        else:
            return json.JSONEncoder(self, o)


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


