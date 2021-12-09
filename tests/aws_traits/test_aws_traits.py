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
Test for elastic_blast.aws_traits

Author: Greg Boratyn boratyng@ncbi.nlm.nih.gov
"""
import os
from elastic_blast.aws_traits import get_machine_properties, create_aws_config, get_availability_zones_for
from elastic_blast.aws_traits import get_regions
from elastic_blast.base import InstanceProperties
from elastic_blast.util import UserReportError
from elastic_blast.constants import INPUT_ERROR, ELB_DFLT_AWS_REGION
import pytest


def test_create_config():
    """Test boto3 config creation"""
    config = create_aws_config('some-region')
    assert config
    assert config.region_name == 'some-region'


def test_create_default_config():
    """Test boto3 config creation"""
    config = create_aws_config()
    assert config
    assert config.region_name == ELB_DFLT_AWS_REGION


@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='AWS credentials not set in TC')
def test_get_regions():
    regions = get_regions()
    assert len(regions)
    assert 'us-east-1' in regions
    assert 'eu-north-1' in regions
    assert 'us-east1' not in regions
    assert 'us-east4' not in regions
    assert 'dummy' not in regions


@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='AWS credentials not set in TC')
def test_machine_properties():
    props = get_machine_properties('m4.10xlarge')
    assert props == InstanceProperties(ncpus=40, memory=160)
    with pytest.raises(UserReportError) as err:
        props = get_machine_properties('dummy')
    assert err.value.returncode == INPUT_ERROR
    assert 'Invalid AWS machine type' in err.value.message

def test_machine_properties_optimal():
    with pytest.raises(ValueError) as err:
        props = get_machine_properties('optimal')
    assert 'optimal instance type is not supported' in str(err)

@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='AWS credentials not set in TC')
def test_get_azs_us_east_1():
    azs = get_availability_zones_for('us-east-1')
    assert 6 == len(azs)


@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='AWS credentials not set in TC')
def test_get_azs_us_east_2():
    azs = get_availability_zones_for('us-east-2')
    assert 3 == len(azs)


@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='AWS credentials not set in TC')
def test_get_azs_us_west_1():
    azs = get_availability_zones_for('us-west-1')
    assert 2 == len(azs)


@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='AWS credentials not set in TC')
def test_get_azs_us_west_2():
    azs = get_availability_zones_for('us-west-2')
    assert 4 == len(azs)


@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='AWS credentials not set in TC')
def test_get_azs_invalid_region():
    with pytest.raises(ValueError) as err:
        azs = get_availability_zones_for('this-region-does-not-exist!')
