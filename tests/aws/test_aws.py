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
Unit tests for aws module

"""
# A few notes for mocked unit tests

# Boto3 calls are mocked in "with mocked_<api name>()" blocks. You need to use
# this call for each AWS API accessed in the test. If you get authorization
# error, you very likely forgot to call this.

# To make things easier, the cloudformation, iam, ec2, batch, and s3 fixtures
# do the above for you.

# To make things even easier, if you need elastic_blast.aws.ElasticBlastAws object with
# default parameters, use ElasticBlastAws fixture (see
# test_ElasticBlastAws_init_auto_vpc as an example). If you need to modify
# elastic-blast config, use at least cloudformation, iam, ec2, and batch
# fixtures (see test_ElasticBlastAws_init_custom_vpc as an example).

# Mocks must be set up before boto3 clients, so if we have any code in elastic_blast.aws
# that initializes boto3 clients during import, aws will have to be
# imported inside test function.

import configparser
import os
import json
import re
import boto3 #type: ignore
import getpass
from moto import mock_batch, mock_s3, mock_ec2, mock_cloudformation, mock_iam #type: ignore

from elastic_blast import aws
from elastic_blast import aws_traits
from elastic_blast.constants import ELB_DFLT_AWS_REGION, CSP
from elastic_blast.constants import BLASTDB_ERROR, DEPENDENCY_ERROR, INPUT_ERROR
from elastic_blast.constants import ElbCommand
from elastic_blast.util import UserReportError
from elastic_blast.filehelper import parse_bucket_name_key
from elastic_blast.base import InstanceProperties, DBSource
from elastic_blast.elb_config import ElasticBlastConfig, PositiveInteger
from tests.utils import aws_credentials

from botocore.exceptions import ClientError #type: ignore
from unittest.mock import call
import pytest


TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'config', 'data')
TEST_CONFIG_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


@pytest.fixture
def ec2(aws_credentials):
    """Get mocked API for EC2"""
    with mock_ec2():
        yield boto3.resource('ec2')


@pytest.fixture()
def iam(aws_credentials):
    """Get mocked API for AWS IAM"""
    with mock_iam():
        yield boto3.resource('iam')


@pytest.fixture()
def cloudformation(aws_credentials):
    """Get mocked API for AWS cloudformation"""
    with mock_cloudformation():
        yield boto3.resource('cloudformation')


@pytest.fixture()
def batch(aws_credentials):
    """Get mocked API for AWS Batch"""
    with mock_batch():
        yield boto3.client('batch')


@pytest.fixture()
def s3(aws_credentials):
    """Get mocked API for S3"""
    with mock_s3():
        yield boto3.resource('s3')


def create_roles():
    """Create roles needed for AWS Batch compute environment.

    Returns:
        Batch service role, ecsInstanceRole
    """
    iam = boto3.resource('iam')

    # FIXME: Permission checking is currently disabled in Moto (default
    # setting), so the roles do not require policies.
    service_role = iam.create_role(
        RoleName="BatchServiceRole",
        AssumeRolePolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "batch.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            }
        ),
    )

    instance_role = iam.create_role(
        RoleName="InstanceRole",
        AssumeRolePolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "ec2.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                    }
                ],
            }
        ),
    )

    instance_profile = iam.create_instance_profile(
        InstanceProfileName="InstanceProfile")
    instance_profile.add_role(RoleName=instance_role.name)

    return service_role, instance_profile


def initialize_cfg() -> ElasticBlastConfig:
    """Create minimal config for an AWS search"""

    cfg = ElasticBlastConfig(aws_region = 'us-east-1',
                             program = 'blastn',
                             db = 'test-db',
                             results = f's3://elasticblast-{getpass.getuser()}',
                             queries = 's3://test-bucket/test.fa',
                             task = ElbCommand.SUBMIT)

    cfg.aws.key_pair = 'test-key'
    cfg.cluster.name = 'test-cluster'
    cfg.cluster.num_nodes = PositiveInteger(1)

    return cfg


def create_ElasticBlastAws(cfg: ElasticBlastConfig):
    """Create elastic_blast.aws.ElasticBlastAws object with default parameters unless set
    otherwise.

    Arguments:
        cfg: Elastic-BLAST config

    Returns:
        elastic_blast.aws.ElasticBlastAws object
    """
    service_role, instance_profile = create_roles()

    # set up necessary config values, unless they came in set
    cfg.aws.batch_service_role = service_role.arn
    cfg.aws.instance_role = instance_profile.arn
    return aws.ElasticBlastAws(cfg, create=True)


@pytest.fixture
def ElasticBlastAws(cloudformation, iam, ec2, batch):
    """Fixture that creates elastic_blast.aws.ElasticBlastAws object with default
    parameters"""
    cfg = initialize_cfg()
    yield create_ElasticBlastAws(cfg)


def check_ElasticBlastAws_object(eb, cfg):
    """A helper function to test initialized ElasticBlastAws object and AWS
    resources it creates.

    Arguments:
        eb: elastic_blast.aws.ElasticBlastAws object
        cfg: Config
    """
    batch_client = boto3.client('batch')

    # check that Cloudformation Stack was created
    assert len(list(eb.cf.stacks.all()))
    assert eb.cf_stack.stack_status == 'CREATE_COMPLETE'

    # get job queue name from job queu ARN
    m = re.match(r'^arn.*job-queue/(.*)$', eb.job_queue_name)
    assert m
    queue_name = m.group(1)

    # test AWS Batch Job Queue
    queues = batch_client.describe_job_queues(jobQueues=[])['jobQueues']
    assert len(queues) == 1
    queue = queues[0]
    assert queue['jobQueueName'] == queue_name
    assert queue['state'] == 'ENABLED'
    assert queue['status'] == 'VALID'
    assert len(queue['computeEnvironmentOrder']) == 1

    # test AWS Batch Compute Environment
    comp_envs = batch_client.describe_compute_environments(computeEnvironments=[])['computeEnvironments']
    assert len(comp_envs) == 1
    comp_env = comp_envs[0]
    assert comp_env['state'] == 'ENABLED'
    assert comp_env['status'] == 'VALID'

    # check that job queue points to the correct compute environment
    assert queue['computeEnvironmentOrder'][0]['computeEnvironment'] == \
        comp_env['computeEnvironmentArn']

    # check that compute environment parameters
    comp_res = comp_env['computeResources']
    assert comp_res['minvCpus'] == 0
    # FIXME: maxvCpus does not seem to be correctly set by moto
    assert comp_res['maxvCpus'] == cfg.cluster.num_nodes * aws_traits.get_machine_properties(cfg.cluster.machine_type).ncpus
    assert comp_res['instanceTypes'][0] == cfg.cluster.machine_type
    if cfg.cloud_provider.subnet is not None:
        assert comp_res['subnets'][0] == cfg.cloud_provider.subnet
    if cfg.cloud_provider.security_group is not None:
        assert comp_res['securityGroupIds'][0] == cfg.cloud_provider.security_group
    assert comp_res['instanceRole'] == cfg.cloud_provider.instance_role
    assert comp_env['serviceRole'] == cfg.cloud_provider.batch_service_role

    # FIXME: moto cloudformation does not create job definition
    # FIXME: moto cloudformation does not create launch template


@pytest.mark.skipif(True, reason='There seems to be a bug in moto library handling CloudFormation conditions')
def test_ElasticBlastAws_init_custom_vpc(cloudformation, ec2, iam, batch):
    """Test initialization of elastic_blast.aws.ElasticBlastAws with AWS resource
    creation and user-provided VPC"""

    # create VPC, subnet, and security group
    vpc = ec2.create_vpc(CidrBlock="172.16.0.0/16")
    vpc.wait_until_available()
    subnet = ec2.create_subnet(CidrBlock="172.16.0.0/24", VpcId=vpc.id)
    security_group = ec2.create_security_group(
        Description="Test security group", GroupName="sg1", VpcId=vpc.id)

    # set subnet and security group in elastic-blast config
    cfg = initialize_cfg()
    cfg.aws.subnet = subnet.id
    cfg.aws.security_group = security_group.id
    eb = create_ElasticBlastAws(cfg)
    check_ElasticBlastAws_object(eb, cfg)


@pytest.mark.skipif(True, reason='There seems to be a bug in moto library handling CloudFormation conditions')
def test_ElasticBlastAws_init_auto_vpc(ElasticBlastAws, batch):
    """Test initialization of elastic_blast.aws.ElasticBlastAws with AWS resource
    creation and auto-created VPC"""
    eb = ElasticBlastAws
    check_ElasticBlastAws_object(eb, eb.cfg)


@pytest.mark.skipif(True, reason='There seems to be a bug in moto library handling CloudFormation conditions')
def test_ElasticBlastAws_delete(ElasticBlastAws, s3, mocker):
    """Test elastic_blast.ElasticBlastAws.delete function"""

    eb = ElasticBlastAws

    # create results bucket and upload a query batch
    bucket_name, _ = parse_bucket_name_key(eb.cfg.cluster.results)
    bucket = s3.Bucket(bucket_name)
    bucket.create(ACL='public-read')
    query_batch = 'query_batches/batch_000.fa'
    bucket.put_object(ACL='public-read',
                      Body=b'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
                      Key=query_batch)

    # test that a query batch exists in the mocked S3 bucket
    assert query_batch in [s.key for s in list(bucket.objects.all())]

    # put a fake results file in the S3 bucket
    results_key = 'batch-blastn-000.out.gz'
    bucket.put_object(ACL='public-read',
                      Body=b'Some content',
                      Key=results_key)
    assert results_key in [s.key for s in list(bucket.objects.all())]

    # the mock library has holes, so we need to mock eb.cf and eb.cf_stack
    # objects ourselves
    mocker.patch.object(eb, 'cf')
    mocked_stack = mocker.patch.object(eb, 'cf_stack')

    # test ElasticBlastAws deletion
    eb.delete()

    # test thest cloudformation stack delete method was called
    assert mocked_stack.method_calls == [call.delete()]

    # test that query batch was deleted and results were not
    assert query_batch not in [s.key for s in list(bucket.objects.all())]
    assert results_key in [s.key for s in list(bucket.objects.all())]


def test_create_config_from_file(mocker):
    """Test boto3 config creation"""
    def mocked_get_machine_properties(instance_type, boto_cfg):
        """Mocked getting instance number of CPUs and memory"""
        assert instance_type == 'm5.8xlarge'
        return InstanceProperties(32, 128)

    mocker.patch('elastic_blast.elb_config.aws_get_machine_properties', side_effect=mocked_get_machine_properties)

    cfg = configparser.ConfigParser()
    cfg.read(f"{TEST_DATA_DIR}/elb-aws-blastn-pdbnt.ini")
    cfg = ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)
    assert cfg.cloud_provider.cloud == CSP.AWS
    assert cfg.blast.db_source == DBSource.AWS


@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='AWS credentials not set in TC')
def test_provide_vpc_dry_run():
    cfg = ElasticBlastConfig(aws_region='us-east-2',
                             program='blastn',
                             db='some-db',
                             results='s3://elasticblast-test',
                             queries='queries',
                             task = ElbCommand.SUBMIT)
                             

    cfg.cluster.dry_run = True
    cfg.cluster.pd_size = '1G'
    cfg.cluster.name = 'example'
    cfg.cluster.disk_type = 'gp2'
    cfg.cluster.iops = 2000
    cfg.cluster.machine_type = 't2.nano'
    cfg.cluster.num_nodes = 1
    
    # us-east-2 has default vpc, should provide it
    cfg.aws.region = 'us-east-2'
    cfg.aws.security_group = 'sg-test'
    
    b = aws.ElasticBlastAws(cfg)
    b.delete()

    # us-east-1 doesn't, should create new one
    cfg.aws.region = 'us-east-1'
    cfg.aws.security_group = 'sg-test'

    b = aws.ElasticBlastAws(cfg)
    b.delete()


class MockedCloudformationStackEvent:
    """Mocked cloudformation stack envnt"""

    def __init__(self, logical_resource_id: str = 'SomeResource',
                 resource_status: str = 'CREATE_COMPLETE',
                 resource_status_reason: str = ''):
        self.logical_resource_id = logical_resource_id
        self.resource_status = resource_status
        self.resource_status_reason = resource_status_reason


class MockedCloudformationStackEventList:
    """Mocked cloudformation object that holds a list of stack events"""

    def __init__(self, events):
        self.events = events

    def all(self):
        return self.events


class MockedCloudformationStack:
    """Mocked cloudformation stack, base class"""

    def __init__(self):
        self.events = MockedCloudformationStackEventList(list())


class MockedCloudformationStackNotCreated(MockedCloudformationStack):
    """Mocked cloudformation stack object that simulates a stack that was not
    created. Raises botocore.exceptons.ClientError when one tries to access
    any object attribute."""
    # __setattr__ is called on every atttribute binding, not only assignment

    def __setattr__(self, name, value):
        """Override set object attribute function"""
        # needs to be imported here, to avoid conflicts with moto
        from botocore.exceptions import ClientError
        # from https://stackoverflow.com/questions/37143597/mocking-boto3-s3-client-method-python
        parsed_response = {
            'Error': {'Code': '500', 'Message': 'Error Uploading'}}
        raise ClientError(parsed_response, 'DescribeStacks')


class MockedCloudformationStackWithCreateErrors(MockedCloudformationStack):
    """Mocked cloudformation stack object that simulates a stack with
    CREATE_FAILED status and errors in stack events."""

    def __init__(self):
        event_no_errors = MockedCloudformationStackEvent()
        event_with_error = MockedCloudformationStackEvent(resource_status='CREATE_FAILED', resource_status_reason='Expected error message')
        events = [event_no_errors, event_with_error]
        self.events = MockedCloudformationStackEventList(events)
        self.stack_status = 'CREATE_FAILED'


class MockedCloudformationStackWithDeleteErrors(MockedCloudformationStack):
    """Mocked cloudformation stack object that simulates a stack with
    DELETE_FAILED status and errors in stack events a delete function that
    does nothing."""

    def __init__(self):
        event_no_errors = MockedCloudformationStackEvent()
        event_with_error = MockedCloudformationStackEvent(resource_status='DELETE_FAILED', resource_status_reason='Expected error message')
        events = [event_no_errors, event_with_error]
        self.events = MockedCloudformationStackEventList(events)
        self.stack_status = 'DELETE_FAILED'

    def delete(self):
        """A delete function that does nothing"""
        pass


class MockedWaiter:
    """Mocked Waiter that raises botocore.exceptions.WaiterError whenever its
    wait function is called.
    """

    def wait(self, **kwargs):
        """Mocked wait function that always raises WaiterError"""
        from botocore.exceptions import WaiterError
        # from https://github.com/amplify-education/amplify_aws_utils/blob/master/test/unit/test_resource_helper.py
        last_response = {"Error": {"Code": "Throttling"}}
        raise WaiterError('Timeout', 'test', last_response)


class Client:
    def __init__(self):
        self.get_waiter = None


class Meta:
    def __init__(self):
        self.client = Client()


class MockedCloudformation:
    """Mocked boto3 cloudformation resource class that returns with these
    properties:
        - self.Stack returns a stack object describing a cloudformation stack
        that was not created
        - self.create_stack returns a stack that failed to create
    """

    def __init__(self):
        self.meta = Meta()
        # tested code will access these attributes
        self.meta.client.get_waiter = self.get_waiter

    def Stack(self, name):
        """Create a stack object for an AWS cloudformation stack that does
        not exist."""
        return MockedCloudformationStackNotCreated()

    def create_stack(self, **kwargs):
        """Create a new stack that fails to create and has errors"""
        return MockedCloudformationStackWithCreateErrors()

    def get_waiter(self, status):
        """Return a mocked waiter object"""
        return MockedWaiter()


def test_report_cloudformation_create_errors(batch, s3, iam, ec2, mocker):
    """Test proper reporting of cloudformation stack creation errors"""

    from elastic_blast.aws import ElasticBlastAws

    def mocked_resource(name, config):
        """Mocked boto3 resource function that creates mocked cloudformation
        resource"""
        # return the mocked object for cloudformation and regular moto objects
        # for other resources
        if name == 'cloudformation':
            return MockedCloudformation()
        elif name == 's3':
            return s3
        elif name == 'iam':
            return iam
        elif name == 'ec2':
            return ec2
        return None

    def mocked_get_machine_properties(cloud_provider, machine_type):
        """Mocked getting instance properties that always reports the same value"""
        return InstanceProperties(32, 128)

    mocker.patch('boto3.resource', side_effect=mocked_resource)
    mocker.patch('elastic_blast.elb_config.aws_get_machine_properties',
                 side_effect=mocked_get_machine_properties)

    cfg = initialize_cfg()
    with pytest.raises(UserReportError) as err:
        elb = ElasticBlastAws(cfg, create=True)

    assert err.value.returncode == DEPENDENCY_ERROR
    assert 'Cloudformation stack creation failed' in err.value.message
    assert 'Expected error message'


@pytest.mark.skipif(True, reason='There seems to be a bug in moto library handling CloudFormation conditions')
def test_report_cloudformation_delete_errors(ElasticBlastAws, mocker):
    """Test proper reporting of cloudformation stack deletion errors"""
    eb = ElasticBlastAws

    def mocked_remove_ancillary_data(direcotry):
        """Mocked elastic_blast.aws.ElasticBlastAws._remove_ancillary_data that does
        nothing"""
        pass

    # mocked cloudformation and stack objects
    mocked_cf = MockedCloudformation()
    mocked_stack = MockedCloudformationStackWithDeleteErrors()

    mocker.patch.object(eb, 'cf', mocked_cf)
    mocker.patch.object(eb, 'cf_stack', mocked_stack)
    # this is mocked so that we do not need put fake query_batch file in fake S3
    mocker.patch('elastic_blast.aws.ElasticBlastAws._remove_ancillary_data',
                 side_effect=mocked_remove_ancillary_data)

    with pytest.raises(UserReportError) as err:
        eb.delete()

    assert err.value.returncode == DEPENDENCY_ERROR
    assert 'Cloudformation stack deletion failed' in err.value.message
    assert 'Expected error message'


@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='AWS credentials not set in TC')
def test_incorrect_user_db():
    cfg = configparser.ConfigParser()
    cfg.read(f"{TEST_CONFIG_DATA_DIR}/aws-wrong-custom-db.ini")
    cfg = ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)
    cfg.cluster.machine_type = 't2.micro'
    try:
        with pytest.raises(UserReportError) as exc_info:
            b = aws.ElasticBlastAws(cfg, create=True)
    finally:
        # In case the test fails and cluster is created, clean up the cluster
        b = aws.ElasticBlastAws(cfg)
        b.delete()
    assert(exc_info.value.returncode == BLASTDB_ERROR)
    assert('is not a valid BLAST database' in exc_info.value.message)


@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='AWS credentials not set in TC')
def test_wrong_provider_user_db():
    cfg = configparser.ConfigParser()
    cfg.read(f"{TEST_CONFIG_DATA_DIR}/aws-wrong-provider-custom-db.ini")
    cfg = ElasticBlastConfig(cfg, task = ElbCommand.SUBMIT)
    cfg.cluster.machine_type = 't2.micro'
    try:
        with pytest.raises(UserReportError) as exc_info:
            b = aws.ElasticBlastAws(cfg, create=True)
    finally:
        # In case the test fails and cluster is created, clean up the cluster
        b = aws.ElasticBlastAws(cfg)
        b.delete()
    assert(exc_info.value.returncode == BLASTDB_ERROR)
    assert('User database should be in the AWS S3 bucket' in exc_info.value.message)
