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
Help functions to access AWS resources and manipulate parameters and environment

"""

import getpass
import logging
import re
import time
import os
from collections import defaultdict
from functools import wraps
import json
import inspect
from tempfile import NamedTemporaryFile
from timeit import default_timer as timer
import uuid

from pprint import pformat
from pathlib import Path

from typing import Any, Dict, List, Tuple

import boto3  # type: ignore
from botocore.exceptions import ClientError, NoCredentialsError, ParamValidationError, WaiterError # type: ignore

from .util import convert_labels_to_aws_tags, convert_disk_size_to_gb
from .util import convert_memory_to_mb, UserReportError
from .util import ElbSupportedPrograms, get_usage_reporting, sanitize_aws_batch_job_name
from .constants import BLASTDB_ERROR, CLUSTER_ERROR, ELB_QUERY_LENGTH, PERMISSIONS_ERROR
from .constants import ELB_QUERY_BATCH_DIR, ELB_METADATA_DIR, ELB_LOG_DIR
from .constants import ELB_DOCKER_IMAGE_AWS, INPUT_ERROR, ELB_QS_DOCKER_IMAGE_AWS
from .constants import DEPENDENCY_ERROR, TIMEOUT_ERROR
from .constants import ELB_AWS_JOB_IDS, ELB_S3_PREFIX, ELB_GCS_PREFIX
from .constants import ELB_DFLT_NUM_BATCHES_FOR_TESTING, ELB_UNKNOWN_NUMBER_OF_QUERY_SPLITS
from .constants import ElbStatus, ELB_CJS_DOCKER_IMAGE_AWS
from .constants import ELB_AWS_JANITOR_CFN_TEMPLATE, ELB_DFLT_JANITOR_SCHEDULE_AWS
from .constants import ELB_AWS_JANITOR_LAMBDA_DEPLOYMENT_BUCKET, ELB_AWS_JANITOR_LAMBDA_DEPLOYMENT_KEY
from .constants import CFG_CLOUD_PROVIDER, CFG_CP_AWS_AUTO_SHUTDOWN_ROLE
from .constants import AWS_JANITOR_ROLE_NAME
from .filehelper import parse_bucket_name_key
from .aws_traits import get_machine_properties, create_aws_config, get_availability_zones_for
from .object_storage_utils import write_to_s3
from .base import DBSource
from .elb_config import ElasticBlastConfig
from .elasticblast import ElasticBlast


CF_TEMPLATE = os.path.join(os.path.dirname(__file__), 'templates', 'elastic-blast-cf.yaml')
# the order of job states reflects state transitions and is important for
# ElasticBlastAws.get_job_ids method
AWS_BATCH_JOB_STATES = ['SUBMITTED', 'PENDING', 'RUNNABLE', 'STARTING', 'RUNNING', 'SUCCEEDED', 'FAILED']
SECONDS2SLEEP = 10

def handle_aws_error(f):
    """ Defines decorator to consistently handle exceptions stemming from AWS API calls. """
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except NoCredentialsError as err:
            raise UserReportError(PERMISSIONS_ERROR, str(err))
        except ClientError as err:
            code_str = err.response.get('Error', {}).get('Code', 'Unknown')
            if code_str in ('AccessDenied', 'RequestExpired', 'ExpiredToken', 'ExpiredTokenException'):
                code = PERMISSIONS_ERROR
            else:
                code = CLUSTER_ERROR
            raise UserReportError(code, str(err))
    return wrapper


def check_cluster(cfg: ElasticBlastConfig) -> bool:
    """ Check that cluster described in configuration is running
        Parameters:
            cfg - configuration fo cluster
        Returns:
            true if cluster is running
    """
    if cfg.cluster.dry_run:
        return False
    boto_cfg = create_aws_config(cfg.aws.region)
    cf = boto3.resource('cloudformation', config=boto_cfg)
    try:
        cf_stack = cf.Stack(cfg.cluster.name)
        status = cf_stack.stack_status  # Will throw exception if error/non-existant
        return True
    except ClientError:
        return False


class ElasticBlastAws(ElasticBlast):
    """ Implementation of core ElasticBLAST functionality in AWS.
    Uses a CloudFormation template and AWS Batch for its main operation.
    Uses a nested CloudFormation template and lambda to clean up after itself
    (janitor module)
    """

    def __init__(self, cfg: ElasticBlastConfig, create=False, cleanup_stack: List[Any]=None):
        """ Class constructor: it's meant to be a starting point and to implement
        a base class with the core ElasticBLAST interface
        Parameters:
            cfg - configuration to use for cluster creation
            create - if cluster does not exist, create it. Default: False
        """
        super().__init__(cfg, create, cleanup_stack)
        self._init(cfg, create)

    @handle_aws_error
    def _init(self, cfg: ElasticBlastConfig, create: bool):
        """ Internal constructor, converts AWS exceptions to UserReportError """
        self.boto_cfg = create_aws_config(cfg.aws.region)
        self.stack_name = self.cfg.cluster.name
        logging.debug(f'CloudFormation stack name: {self.stack_name}')

        self.cf = boto3.resource('cloudformation', config=self.boto_cfg)
        self.batch = boto3.client('batch', config=self.boto_cfg)
        self.s3 = boto3.resource('s3', config=self.boto_cfg)
        self.iam = boto3.resource('iam', config=self.boto_cfg)
        self.ec2 = boto3.resource('ec2', config=self.boto_cfg)

        self.owner = getpass.getuser()
        self.results_bucket = cfg.cluster.results
        self.vpc_id = cfg.aws.vpc
        self.subnets = None
        self._provide_subnets()
        self.cf_stack = None
        self.job_ids : List[str] = []
        self.qs_job_id = None

        initialized = True

        # Early check before creating cluster
        if self.cfg.blast and self.cfg.blast.db:
            try:
                self.db, self.db_path, self.db_label = self._get_blastdb_info()
            except:
                # do not report database errors if a cloudformation stack
                # will not be created, e.g.: for job submission on the cloud
                if create:
                    raise

        try:
            if not self.dry_run:
                cf_stack = self.cf.Stack(self.stack_name)
                status = cf_stack.stack_status  # Will throw exception if error/non-existant
                if create:
                    # If we'd want to retry jobs with different parameters on the same cluster we
                    # need to wait here for status == 'CREATE_COMPLETE'
                    raise UserReportError(INPUT_ERROR, f'An ElasticBLAST search that will write '
                                          f'results to {self.results_bucket} has already been submitted '
                                          f'(AWS CloudFormation stack {cf_stack.name}).\nPlease resubmit '
                                          'your search with different value for "results" configuration '
                                          'parameter or delete the previous ElasticBLAST search by running '
                                          'elastic-blast delete.')
                self.cf_stack = cf_stack
                logging.debug(f'Initialized AWS CloudFormation stack {self.cf_stack}: status {status}')
            else:
                logging.debug(f'dry-run: would have initialized {self.stack_name}')
        except ClientError as err:
            if not create:
                logging.error(f'CloudFormation stack {self.stack_name} could not be initialized: {err}')
            initialized = False
        if not initialized and create:
            use_ssd = False
            tags = convert_labels_to_aws_tags(self.cfg.cluster.labels)
            disk_size = convert_disk_size_to_gb(self.cfg.cluster.pd_size)
            disk_type = self.cfg.cluster.disk_type
            instance_type = self.cfg.cluster.machine_type
            # FIXME: This is a shortcut, should be implemented in get_machine_properties
            if re.match(r'[cmr]5a?dn?\.\d{0,2}xlarge', instance_type):
                use_ssd = True
                # Shrink the default EBS root disk since EC2 instances will use locally attached SSDs
                logging.warning("Using gp2 30GB EBS root disk because locally attached SSDs will be used")
                disk_size = 30
                disk_type = 'gp2'
            if instance_type.lower() == 'optimal':  # EXPERIMENTAL!
                max_cpus = self.cfg.cluster.num_nodes * self.cfg.cluster.num_cpus
            else:
                max_cpus = self.cfg.cluster.num_nodes * \
                    get_machine_properties(instance_type, self.boto_cfg).ncpus
            token = cfg.cluster.results.md5
            janitor_schedule = ELB_DFLT_JANITOR_SCHEDULE_AWS
            if not self.cfg.aws.auto_shutdown_role and 'ELB_DISABLE_AUTO_SHUTDOWN' not in os.environ:
                try:
                    role = self.iam.Role(AWS_JANITOR_ROLE_NAME)
                    self.cfg.aws.auto_shutdown_role = role.arn
                    logging.debug(f'Found janitor role for {AWS_JANITOR_ROLE_NAME}: {role.arn}')
                except:
                    logging.debug(f'Did not find janitor role for {AWS_JANITOR_ROLE_NAME}')
            if 'ELB_JANITOR_SCHEDULE' in os.environ:
                janitor_schedule = os.environ['ELB_JANITOR_SCHEDULE']
                logging.debug(f'Overriding janitor schedule to "{janitor_schedule}"')
            if 'ELB_DISABLE_AUTO_SHUTDOWN' in os.environ:
                janitor_schedule = ''
                logging.debug('Disabling janitor')
            elif not self.cfg.aws.auto_shutdown_role:
                janitor_schedule = ''
                logging.debug(f'Disabling janitor due to non-existent {AWS_JANITOR_ROLE_NAME} and unset {CFG_CLOUD_PROVIDER}.{CFG_CP_AWS_AUTO_SHUTDOWN_ROLE}')
            else:
                logging.debug("Submitting ElasticBLAST janitor CloudFormation stack")
            params = [
                {'ParameterKey': 'Owner', 'ParameterValue': self.owner},
                {'ParameterKey': 'MaxCpus', 'ParameterValue': str(max_cpus)},
                {'ParameterKey': 'MachineType', 'ParameterValue': instance_type},
                {'ParameterKey': 'DiskType', 'ParameterValue': disk_type},
                {'ParameterKey': 'DiskSize', 'ParameterValue': str(disk_size)},
                {'ParameterKey': 'DockerImageBlast', 'ParameterValue': ELB_DOCKER_IMAGE_AWS},
                {'ParameterKey': 'DockerImageQuerySplitting', 'ParameterValue': ELB_QS_DOCKER_IMAGE_AWS},
                {'ParameterKey': 'DockerImageJobSubmission', 'ParameterValue': ELB_CJS_DOCKER_IMAGE_AWS},
                {'ParameterKey': 'RandomToken', 'ParameterValue': token},
                {'ParameterKey': 'ElbResults', 'ParameterValue': self.results_bucket},
                {'ParameterKey': 'JanitorSchedule', 'ParameterValue': janitor_schedule},
                {'ParameterKey': 'JanitorTemplateUrl', 'ParameterValue': ELB_AWS_JANITOR_CFN_TEMPLATE},
                {'ParameterKey': 'JanitorLambdaDeploymentS3Bucket', 'ParameterValue': ELB_AWS_JANITOR_LAMBDA_DEPLOYMENT_BUCKET},
                {'ParameterKey': 'JanitorLambdaDeploymentS3Key', 'ParameterValue': ELB_AWS_JANITOR_LAMBDA_DEPLOYMENT_KEY}
            ]
            if self.vpc_id and self.vpc_id.lower() != 'none':
                params.append({'ParameterKey': 'VPC', 'ParameterValue': self.vpc_id})
            else:
                azs = get_availability_zones_for(cfg.aws.region)
                params.append({'ParameterKey': 'NumberOfAZs', 'ParameterValue': str(len(azs))})
            if self.subnets:
                params.append({'ParameterKey': 'Subnets', 'ParameterValue': self.subnets})
            if cfg.aws.security_group and \
                    len(cfg.aws.security_group) > 0:
                params.append({'ParameterKey': 'SecurityGrp',
                               'ParameterValue': cfg.aws.security_group})
            if cfg.aws.key_pair:
                params.append({'ParameterKey': 'EC2KeyPair',
                               'ParameterValue': cfg.aws.key_pair})
            if self.cfg.cluster.iops:
                params.append({'ParameterKey': 'ProvisionedIops', 
                               'ParameterValue': str(self.cfg.cluster.iops)})

            instance_role = self._get_instance_role()
            batch_service_role = self._get_batch_service_role()
            job_role = self._get_job_role()
            spot_fleet_role = self._get_spot_fleet_role()

            if instance_role:
                params.append({'ParameterKey': 'InstanceRole',
                               'ParameterValue': instance_role})

            if batch_service_role:
                params.append({'ParameterKey': 'BatchServiceRole',
                               'ParameterValue': batch_service_role})

            if job_role:
                params.append({'ParameterKey': 'JobRole',
                               'ParameterValue': job_role})

            use_spot_instances = self.cfg.cluster.use_preemptible
            params.append({'ParameterKey': 'UseSpotInstances',
                           'ParameterValue': str(use_spot_instances)})
            if use_spot_instances:
                params.append({'ParameterKey': 'SpotBidPercentage',
                               'ParameterValue': str(self.cfg.cluster.bid_percentage)})
                if spot_fleet_role:
                    params.append({'ParameterKey': 'SpotFleetRole',
                                   'ParameterValue': str(spot_fleet_role)})

            params.append({'ParameterKey': 'UseSSD',
                           'ParameterValue': str(use_ssd).lower()})
            capabilities = []
            if not (instance_role and batch_service_role and job_role and spot_fleet_role):
                # this is needed if cloudformation template creates roles
                capabilities = ['CAPABILITY_NAMED_IAM']

            logging.debug(f'Setting AWS tags: {pformat(tags)}')
            logging.debug(f'Setting AWS CloudFormation parameters: {pformat(params)}')
            logging.debug(f'Creating CloudFormation stack {self.stack_name} from {CF_TEMPLATE}')
            template_body = Path(CF_TEMPLATE).read_text()
            creation_failure_strategy = 'DELETE'
            if 'ELB_ROLLBACK_ON_CFN_CREATION_FAILURE' in os.environ:
                creation_failure_strategy = 'ROLLBACK'
            if not self.dry_run:
                create_stack_args = { 
                    "StackName": self.stack_name,
                    "TemplateBody": template_body,
                    "OnFailure": creation_failure_strategy,
                    "Parameters": params,
                    "Tags": tags,
                    "Capabilities": capabilities
                }
                if self.cfg.aws.auto_shutdown_role:
                    create_stack_args["RoleARN"] = self.cfg.aws.auto_shutdown_role
                self.cf_stack = self.cf.create_stack(**create_stack_args)
                waiter = self.cf.meta.client.get_waiter('stack_create_complete')
                try:
                    # Waiter periodically probes for cloudformation stack
                    # status with default period of 30s and 120 tries.
                    # If it takes over an hour to create a stack, then the code
                    # will exit with an error before the stack is created.
                    waiter.wait(StackName=self.stack_name)
                except WaiterError as err:
                    # report cloudformation stack creation timeout
                    if self.cf_stack.stack_status == 'CREATE_IN_PROGRESS':
                        raise UserReportError(returncode=TIMEOUT_ERROR,
                                              message='CloudFormation stack creation has timed out')

                    # report cloudformation stack creation error,
                    elif self.cf_stack.stack_status != 'CREATE_COMPLETE':
                        # report error message
                        message = 'CloudFormation stack creation failed'
                        stack_messages = self._get_cloudformation_errors()
                        if stack_messages:
                            message += f' with error message {". ".join(stack_messages)}'
                        else:
                            message += f' for unknown reason.'
                        message += ' Please, run elastic-blast delete to remove CloudFormation stack with errors'
                        raise UserReportError(returncode=DEPENDENCY_ERROR,
                                              message=message)

                status = self.cf_stack.stack_status
                logging.debug(f'Created AWS CloudFormation stack {self.cf_stack}: status {status}')

            else:
                logging.debug(f'dry-run: would have registered CloudFormation template {template_body}')

        # get job queue name and job definition name from cloudformation stack
        # outputs
        self.job_queue_name = None
        self.blast_job_definition_name = None
        self.qs_job_definition_name = None
        self.js_job_definition_name = None
        self.compute_env_name = None
        if not self.dry_run and self.cf_stack and \
               self.cf_stack.stack_status == 'CREATE_COMPLETE':
            for output in self.cf_stack.outputs:
                if output['OutputKey'] == 'JobQueueName':
                    self.job_queue_name = output['OutputValue']
                elif output['OutputKey'] == 'BlastJobDefinitionName':
                    self.blast_job_definition_name = output['OutputValue']
                elif output['OutputKey'] == 'QuerySplittingJobDefinitionName':
                    self.qs_job_definition_name = output['OutputValue']
                elif output['OutputKey'] == 'JobSubmissionJobDefinitionName':
                    self.js_job_definition_name = output['OutputValue']
                elif output['OutputKey'] == 'ComputeEnvName':
                    self.compute_env_name = output['OutputValue']

            if self.job_queue_name:
                logging.debug(f'JobQueueName: {self.job_queue_name}')
            else:
                raise UserReportError(returncode=DEPENDENCY_ERROR, message='JobQueueName could not be read from CloudFormation stack')

            if self.blast_job_definition_name:
                logging.debug(f'BlastJobDefinitionName: {self.blast_job_definition_name}')
            else:
                raise UserReportError(returncode=DEPENDENCY_ERROR, message='BlastJobDefinitionName could not be read from CloudFormation stack')

            if self.qs_job_definition_name:
                logging.debug(f'QuerySplittingJobDefinitionName: {self.qs_job_definition_name}')
            else:
                raise UserReportError(returncode=DEPENDENCY_ERROR, message='QuerySplittingJobDefinitionName could not be read from CloudFormation stack')

            if self.js_job_definition_name:
                logging.debug(f'JobSubmissionJobDefinitionName: {self.js_job_definition_name}')
            else:
                raise UserReportError(returncode=DEPENDENCY_ERROR, message='JobSubmissionJobDefinitionName could not be read from CloudFormation stack')

            if self.compute_env_name:
                logging.debug(f'ComputeEnvName: {self.compute_env_name}')
            else:
                logging.warning('ComputeEnvName could not be read from CloudFormation stack')

    def _provide_subnets(self):
        """ Read subnets from config file or if not set try to get them from default VPC """
        if self.dry_run:
            return
        if not self.cfg.aws.subnet:
            logging.debug("Subnets are not provided")
            # Try to get subnet from default VPC or VPC set in aws-vpc config parameter
            vpc = self._provide_vpc()
            if vpc:
                subnet_list = vpc.subnets.all()
                self.vpc_id = vpc.id
                self.subnets = ','.join(map(lambda x: x.id, subnet_list))
        else:
            # Ensure that VPC is set and that subnets provided belong to it
            subnets = [x.strip() for x in self.cfg.aws.subnet.split(',')]
            # If aws-vpc parameter is set, use this VPC, otherwise use VPC of the
            # first subnet
            logging.debug(f"Subnets are provided: {' ,'.join(subnets)}")
            vpc = None
            if self.vpc_id:
                if self.vpc_id.lower() == 'none':
                    return
                vpc = self.ec2.Vpc(self.vpc_id)
            for subnet_name in subnets:
                subnet = self.ec2.Subnet(subnet_name)
                if not vpc:
                    vpc = subnet.vpc # if subnet is invalid - will throw an exception botocore.exceptions.ClientError with InvalidSubnetID.NotFound
                else:
                    if subnet.vpc != vpc:
                        raise UserReportError(returncode=INPUT_ERROR, message="Subnets set in aws-subnet parameter belong to different VPCs")
            self.vpc_id = vpc.id
            self.subnets = ','.join(subnets)
        logging.debug(f"Using VPC {self.vpc_id}, subnet(s) {self.subnets}")

    def _provide_vpc(self):
        """ Get boto3 Vpc object for either configured VPC, or if not, default VPC for the
            configured region, if not available return None """
        if self.vpc_id:
            if self.vpc_id.lower() == 'none':
                return None
            return self.ec2.Vpc(self.vpc_id)
        vpcs = list(self.ec2.vpcs.filter(Filters=[{'Name':'isDefault', 'Values':['true']}]))
        if len(vpcs) > 0:
            logging.debug(f'Default vpc is {vpcs[0].id}')
            return vpcs[0]
        else:
            return None

    def _get_instance_role(self) -> str:
        """Find role for AWS ECS instances.
        Returns:
            * cfg.aws.instance_role value in config, if provided,
            * otherwise, ecsInstanceRole if this role and instance profile exist
            in AWS account,
            * otherwise, an empty string"""

        # if instance role is set in config, return it
        if self.cfg.aws.instance_role:
            logging.debug(f'Instance role provided from config: {self.cfg.aws.instance_role}')
            return self.cfg.aws.instance_role

        # check if ecsInstanceRole is present in the account and return it,
        # if it is
        # instance profile and role, both named ecsInstanceRole must exist
        DFLT_INSTANCE_ROLE_NAME = 'ecsInstanceRole'
        instance_profile = self.iam.InstanceProfile(DFLT_INSTANCE_ROLE_NAME)
        try:
            role_names = [i.name for i in instance_profile.roles]
            if DFLT_INSTANCE_ROLE_NAME in role_names:
                logging.debug(f'Using {DFLT_INSTANCE_ROLE_NAME} present in the account')
                return DFLT_INSTANCE_ROLE_NAME
        except self.iam.meta.client.exceptions.NoSuchEntityException:
            # an exception means that ecsInstanceRole is not defined in the
            # account
            pass

        # otherwise return en empty string, which cloudformation template
        # will interpret to create the instance role
        logging.debug('Instance role will be created by CloudFormation')
        return ''

    def _get_batch_service_role(self):
        """Find AWS Batch service role.
        Returns:
            * cfg.aws.batch_service_role value in config, if provided,
            * otherwise, AWSBatchServiceRole if this role if it exists in AWS account,
            * otherwise, an empty string"""
        # if batch service role is set in config, return it
        if self.cfg.aws.batch_service_role:
            logging.debug(f'Batch service role provided from config: {self.cfg.aws.batch_service_role}')
            return self.cfg.aws.batch_service_role

        # check if ecsInstanceRole is present in the account and return it,
        # if it is
        # instance profile and role, both named ecsInstanceRole must exist
        DFLT_BATCH_SERVICE_ROLE_NAME = 'AWSBatchServiceRole'
        role = self.iam.Role(DFLT_BATCH_SERVICE_ROLE_NAME)
        try:
            # Accessing role.arn will trigger an exception if the role is
            # not defined
            _ = role.arn
            logging.debug(f'Using {role.name} present in the account')
            return role.arn
        except self.iam.meta.client.exceptions.NoSuchEntityException:
            # an exception means that the role is not defined in the account
            pass

        # otherwise return en empty string, which cloudformation template
        # will interpret to create the instance role
        logging.debug('Batch service role will be created by CloudFormation')
        return ''

    def _get_job_role(self):
        """Find AWS Batch job role.
        Returns:
            cfg.aws.job_role value in config, if provided,
            otherwise, an empty string"""
        if self.cfg.aws.job_role:
            job_role = self.cfg.aws.job_role
            logging.debug(f'Using Batch job role provided from config: {job_role}')
            return job_role
        else:
            logging.debug('Batch job role will be created by CloudFormation')
            return ''

    def _get_spot_fleet_role(self):
        """Find AWS EC2 Spot Fleet role.
        Returns:
            cfg.aws.spot_fleet_role value in config, if provided,
            otherwise, an empty string"""
        if self.cfg.aws.spot_fleet_role:
            role = self.cfg.aws.spot_fleet_role
            logging.debug(f'Using Spot Fleet role provided from config: {role}')
            return role
        else:
            logging.debug('Spot Fleet role will be created by CloudFormation')
            return ''


    @handle_aws_error
    def delete(self):
        """Delete a CloudFormation stack associated with AWS Batch resources,
           convert AWS exceptions to UserReportError """
        logging.debug(f'Request to delete {self.stack_name}')
        if not self.dry_run:
            if not self.cf_stack:
                logging.info(f"AWS CloudFormation stack {self.stack_name} doesn't exist, nothing to delete")
                return
            logging.debug(f'Deleting AWS CloudFormation stack {self.stack_name}')
            self._remove_ancillary_data(ELB_QUERY_BATCH_DIR)
            self.cf_stack.delete()
            for sd in [ELB_METADATA_DIR, ELB_LOG_DIR]:
                self._remove_ancillary_data(sd)
            waiter = self.cf.meta.client.get_waiter('stack_delete_complete')
            try:
                waiter.wait(StackName=self.stack_name)
            except WaiterError:
                # report cloudformation stack deletion timeout
                if self.cf_stack.stack_status == 'DELETE_IN_PROGRESS':
                    raise UserReportError(returncode=TIMEOUT_ERROR,
                                          message='CloudFormation stack deletion has timed out')

                # report cloudformation stack deletion error
                elif self.cf_stack.stack_status != 'DELETE_COMPLETE':
                    message = 'CloudFormation stack deletion failed'
                    stack_messages = self._get_cloudformation_errors()
                    if stack_messages:
                        message += f' with errors {". ".join(stack_messages)}'
                    else:
                        message += ' for unknown reason'
                    raise UserReportError(returncode=DEPENDENCY_ERROR,
                                          message=message)
            logging.debug(f'Deleted AWS CloudFormation stack {self.stack_name}')
        else:
            logging.debug(f'dry-run: would have deleted {self.stack_name}')

    def _get_blastdb_info(self) -> Tuple[str, str, str]:
        """Returns a tuple of BLAST database basename, path (if applicable), and label
        suitable for job name. Gets user provided database from configuration.
        For custom database finds basename from full path, and provides
        correct path for db retrieval.
        For standard database the basename is the only value provided by the user,
        and the path name returned is empty.
        Example
        cfg.blast.db = pdb_nt -> 'pdb_nt', 'None', 'pdb_nt'
        cfg.blast.db = s3://example/pdb_nt -> 'pdb_nt', 's3://example', 'pdb_nt'
        """
        db = self.cfg.blast.db
        db_path = 'None'
        if db.startswith(ELB_S3_PREFIX):
            #TODO: support tar.gz database
            bname, key = parse_bucket_name_key(db)
            if not self.dry_run:
                try:
                    bucket = self.s3.Bucket(bname)
                    if len(list(bucket.objects.filter(Prefix=key, Delimiter='/'))) == 0:
                        raise RuntimeError
                except:
                    raise UserReportError(returncode=BLASTDB_ERROR,
                                          message=f'{db} is not a valid BLAST database')
            db_path = os.path.dirname(db)
            db = os.path.basename(db)
        elif db.startswith(ELB_GCS_PREFIX):
            raise UserReportError(returncode=BLASTDB_ERROR,
                                  message=f'User database should be in the AWS S3 bucket')

        return db, db_path, sanitize_aws_batch_job_name(db)


    @handle_aws_error
    def cloud_query_split(self, query_files: List[str]) -> None:
        """ Submit the query sequences for splitting to the cloud.
            Parameters:
                query_files     - list files containing query sequence data to split

        Current implementation:
        Submit AWS Batch query splitting job, wait for results, then submit
        AWS Batch BLAST jobs. Downside: for long query splitting jobs, user
        still waits for a long time while query splitting is happening

        Ideas on how to improve this
        1. Refactor AWS Batch BLAST job submission code so that it can live in
           the same docker image as the query splitting code
        2. After query split has completed, that same docker image
           submits AWS Batch BLAST jobs, and
           saves the job IDs on the results bucket

        A more decoupled approach: elastic-blast submit creates 2 AWS Batch jobs:
        1. After the query splitting job is started on the cloud
        2. Start another job, that depends on the query splitting job
           This job submits AWS Batch BLAST jobs on the cloud
          (and in the future k8s jobs also) and saves the job IDs to the results bucket

        """
        overrides: Dict[str, Any] = {
            'vcpus': self.cfg.cluster.num_cpus,
            'memory': int(convert_memory_to_mb(self.cfg.cluster.mem_limit))
        }
        # FIXME: handle multiple files by concatenating them?
        parameters = {'input': query_files[0],
                      'batchlen': str(self.cfg.blast.batch_len),
                      'output': self.results_bucket}
        logging.debug(f'Query splitting job definition container overrides {overrides}')
        logging.debug(f"Query splitting job definition parameters {parameters}")
        jname = f'elasticblast-{self.owner}-{self.cfg.cluster.results.md5}-query-split'
        if not self.dry_run:
            logging.debug(f"Launching query splitting job named {jname}")
            job = self.batch.submit_job(jobQueue=self.job_queue_name,
                                        jobDefinition=self.qs_job_definition_name,
                                        jobName=jname,
                                        parameters=parameters,
                                        containerOverrides=overrides)
            self.qs_job_id = job['jobId']
            logging.info(f"Submitted AWS Batch job {job['jobId']} to split query {query_files[0]}")
            self.upload_job_ids()
        else:
            logging.debug(f'dry-run: would have submitted {jname}')


    @handle_aws_error
    def wait_for_cloud_query_split(self) -> None:
        """ Interim implementation of query splitting on the cloud using a dual
            AWS Batch job approach
        """
        if self.dry_run:
            return
        if not self.qs_job_id:
            msg = 'Query splitting job was not submitted!'
            logging.fatal(msg)
            raise RuntimeError(msg)

        while True:
            job_batch = self.batch.describe_jobs(jobs=[self.qs_job_id])['jobs']
            job_status = job_batch[0]['status']
            logging.debug(f'Query splitting job status {job_status} for {self.qs_job_id}')
            if job_status == 'SUCCEEDED':
                break
            if job_status == 'FAILED':
                batch_of_jobs = self.batch.list_jobs(jobQueue=self.job_queue_name, jobStatus='FAILED')
                job = batch_of_jobs['jobSummaryList'][0]
                logging.debug(f'Failed query splitting job {pformat(job)}')
                failure_details: str = ''
                if 'container' in job:
                    container = job['container']
                    for k in ['exitCode', 'reason']:
                        if k in container:
                            failure_details += f'Container{k[0].upper()+k[1:]}: {container[k]} '
                msg = f'Query splitting on the cloud failed (jobId={self.qs_job_id})'
                if failure_details: msg += failure_details
                logging.fatal(msg)
                raise UserReportError(CLUSTER_ERROR, msg)
            time.sleep(SECONDS2SLEEP)


    @handle_aws_error
    def submit(self, query_batches: List[str], query_length, one_stage_cloud_query_split: bool) -> None:
        """ Submit query batches to cluster, converts AWS exceptions to UserReportError
            Parameters:
                query_batches               - list of bucket names of queries to submit
                query_length                - total query length
                one_stage_cloud_query_split - do the query split in the cloud as a part
                                              of executing a regular job """
        if self.cloud_job_submission:
            self._cloud_submit()
        else:
            self.client_submit(query_batches, one_stage_cloud_query_split)


    def _cloud_submit(self) -> None:
        parameters = {'db': self.db,
                      'num-vcpus': str(self.cfg.cluster.num_cpus),
                      'mem-limit': self.cfg.cluster.mem_limit,
                      'blast-program': self.cfg.blast.program,
                      'blast-options': self.cfg.blast.options,
                      'bucket': self.results_bucket,
                      'region': self.cfg.aws.region}

        if self.cfg.blast.taxidlist:
            parameters['taxidlist'] = self.cfg.blast.taxidlist
        if logging.getLogger(__name__).getEffectiveLevel() == logging.DEBUG:
            parameters['loglevel'] = 'DEBUG'
            parameters['logfile'] = 'stderr'

        overrides = {'vcpus': self.cfg.cluster.num_cpus,
                     'memory': int(convert_memory_to_mb(self.cfg.cluster.mem_limit)),
                     'environment': [{'name': 'ELB_CLUSTER_NAME',
                                      'value': self.cfg.cluster.name}]
        }

        # FIXME: It may be better to make usage report part of config that
        # ElasticBlastConfig sets from environment
        if 'BLAST_USAGE_REPORT' in os.environ:
            ovr_env = overrides['environment']
            assert isinstance(ovr_env, List)
            ovr_env.append({'name': 'BLAST_USAGE_REPORT',
                                             'value': os.environ['BLAST_USAGE_REPORT']})

        logging.debug(f'Job submission in the cloud parameters: {parameters}')
        logging.debug(f'Job submission in the cloud overrides: {overrides}')
        jname = f'elasticblast-{self.owner}-{self.cfg.cluster.results.md5}-job-submissions'
        if not self.dry_run:
            logging.debug(f'Submit-jobs job definition name: {self.js_job_definition_name}')
            submit_job_args = {
                "jobQueue": self.job_queue_name,
                "jobDefinition": self.js_job_definition_name,
                "jobName": jname,
                "parameters": parameters,
                "containerOverrides": overrides
            }
            if self.qs_job_id:
                submit_job_args["dependsOn"] = [{'jobId': self.qs_job_id}]
            job = self.batch.submit_job(**submit_job_args)
            logging.info(f'Submitted AWS Batch job {job["jobId"]} to submit search jobs')
            self.job_ids.append(job['jobId'])
            self.upload_job_ids()


    @handle_aws_error
    def client_submit(self, query_batches: List[str], one_stage_cloud_query_split: bool) -> None:
        """ Submit query batches to cluster, converts AWS exceptions to UserReportError
            Parameters:
                query_batches               - list of bucket names of queries to submit
                one_stage_cloud_query_split - do the query split in the cloud as a part
                                              of executing a regular job """
        self.job_ids = []

        prog = self.cfg.blast.program

        if self.cfg.cluster.db_source != DBSource.AWS:
            logging.warning(f'BLAST databases for AWS based ElasticBLAST obtained from {self.cfg.cluster.db_source.name}')

        overrides: Dict[str, Any] = {
            'vcpus': self.cfg.cluster.num_cpus,
            'memory': int(convert_memory_to_mb(self.cfg.cluster.mem_limit))
        }
        usage_reporting = get_usage_reporting()
        elb_job_id = uuid.uuid4().hex

        parameters = {'db': self.db,
                      'db-path': self.db_path,
                      'db-source': self.cfg.cluster.db_source.name,
                      'db-mol-type': str(ElbSupportedPrograms().get_db_mol_type(prog)),
                      'num-vcpus': str(self.cfg.cluster.num_cpus),
                      'blast-program': prog,
                      'blast-options': self.cfg.blast.options,
                      'bucket': self.results_bucket}

        if self.cfg.blast.taxidlist:
            parameters['taxidlist'] = self.cfg.blast.taxidlist

        no_search = 'ELB_NO_SEARCH' in os.environ
        if no_search:
            parameters['do-search'] = '--no-search'

        logging.debug(f'Job definition container overrides {overrides}')

        num_parts = ELB_UNKNOWN_NUMBER_OF_QUERY_SPLITS
        if one_stage_cloud_query_split:
            num_parts = len(query_batches)
            logging.debug(f'Performing one stage cloud query split into {num_parts} parts')
        parameters['num-parts'] = str(num_parts)

        # For testing purposes if there is no search requested
        # we can use limited number of jobs
        if (no_search and one_stage_cloud_query_split) or 'ELB_PERFORMANCE_TESTING' in os.environ:
            nbatches2test = ELB_DFLT_NUM_BATCHES_FOR_TESTING
            def is_int(value: str):
                try:
                    int(value)
                    return True
                except:
                    return False
            if is_int(os.environ['ELB_PERFORMANCE_TESTING']):
                nbatches2test = int(os.environ['ELB_PERFORMANCE_TESTING'])
            query_batches = query_batches[:nbatches2test]
            logging.debug(f'For testing purposes will only process a subset of query batches: {nbatches2test}')

        start = timer()
        for i, q in enumerate(query_batches):
            parameters['query-batch'] = q
            parameters['split-part'] = str(i)
            jname = f'elasticblast-{self.owner}-{prog}-batch-{self.db_label}-job-{i}'
            # add random search id for ElasticBLAST usage reporting
            # and pass BLAST_USAGE_REPORT environment var to container
            if usage_reporting:
                overrides['environment'] = [{'name': 'BLAST_ELB_JOB_ID',
                                             'value': elb_job_id},
                                            {'name': 'BLAST_USAGE_REPORT',
                                             'value': 'true'},
                                            {'name': 'BLAST_ELB_BATCH_NUM',
                                             'value': str(i)}]
            else:
                overrides['environment'] = [{'name': 'BLAST_USAGE_REPORT',
                                             'value': 'false'}]
            if not self.dry_run:
                submit_job_args = {
                    "jobQueue": self.job_queue_name,
                    "jobDefinition": self.blast_job_definition_name,
                    "jobName": jname,
                    "parameters": parameters,
                    "containerOverrides": overrides
                }
                if self.qs_job_id:
                    submit_job_args["dependsOn"] = [{'jobId': self.qs_job_id}]
                job = self.batch.submit_job(**submit_job_args)
                self.job_ids.append(job['jobId'])
                logging.debug(f"Job definition parameters for job {job['jobId']} {parameters}")
                logging.info(f"Submitted AWS Batch job {job['jobId']} with query {q}")
            else:
                logging.debug(f'dry-run: would have submitted {jname} with query {q}')
        end = timer()
        logging.debug(f'RUNTIME submit-jobs {end-start} seconds')
        logging.debug(f'SPEED to submit-jobs {len(query_batches)/(end-start):.2f} jobs/second')

        if not self.dry_run:
            # upload AWS-Batch job ids to results bucket for better search
            # status checking
            self.upload_job_ids()


    def get_job_ids(self) -> List[str]:
        """Get a list of batch job ids"""
        # we can only query for job ids by jobs states which can change
        # between calls, so order in which job states are processed matters
        ids = defaultdict(int)
        logging.debug(f'Retrieving job IDs from job queue {self.job_queue_name}')
        for status in AWS_BATCH_JOB_STATES:
            batch_of_jobs = self.batch.list_jobs(jobQueue=self.job_queue_name,
                                             jobStatus=status)
            for j in batch_of_jobs['jobSummaryList']:
                ids[j['jobId']] = 1

            while 'nextToken' in batch_of_jobs:
                batch_of_jobs = self.batch.list_jobs(jobQueue=self.job_queue_name,
                                                     jobStatus=status,
                                                     nextToken=batch_of_jobs['nextToken'])
                for j in batch_of_jobs['jobSummaryList']:
                    ids[j['jobId']] = 1

        logging.debug(f'Retrieved {len(ids.keys())} job IDs')
        return list(ids.keys())


    def upload_job_ids(self) -> None:
        """Save AWS Batch job ids in a metadata file in S3, if the metadata
        file is present, append job ids"""
        self._load_job_ids_from_aws()
        bucket_name, key = parse_bucket_name_key(f'{self.results_bucket}/{ELB_METADATA_DIR}/{ELB_AWS_JOB_IDS}')
        bucket = self.s3.Bucket(bucket_name)
        job_ids = self.job_ids
        if self.qs_job_id:
            job_ids.append(self.qs_job_id)
        job_ids = list(set(job_ids))
        bucket.put_object(Body=json.dumps(job_ids).encode(), Key=key)
        logging.debug(f'Uploaded {len(job_ids)} job IDs to {self.results_bucket}/{ELB_METADATA_DIR}/{ELB_AWS_JOB_IDS}')


    def upload_query_length(self, query_length: int) -> None:
        """Save query length in a metadata file in S3"""
        if query_length <= 0: return
        if not self.dry_run:
            write_to_s3(os.path.join(self.results_bucket, ELB_METADATA_DIR, ELB_QUERY_LENGTH), str(query_length), self.boto_cfg)
        else:
            logging.debug('dry-run: would have uploaded query length')


    def check_status(self, extended=False) -> Tuple[ElbStatus, Dict[str, int], str]:
        """ Check execution status of ElasticBLAST search
        Parameters:
            extended - do we need verbose information about jobs
        Returns:
            tuple of
                status - cluster status, ElbStatus
                counts - job counts for all job states
                verbose_result - detailed info about jobs
        """
        try:
            retval = ElbStatus.UNKNOWN

            counts, details = self._check_status(extended)
            njobs = sum(counts.values())
            pending = counts['pending']
            running = counts['running']
            succeeded = counts['succeeded']
            failed = counts['failed']
            logging.debug(f'NumJobs {njobs} Pending {pending} Running {running} Succeeded {succeeded} Failed {failed}')
            if failed > 0:
                retval = ElbStatus.FAILURE
            elif njobs == 0:
                # This is likely the case when dry-run is set to True
                retval = ElbStatus.UNKNOWN
            elif running > 0 or pending > 0:
                retval = ElbStatus.RUNNING
            elif (pending + running + failed) == 0 and succeeded == njobs:
                retval = ElbStatus.SUCCESS

            return retval, counts, details

        except ParamValidationError:
            raise UserReportError(CLUSTER_ERROR, f"Cluster {self.stack_name} is not valid or not created yet")

    def _load_job_ids_from_aws(self):
        """ Retrieve the list of AWS Batch job IDs from AWS S3. Missing file
            in S3 means that list of job ids is empty.
            Post-condition: self.job_ids contains the list of job IDs for this search
        """
        with NamedTemporaryFile() as tmp:
            bucket_name, key = parse_bucket_name_key(os.path.join(self.results_bucket, ELB_METADATA_DIR, ELB_AWS_JOB_IDS))
            bucket = self.s3.Bucket(bucket_name)
            try:
                bucket.download_file(key, tmp.name)
                with open(tmp.name) as f_ids:
                    self.job_ids += json.load(f_ids)
                    self.job_ids = list(set(self.job_ids))
            except ClientError as err:
                err_code = err.response['Error']['Code']
                fnx_name = inspect.stack()[0].function
                if err_code == "404":
                    logging.debug(f'{fnx_name} failed to retrieve {os.path.join(self.results_bucket, ELB_METADATA_DIR, ELB_AWS_JOB_IDS)}: error code {err_code}')
                else:
                    logging.debug(f'{fnx_name} raised exception on ClientError: {pformat(err.response)}')
                    raise

    @handle_aws_error
    def _check_status(self, extended) -> Tuple[Dict[str, int], str]:
        """ Internal check_status, converts AWS exceptions to UserReportError  """
        counts : Dict[str, int] = defaultdict(int)
        if self.dry_run:
            logging.info('dry-run: would have checked status')
            return counts, ''

        if extended:
            return self._check_status_extended()

        if not self.job_ids:
            self._load_job_ids_from_aws()

        # check status of jobs in batches of JOB_BATCH_NUM
        JOB_BATCH_NUM = 100
        for i in range(0, len(self.job_ids), JOB_BATCH_NUM):
            job_batch = self.batch.describe_jobs(jobs=self.job_ids[i:i + JOB_BATCH_NUM])['jobs']
            # get number for AWS Batch job states
            for st in AWS_BATCH_JOB_STATES:
                counts[st] += sum([j['status'] == st for j in job_batch])

        # compute numbers for elastic-blast job states
        status = {
            'pending': counts['SUBMITTED'] + counts['PENDING'] + counts['RUNNABLE'] + counts['STARTING'],
            'running':  counts['RUNNING'],
            'succeeded': counts['SUCCEEDED'],
            'failed': counts['FAILED'],
        }
        return status, ''

    def _check_status_extended(self) -> Tuple[Dict[str, int], str]:
        """ Internal check_status_extended, not protected against exceptions in AWS """
        logging.debug(f'Retrieving jobs for queue {self.job_queue_name}')
        jobs = {}
        # As statuses in AWS_BATCH_JOB_STATES are ordered in job transition
        # succession, if job changes status between calls it will be reflected
        # in updated value in jobs dictionary
        for status in AWS_BATCH_JOB_STATES:
            batch_of_jobs = self.batch.list_jobs(jobQueue=self.job_queue_name,
                                            jobStatus=status)
            for j in batch_of_jobs['jobSummaryList']:
                jobs[j['jobId']] = j

            while 'nextToken' in batch_of_jobs:
                batch_of_jobs = self.batch.list_jobs(jobQueue=self.job_queue_name,
                                                    jobStatus=status,
                                                    nextToken=batch_of_jobs['nextToken'])
                for j in batch_of_jobs['jobSummaryList']:
                    jobs[j['jobId']] = j
        counts : Dict[str, int] = defaultdict(int)
        detailed_info: Dict[str, List[str]] = defaultdict(list)
        pending_set = set(['SUBMITTED', 'PENDING', 'RUNNABLE', 'STARTING'])
        for job_id, job in jobs.items():
            if job['status'] in pending_set:
                status = 'pending'
            else:
                status = job['status'].lower()
            counts[status] += 1
            info = [f' {len(detailed_info[status])+1}. ']
            for k in ['jobArn', 'jobName', 'statusReason']:
                if k in job:
                    info.append(f'  {k[0].upper()+k[1:]}: {job[k]}')
            if 'container' in job:
                container = job['container']
                for k in ['exitCode', 'reason']:
                    if k in container:
                        info.append(f'  Container{k[0].upper()+k[1:]}: {container[k]}')
            if 'startedAt' in job and 'stoppedAt' in job:
                # NB: these Unix timestamps are in milliseconds
                info.append(f'  RuntimeInSeconds: {(job["stoppedAt"] - job["startedAt"])/1000}')
            detailed_info[status].append('\n'.join(info))
        detailed_rep = []
        for status in ['pending', 'running', 'succeeded', 'failed']:
            jobs_in_status = len(detailed_info[status])
            detailed_rep.append(f'{status.capitalize()} {jobs_in_status}')
            if jobs_in_status:
                detailed_rep.append('\n'.join(detailed_info[status]))
        return counts, '\n'.join(detailed_rep)

    def _remove_ancillary_data(self, bucket_prefix: str) -> None:
        """ Removes ancillary data from the end user's result bucket
        bucket_prefix: path that follows the users' bucket name (looks like a file system directory)
        """
        bname, _ = parse_bucket_name_key(self.results_bucket)
        if not self.dry_run:
            s3_bucket = self.s3.Bucket(bname)
            s3_bucket.objects.filter(Prefix=bucket_prefix).delete()
        else:
            logging.debug(f'dry-run: would have removed {bname}/{bucket_prefix}')

    def _get_cloudformation_errors(self) -> List[str]:
        """Iterate over cloudformation stack events and extract error messages
        for failed resource creation or deletion. Cloudformation stack object
        must already be initialized.
        """
        # cloudformation stack must be initialized
        assert self.cf_stack
        messages = []
        for event in self.cf_stack.events.all():
            if event.resource_status == 'CREATE_FAILED' or \
                    event.resource_status == 'DELETE_FAILED':
                # resource creation may be canceled because other resources
                # were not created, these are not useful for reporting
                # problems
                if 'Resource creation cancelled' not in event.resource_status_reason:
                    messages.append(f'{event.logical_resource_id}: {event.resource_status_reason}')
        return messages

    def __str__(self):
        """ Print details about stack passed in as an argument, for debugging """
        st = self.cf_stack
        retval = f'Stack id: {st.stack_id}'
        retval += f'Stack name: {st.stack_name}'
        retval += f'Stack description: {st.description}'
        retval += f'Stack creation-time: {st.creation_time}'
        retval += f'Stack last-update: {st.last_updated_time}'
        retval += f'Stack status: {st.stack_status}'
        retval += f'Stack status reason: {st.stack_status_reason}'
        retval += f'Stack outputs: {st.outputs}'
        return retval
