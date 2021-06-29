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

# Unit and application tests

import pytest  # type: ignore
import os, subprocess, io
from elastic_blast.cost import get_cost, DFLT_BQ_DATASET, DFLT_BQ_TABLE, BQ_ERROR, NO_RESULTS_ERROR, CMD_ARGS_ERROR

#TEST_CMD = 'python3 elb-cost.py'
TEST_CMD = 'elb-cost.py'

# A few test require specific GCP credentials and are skipped. Set environment
# variable RUN_ALL_COST_TESTS to run all tests.
SKIP = not os.getenv('RUN_ALL_TESTS')

@pytest.mark.skipif(SKIP, reason='This test requires specific GCP credentials to access a BigQuery dataset and table. It will only work for users with these credentials.')
def test_get_cost():
    """Basic test for getting costs"""
    result = get_cost('exp:2mins', date_range='2020-01-09:2020-01-10')
    print(result)
    assert len(result) > 0

def test_get_cost_bad_label():
    """Test that get_cost function throws ValueError for inapropriattly
    formatted label."""
    with pytest.raises(ValueError):
        get_cost('aaa')
    
def test_get_cost_bad_date_range():
    """Test that get_cost function throws ValueError for inapropriattly
    formatted date range."""
    with pytest.raises(ValueError):
        get_cost('aaa:bb', date_range = 'abc')

def test_get_cost_bigquery_error():
    """Test that get_cost function throws RuntimeError for BigQuery failure"""
    with pytest.raises(RuntimeError):
        get_cost('aaa:bb', dataset = 'aaa')

@pytest.mark.skipif(SKIP, reason='This test requires specific GCP credentials to access a BigQuery dataset and table. It will only work for users with these credentials.')
def test_app():
    """Simple application test"""
    cmd = TEST_CMD + ' exp:2mins --date-range 2020-01-09:2020-01-10'
    p = subprocess.run(cmd.split(), stdout=subprocess.PIPE)
    assert p.returncode == 0
    with io.BytesIO(p.stdout) as f:
        out = f.readlines()
        assert len(out) == 1
        assert out[0].decode().rstrip() == '$2.49', 'Unexpected cost output'
        
@pytest.mark.skipif(SKIP, reason='This test requires specific GCP credentials to access a BigQuery dataset and table. It will only work for users with these credentials.')
def test_app_no_results_for_label():
    """Test if the application returns the appropriate error code and an error
    message if no cost record for a label was found"""
    cmd = TEST_CMD + ' some_label:that_hopefully_does_not_exist --date-range 2020-01-09:2020-01-10'
    p = subprocess.run(cmd.split(), stderr=subprocess.PIPE)
    assert p.returncode == NO_RESULTS_ERROR
    with io.BytesIO(p.stderr) as f:
        assert len(f.readlines()) > 0, 'Application error message is missing'
    
def test_app_bq_error():
    """Test if the application returns the appropriate error code and an error
    message if BigQuery dataset could not be foun"""
    cmd = TEST_CMD + ' --dataset aa aaa:bbb --date-range 2020-01-09:2020-01-10'
    p = subprocess.run(cmd.split(), stderr=subprocess.PIPE)
    assert p.returncode == BQ_ERROR
    with io.BytesIO(p.stderr) as f:
        assert len(f.readlines()) > 0, 'Application error message is missing'

def test_app_label_format_error():
    """Test if the application returns the appropriate error code and an error
    message if run label was formatted incorrectly"""
    cmd = TEST_CMD + ' aaa --date-range 2020-01-09:2020-01-10'
    p = subprocess.run(cmd.split(), stderr=subprocess.PIPE)
    assert p.returncode == CMD_ARGS_ERROR
    with io.BytesIO(p.stderr) as f:
        assert len(f.readlines()) > 0, 'Application error message is missing'

def test_app_date_format_error():
    """Test if the application returns the appropriate error code and an error
    message if date range was formatted incorrectly"""
    cmd = TEST_CMD + ' aaa:bb --date-range 2020-01-09:2020-01-xx'
    p = subprocess.run(cmd.split(), stderr=subprocess.PIPE)
    assert p.returncode == CMD_ARGS_ERROR
    with io.BytesIO(p.stderr) as f:
        assert len(f.readlines()) > 0, 'Application error message is missing'
