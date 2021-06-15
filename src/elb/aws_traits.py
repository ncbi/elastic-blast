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
elb/aws_traits.py - helper module for AWS machine info

"""

from botocore.config import Config  # type: ignore
import boto3 # type: ignore
from botocore.exceptions import ClientError, NoCredentialsError # type: ignore
import logging
from typing import Optional, List
from .util import UserReportError, validate_aws_region
from .base import InstanceProperties
from .constants import ELB_DFLT_AWS_REGION, INPUT_ERROR, PERMISSIONS_ERROR


def create_aws_config(region: Optional[str] = None) -> Config:
    """Create boto3 config object using application config parameters"""
    retval = None
    if region:
        retval = Config(region_name=region)
    else:
        retval = Config(region_name=ELB_DFLT_AWS_REGION)
    return retval


def get_availability_zones_for(region: str) -> List[str]:
    """ Get a list of availability zones for the given region """
    validate_aws_region(region)
    ec2 = boto3.client('ec2', region_name=region)
    try:
        response = ec2.describe_availability_zones(Filters=[{'Name':'region-name', 'Values': [region]}])
        return [r['ZoneName'] for r in response['AvailabilityZones']]
    except ClientError as err:
        logging.debug(err)
    return []


def get_machine_properties(instance_type: str, boto_cfg: Config = None) -> InstanceProperties:
    """ Get the number of vCPUs and memory in GB for a given instance type
    instance_type: name of the AWS EC2 instance type
    boto_cfg: boto3 library configuration

    Raises botocore.exceptions.ClientError if the instance type is invalid
    """
    if instance_type.lower() == 'optimal':
        raise ValueError('optimal instance type is not supported in get_machine_properties')
    ec2 = boto3.client('ec2') if boto_cfg == None else boto3.client('ec2', config=boto_cfg)
    try:
        rv = ec2.describe_instance_types(InstanceTypes=[instance_type])
        ncpus = int(rv['InstanceTypes'][0]['VCpuInfo']['DefaultVCpus'])
        nram = int(rv['InstanceTypes'][0]['MemoryInfo']['SizeInMiB']) / 1024
    except ClientError as err:
        logging.debug(err)
        raise UserReportError(returncode=INPUT_ERROR, message=f'Invalid AWS machine type "{instance_type}"')
    except NoCredentialsError as err:
        logging.debug(err)
        raise UserReportError(returncode=PERMISSIONS_ERROR, message=str(err))
    return InstanceProperties(ncpus, nram)
