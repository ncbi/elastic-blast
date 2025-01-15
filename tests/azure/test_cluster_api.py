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

from elastic_blast.gcp import check_cluster, start_cluster, delete_cluster
import time
import os
import pytest
import configparser

TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


@pytest.fixture(scope="module")
def get_cluster_name():
    str_current_time = str(int(time.time()))
    uniq_cluster_name = "pytest-"+str_current_time
    if 'USER' in os.environ:
        uniq_cluster_name = uniq_cluster_name + "-" + os.environ['USER']
    else:
        uniq_cluster_name = uniq_cluster_name + "-" + str(os.getpid())

    if 'HOST' in os.environ:
        uniq_cluster_name = uniq_cluster_name + "-" + os.environ['HOST']
    else:
        uniq_cluster_name = uniq_cluster_name + "-" + str(os.getpid())

    return uniq_cluster_name

# FIXME: https://jira.ncbi.nlm.nih.gov/browse/EB-217


@pytest.mark.skip(reason="The logic in these tests assumes ordering of tests, leaks resources")
def test_start_cluster(get_cluster_name):
    cluster_name = get_cluster_name
    cfg = configparser.ConfigParser()
    cfg.read(f"{TEST_DATA_DIR}/test-cfg-file.ini")
    # override name to allow simulteniouse runs
    cfg[CFG_CLUSTER][CFG_CLUSTER_NAME] = cluster_name
    created_name = start_cluster(cfg)
    assert cluster_name == created_name


@pytest.mark.skip(reason="The logic in these tests assumes ordering of tests, leaks resources")
def test_cluster_presense(get_cluster_name):
    cluster_name = get_cluster_name
    cfg = configparser.ConfigParser()
    cfg.read(f"{TEST_DATA_DIR}/test-cfg-file.ini")
    cfg[CFG_CLUSTER][CFG_CLUSTER_NAME] = cluster_name
    status = check_cluster(cfg)
    assert status == 'RUNNING'


@pytest.mark.skip(reason="The logic in these tests assumes ordering of tests, leaks resources")
def test_delete_cluster(get_cluster_name):
    cluster_name = get_cluster_name
    cfg = configparser.ConfigParser()
    cfg.read(f"{TEST_DATA_DIR}/test-cfg-file.ini")
    cfg[CFG_CLUSTER][CFG_CLUSTER_NAME] = cluster_name
    deleted_name = delete_cluster(cfg)
    assert deleted_name == cluster_name


@pytest.mark.skip(reason="The logic in these tests assumes ordering of tests, leaks resources")
def test_cluster_deletion(get_cluster_name):
    cluster_name = get_cluster_name
    cfg = configparser.ConfigParser()
    cfg.read(f"{TEST_DATA_DIR}/test-cfg-file.ini")
    cfg[CFG_CLUSTER][CFG_CLUSTER_NAME] = cluster_name
    status = check_cluster(cfg)
    assert status == ''
