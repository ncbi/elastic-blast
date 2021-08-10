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
import getpass
from hashlib import md5
import configparser
import re
import time
import socket
import logging
import shlex
from collections import defaultdict
from typing import Optional, List
from typing import cast
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
from .constants import SYSTEM_MEMORY_RESERVE
from .constants import ELB_DFLT_AWS_NUM_CPUS, ELB_DFLT_GCP_NUM_CPUS
from .constants import ELB_S3_PREFIX, ELB_GCS_PREFIX
from .util import validate_gcp_string, validate_aws_region
from .util import validate_gke_cluster_name, ElbSupportedPrograms
from .util import get_query_batch_size
from .util import UserReportError
from .gcp_traits import get_machine_properties as gcp_get_machine_properties
from .aws_traits import get_machine_properties as aws_get_machine_properties
from .aws_traits import create_aws_config
from .base import InstanceProperties, PositiveInteger, Percentage
from .base import ParamInfo, ConfigParserToDataclassMapper, DBSource, MemoryStr
from .config import validate_cloud_storage_object_uri, _validate_csp


# Config parameter types

class CloudURI(str):
    """A subclass of str that only acceppts valid cloud bucket URIs and
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


class GCPString(str):
    """A subclass of str that only accepts valid GCP names. The value
    is validated before object creation"""
    def __new__(cls, value):
        """Constructor, validates that argumant is a valid GCP name"""
        validate_gcp_string(str(value))
        return super(cls, cls).__new__(cls, value)


class AWSRegion(str):
    """A subclass of str that only accepts valid AWS strings. The value
    is validated before object creation"""
    def __new__(cls, value):
        """Constructor, validates that argumant is a valid GCP name"""
        validate_aws_region(str(value))
        return super(cls, cls).__new__(cls, value)


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
# each config paraeter, defined as a dataclass atribute is mapped to an
# parameter in the ConfigParser object.

@dataclass
class CloudProviderBaseConfig:
    """Base class for cloud provider config. It contains values common for
    all cloud providers. All Cloud provider coonfig classes should inherit
    from it."""
    # name of a cloud provider, must be initialized by a child class
    cloud: CSP = field(init=False)


@dataclass
class GCPConfig(CloudProviderBaseConfig, ConfigParserToDataclassMapper):
    """GCP config for ElasticBLAST"""
    project: GCPString
    region: GCPString
    zone: GCPString
    network: Optional[str] = None
    subnet: Optional[str] = None

    # mapping to class attributes to ConfigParser parameters so that objects
    # can be initialized from ConfigParser objects
    mapping = {'project': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_GCP_PROJECT),
               'region': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_GCP_REGION),
               'zone': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_GCP_ZONE),
               'cloud': None,
               'network': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_GCP_NETWORK),
               'subnet': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_GCP_SUBNETWORK)}
 
    def __post_init__(self):
        self.cloud = CSP.GCP

    def validate(self, errors: List[str], task: ElbCommand):
        """Validate config"""
        if bool(self.network) != bool(self.subnet):
            errors.append('Both gcp-network and gcp-subnetwork need to be specified if one of them is specified')

    

@dataclass
class AWSConfig(CloudProviderBaseConfig, ConfigParserToDataclassMapper):
    """AWS config for ElasticBLAST"""
    region: AWSRegion
    vpc: Optional[str] = None
    subnet: Optional[str] = None
    security_group: Optional[str] = None
    key_pair: Optional[str] = None
    job_role: Optional[str] = None
    instance_role: Optional[str] = None
    batch_service_role: Optional[str] = None
    spot_fleet_role: Optional[str] = None

    mapping = {'region': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_AWS_REGION),
               'vpc': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_AWS_VPC),
               'subnet': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_AWS_SUBNET),
               'security_group': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_AWS_SECURITY_GROUP),
               'key_pair': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_AWS_KEY_PAIR),
               'job_role': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_AWS_JOB_ROLE),
               'instance_role': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_AWS_INSTANCE_ROLE),
               'batch_service_role': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_AWS_BATCH_SERVICE_ROLE),
               'spot_fleet_role': ParamInfo(CFG_CLOUD_PROVIDER, CFG_CP_AWS_SPOT_FLEET_ROLE),
               'cloud': None}


    def __post_init__(self):
        self.cloud = CSP.AWS

    def validate(self, errors: List[str], task: ElbCommand):
        """Validate config"""
        # nothing to do
        pass

@dataclass
class BlastConfig(ConfigParserToDataclassMapper):
    """ElasticBLAST BLAST parameters"""
    # these are additonal parameters to class constructor, not part of config
    # spec
    cloud_provider: InitVar[CloudProviderBaseConfig]
    machine_type: InitVar[str]

    # these are config parameters
    program: BLASTProgram  # maybe enum?
    db: str
    queries_arg: str
    # This field is required only when machine-type == optimal.
    mem_limit: MemoryStr = MemoryStr(ELB_NOT_INITIALIZED_MEM)
    db_source: DBSource = field(init=False)
    batch_len: PositiveInteger = field(init=False)
    queries: List[str] = field(default_factory=list, init=False)
    options: str = f'-outfmt {ELB_DFLT_OUTFMT}'
    # FIXME: Consider moving mem_request and mem_limit to ClusterConfig
    mem_request: Optional[MemoryStr] = field(init=False)
    taxidlist: Optional[str] = field(init=False, default=None)
    db_mem_margin: float = ELB_BLASTDB_MEMORY_MARGIN

    mapping = {'program': ParamInfo(CFG_BLAST, CFG_BLAST_PROGRAM),
               'db': ParamInfo(CFG_BLAST, CFG_BLAST_DB),
               'db_source': ParamInfo(CFG_BLAST, CFG_BLAST_DB_SRC),
               'queries_arg': ParamInfo(CFG_BLAST, CFG_BLAST_QUERY),
               'queries': None,
               'batch_len': ParamInfo(CFG_BLAST, CFG_BLAST_BATCH_LEN),
               'options': ParamInfo(CFG_BLAST, CFG_BLAST_OPTIONS),
               'mem_limit': ParamInfo(CFG_BLAST, CFG_BLAST_MEM_LIMIT),
               'mem_request': ParamInfo(CFG_BLAST, CFG_BLAST_MEM_REQUEST),
               # taxid list is parsed from BLAST options
               'taxidlist': None,
               'db_mem_margin': ParamInfo(CFG_BLAST, CFG_BLAST_DB_MEM_MARGIN)}
               

    def __post_init__(self, cloud_provider, machine_type):
        self.db_source = DBSource[cloud_provider.cloud.name]

        if self.batch_len is None:
            self.batch_len = PositiveInteger(get_query_batch_size(self.program))
        if not self.mem_request:
            self.mem_request = MemoryStr('0.5G')

        if self.mem_limit == ELB_NOT_INITIALIZED_MEM:
            if machine_type == 'optimal':
                msg = 'You specified "optimal" cluster.machine-type, which requires configuring blast.mem-limit. Please provide that configuration parameter or change cluster.machine-type.'
                raise UserReportError(returncode=INPUT_ERROR, message=msg)
            self.mem_limit = compute_default_memory_limit(cloud_provider,
                                                          machine_type)

        if self.options.find('-outfmt') < 0:
            self.options += f' -outfmt {ELB_DFLT_OUTFMT}'



    def validate(self, errors: List[str], task: ElbCommand):
        """Validate config"""
        if task != ElbCommand.SUBMIT:
            return

        for query_file in self.queries_arg.split():
            if query_file.startswith(ELB_S3_PREFIX) or query_file.startswith(ELB_GCS_PREFIX):
                try:
                    validate_cloud_storage_object_uri(query_file)
                except ValueError as err:
                    errors.append(f'Incorrect queries URI "{query_file}": {str(err)}')
        try:
            shlex.split(self.options)
        except ValueError as err:
            errors.append(f'Incorrect BLAST options: {str(err)}')



@dataclass
class ClusterConfig(ConfigParserToDataclassMapper):
    """ElasticBLAST cluster config"""
    # these are additinal parameters for class constructor, not config
    # parameters
    cloud_provider: InitVar[CloudProviderBaseConfig]

    # these are config parameters
    results: CloudURI
    name: str = field(init=False)
    machine_type: str = ''
    pd_size: str = field(init=False)
    num_cpus: PositiveInteger = PositiveInteger(ELB_NOT_INITIALIZED_NUM)
    num_nodes: PositiveInteger = PositiveInteger(ELB_DFLT_NUM_NODES)
    use_preemptible: bool = ELB_DFLT_USE_PREEMPTIBLE
    disk_type: str = ELB_DFLT_AWS_DISK_TYPE
    iops: Optional[int] = None
    bid_percentage: Percentage = Percentage(ELB_DFLT_AWS_SPOT_BID_PERCENTAGE)
    labels: str = ''
    use_local_ssd: bool = False
    enable_stackdriver: bool = False
    dry_run: bool = False

    mapping = {'results': ParamInfo(CFG_BLAST, CFG_BLAST_RESULTS),
               'name': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_NAME),
               'machine_type': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_MACHINE_TYPE),
               'pd_size': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_PD_SIZE),
               'num_cpus': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_NUM_CPUS),
               'num_nodes': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_NUM_NODES),
               'use_preemptible': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_USE_PREEMPTIBLE),
               'disk_type': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_DISK_TYPE),
               'iops': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_PROVISIONED_IOPS),
               'bid_percentage': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_BID_PERCENTAGE),
               'labels': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_LABELS),
               'use_local_ssd': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_EXP_USE_LOCAL_SSD),
               'enable_stackdriver': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_ENABLE_STACKDRIVER),
               'dry_run': ParamInfo(CFG_CLUSTER, CFG_CLUSTER_DRY_RUN)}
    

    def __post_init__(self, cloud_provider):
        # default machine type and pd size
        if cloud_provider.cloud == CSP.GCP:
            if not self.machine_type:
                self.machine_type = ELB_DFLT_GCP_MACHINE_TYPE
            if not self.pd_size:
                self.pd_size = ELB_DFLT_GCP_PD_SIZE
        else:
            if not self.machine_type:
                self.machine_type = ELB_DFLT_AWS_MACHINE_TYPE
            if not self.pd_size:
                self.pd_size = ELB_DFLT_AWS_PD_SIZE

        # default number of CPUs
        if self.num_cpus == ELB_NOT_INITIALIZED_NUM:
            if cloud_provider.cloud == CSP.GCP:
                self.num_cpus = PositiveInteger(ELB_DFLT_GCP_NUM_CPUS)
            else:
                self.num_cpus = PositiveInteger(ELB_DFLT_AWS_NUM_CPUS)

        # Sanity check for the instance type and num CPUs
        if self.machine_type != 'optimal':
            instance_props = get_instance_props(cloud_provider, self.machine_type)
            if instance_props.ncpus < self.num_cpus:
                self.num_cpus = PositiveInteger(instance_props.ncpus)
                if cloud_provider.cloud == CSP.GCP:
                    self.num_cpus = PositiveInteger(instance_props.ncpus - 1)
                logging.debug(f'Requested number of vCPUs lowered to {self.num_cpus} because of instance type choice {self.machine_type}')
            
        # default cluster name
        username = getpass.getuser().lower()
        self.name = f'elasticblast-{username}-{self.results.md5}'

        # Experimental: this is to facilitate performance testing
        if 'ELB_PERFORMANCE_TESTING' in os.environ:
            self.num_nodes = 1


    def validate(self, errors: List[str], task: ElbCommand):
        """Config validation"""
        if task != ElbCommand.SUBMIT:
            return

        if self.use_local_ssd:
            raise NotImplementedError('Usage of local SSD is EXPERIMENTAL and is not supported with autoscaling')

        if self.machine_type.lower() == 'optimal':
            logging.warn("Optimal AWS instance type is NOT FULLY TESTED - for internal development ONLY")


@dataclass
class TimeoutsConfig(ConfigParserToDataclassMapper):
    """Timeouts config"""
    init_pv: PositiveInteger = PositiveInteger(ELB_DFLT_INIT_PV_TIMEOUT)
    blast_k8s: PositiveInteger = PositiveInteger(ELB_DFLT_BLAST_K8S_TIMEOUT)

    mapping = {'init_pv': ParamInfo(CFG_TIMEOUTS, CFG_TIMEOUT_INIT_PV),
               'blast_k8s': ParamInfo(CFG_TIMEOUTS, CFG_TIMEOUT_BLAST_K8S_JOB)}


@dataclass
class AppState:
    """Application state values"""
    disk_id: Optional[str] = None


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
        # ArrtibuteError is raises below because the exceptions would be
        # caused by incorrect code rather than user input.
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
        if sum([i.startswith('aws') for i in cfg[CFG_CLOUD_PROVIDER]]) > 0:
            self.cloud_provider = AWSConfig.create_from_cfg(cfg)
            # for mypy
            self.aws = cast(AWSConfig, self.cloud_provider)
        else:
            self.cloud_provider = GCPConfig.create_from_cfg(cfg)
            # for mypy
            self.gcp = cast(GCPConfig, self.cloud_provider)
            

        self.cluster = ClusterConfig.create_from_cfg(cfg,
                                     cloud_provider = self.cloud_provider)

        if task == ElbCommand.SUBMIT:
            self.blast = BlastConfig.create_from_cfg(cfg,
                                       cloud_provider = self.cloud_provider,
                                       machine_type = self.cluster.machine_type)


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
                              cluster_name: Optional[str] = None):
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
                                     cloud_provider = self.cloud_provider)
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
                                     queries_arg = queries,
                                     cloud_provider = self.cloud_provider,
                                     machine_type = self.cluster.machine_type)

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
                instance_props = get_instance_props(self.cloud_provider,
                                                    self.cluster.machine_type)
                if instance_props.ncpus < self.cluster.num_cpus:
                    errors.append(f'Requested number of CPUs for a single search job "{self.cluster.num_cpus}" exceeds the number of CPUs ({instance_props.ncpus}) on the selected instance type "{self.cluster.machine_type}". Please, reduce the number of CPUs or select an instance type with more available CPUs.')

                if instance_props.memory - SYSTEM_MEMORY_RESERVE < self.blast.mem_limit.asGB():
                    errors.append(f'Memory limit "{self.blast.mem_limit}" exceeds memory available on the selected machine type {self.cluster.machine_type}: {instance_props.memory - SYSTEM_MEMORY_RESERVE}GB. Please, select machine type with more memory or lower memory limit')

        if errors:
            raise UserReportError(returncode=INPUT_ERROR,
                                  message='\n'.join(errors))


    def asdict(self):
        """Convert ElasticBlastConfig object to a dictionary, removing mapping
        attributes, parameters set to None and cloud_provider, because it is
        the same as aws or gcp"""
        retval = asdict(self)

        # cloud_provider is the same as aws or gcp
        if self.cloud_provider is self.aws or self.cloud_provider is self.gcp:
            del retval['cloud_provider']

        remove = []
        if 'mapping' in retval:
            remove.append('mapping')
        for key in retval:
            if retval[key] is None:
                remove.append(key)
        for key in remove:
            del retval[key]

        remove = []
        for key_1 in retval:
            if not isinstance(retval[key_1], dict):
                continue
            if 'mapping' in retval[key_1]:
                remove.append((key_1, 'mapping'))
            for key_2 in retval[key_1]:
                if retval[key_1][key_2] is None:
                    remove.append((key_1, key_2))
        for key_1, key_2 in remove:
            del retval[key_1][key_2]
        return retval



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
    if re.search(r'[A-Z]', cluster_name):
        raise UserReportError(INPUT_ERROR, f'cluster name {cluster_name} must have all lower case characters')

    cluster_name = sanitize(cluster_name)
    blast_program = sanitize(blast_conf.program) if blast_conf else '-'
    db = sanitize(blast_conf.db) if blast_conf else '-'
    create_date = sanitize(time.strftime('%Y-%m-%d-%H-%M-%S', time.gmtime()))
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
        'results': results
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


def get_instance_props(cloud_provider: CloudProviderBaseConfig, machine_type: str) -> InstanceProperties:
    """Get properties of a cloud instance."""
    try:
        if cloud_provider.cloud == CSP.GCP:
            instance_props = gcp_get_machine_properties(machine_type)
        else:
            aws = cast(AWSConfig, cloud_provider)
            instance_props = aws_get_machine_properties(machine_type, create_aws_config(aws.region))
    except NotImplementedError as err:
        raise UserReportError(returncode=INPUT_ERROR,
                              message=f'Invalid machine type. Machine type name "{machine_type}" is incorrect or not supported by ElasticBLAST: {str(err)}')
    return instance_props


def compute_default_memory_limit(cloud_provider: CloudProviderBaseConfig,
                                 machine_type: str) -> MemoryStr:
    """
    Compute default memory limit for a BLAST search of a single batch of
    queries. Returns memory available on an instance specified by machine_type
    minus SYSTEM_MEMORY_RESERVE.

    Arguments:
        cloud_provider: Cloud provider config object (GCPConfig or AWSConfig)
        machine_type: Instance type for ElasticBLAST cluster

    Raises:
        UserReportError: if machine type is not recognised or supported by
        ElasticBLAST or it has too littel memory
    """
    try:
        if cloud_provider.cloud == CSP.GCP:
            instance_props = gcp_get_machine_properties(machine_type)
        else:
            aws = cast(AWSConfig, cloud_provider)
            instance_props = aws_get_machine_properties(machine_type, create_aws_config(aws.region))
    except NotImplementedError as err:
        raise UserReportError(returncode=INPUT_ERROR,
                              message=f'Invalid machine type. Machine type name "{machine_type}" is incorrect or not supported by ElasticBLAST: {str(err)}')

    # set memory limit to memory available on the instance minus memory
    # reserved for cloud framework
    # FIXME: Should we consider self.cluster.num_cpus relative to number
    # of CPUs on the instance and lower memory limit accordingly?
    instance_mem = instance_props.memory
    mem_limit = instance_mem - SYSTEM_MEMORY_RESERVE

    if mem_limit <= 0:
        raise UserReportError(returncode=INPUT_ERROR,
                              message=f'The selected machine type {machine_type}: does not have enough memory to run the search. Please, select machine type with more memory.')

    return MemoryStr(f'{mem_limit}G')
