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
Tests for taxonomy filtering implemented in elb/taxonomy.py

Author: Greg Boratyn (boratyng@ncbi.nlm.nih.gov)
"""

import configparser
import re
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError
import time
from unittest.mock import MagicMock, patch

from elastic_blast import taxonomy
from elastic_blast import constants
from elastic_blast import filehelper
from elastic_blast.util import UserReportError
from elastic_blast.constants import ELB_QUERY_BATCH_DIR, ELB_TAXIDLIST_FILE
from elastic_blast.constants import ElbCommand
from elastic_blast.elb_config import ElasticBlastConfig
from elastic_blast.base import InstanceProperties
from tests.utils import gke_mock

import pytest


# input and output taxids for tests
input_taxids = [9605, 9608]
expected_taxids = [9605, 9606, 63221, 741158, 1425170, 2665952, 2665953,
                   9608, 9611, 9612, 9614, 9615, 9616, 9619, 9620, 9621, 9622, 9623, 9624, 9625, 9626, 9627, 9629, 9630, 9631, 30540, 32534, 34879, 34880, 45781, 55039, 55040, 68721, 68722, 68723, 68724, 68725, 68727, 68728, 68729, 68730, 68732, 68734, 68736, 68737, 68739, 68740, 68741, 69045, 71547, 132609, 143281, 188536, 192959, 228401, 242524, 242525, 244585, 246881, 246882, 286419, 354189, 354190, 354191, 383736, 425200, 425201, 425934, 443256, 476259, 476260, 494514, 554455, 561074, 613187, 644627, 659069, 673762, 676787, 945042, 990119, 1002243, 1002244, 1002254, 1002255, 1224817, 1295334, 1303779, 1316008, 1316009, 1320375, 1341016, 1353242, 1398410, 1419108, 1419257, 1419712, 1605264, 1621113, 1621114, 1621115, 1621116, 1621117, 1621118, 1707807, 1785177, 2494276, 2562269, 2605939, 2626217, 2627721, 2639686, 2658581, 2714668, 2714669, 2714670, 2714671, 2714672, 2714673, 2714674, 2714675, 2726995, 2726996, 2769327, 2769328, 2769329, 2793302, 2793303, 2841919, 2841920, 2841921, 2841922, 2841923]

@pytest.fixture()
def wait(mocker):
    """Fixture that delays taxonomy.entrez_query call by 1 second to avoid
    filling E-utils request quota (3 requests per second) """

    orig_entrez_query = taxonomy.entrez_query
    def mocked_entrez_query(tool, query):
        """Mocked elastic_blast.taxonomy.entrez_query: waits 1 second and calls the
        original function"""
        time.sleep(1)
        return orig_entrez_query(tool, query)

    mocker.patch('elastic_blast.taxonomy.entrez_query', side_effect=mocked_entrez_query)
    yield
    

@pytest.fixture
def mocked_get_machine_properties(mocker):
    """Fixture that proviedes mocked get_machine_properties function so that
    AWS credentials and real AWS regions are not needed for the tests"""
    def fun_mocked_get_machine_properties(instance_type, boto_cfg=None):
        """Mocked getting instance number of CPUs and memory"""
        return InstanceProperties(32, 128)

    mocker.patch('elastic_blast.elb_config.aws_get_machine_properties', side_effect=fun_mocked_get_machine_properties)
    mocker.patch('elastic_blast.tuner.aws_get_machine_properties', side_effect=fun_mocked_get_machine_properties)


@pytest.fixture
def cfg(mocked_get_machine_properties, gke_mock):
    """Create an ElasticBlastConfig object"""
    cfg = ElasticBlastConfig(aws_region = 'test-region',
                             program = 'blastn',
                             db = 'testdb',
                             queries = 'test-queries.fa',
                             results = 's3://test-results',
                             task = ElbCommand.SUBMIT)
    yield cfg


def test_get_user_taxids():
    """Test extracting user-provided taxids from blast options"""
    expected_taxids = [5, 6]

    # test config without taxonomy filtering
    assert len(taxonomy.get_user_taxids('')) == 0
    assert len(taxonomy.get_user_taxids('-evalue 0.1 -outfmt 6')) == 0

    # test config with -taxids blast command line option
    user_taxids = taxonomy.get_user_taxids(f'-evalue 0.1 -taxids {",".join([str(i) for i in expected_taxids])}')
    assert sorted(user_taxids) == sorted(expected_taxids)

    # test config with -taxidlist blast command line option
    user_taxids = None
    with NamedTemporaryFile() as ftax:
        for i in expected_taxids:
            # write taxid list to a file
            ftax.write(str(i).encode())
            ftax.write(b'\n')
        ftax.flush()
        ftax.seek(0)
        user_taxids = taxonomy.get_user_taxids(f'-evalue 0.1 -taxidlist {ftax.name}')
    assert sorted(user_taxids) == sorted(expected_taxids)


def test_get_user_taxids_errors():
    """Test that incorrect taxids are properly reported"""
    
    # both -taxids and -taxidlist options are given
    with pytest.raises(UserReportError) as err:
        taxonomy.get_user_taxids('-taxids 1,2,3 -taxidlist some-file')
    assert err.value.returncode == constants.INPUT_ERROR
    assert '-taxids, -taxidlist, -negative_taxids, and -negative_taxidlist options are mutually exclusive' in err.value.message

    # no taxidlist file
    with pytest.raises(UserReportError) as err:
        taxonomy.get_user_taxids('-outfmt 6 -taxidlist')
    assert err.value.returncode == constants.INPUT_ERROR
    assert 'taxonomy id list file is missing' in err.value.message

    # not a number -taxids
    with pytest.raises(UserReportError) as err:
        taxonomy.get_user_taxids('-outfmt 6 -taxids 1,2,a,4')
    assert err.value.returncode == constants.INPUT_ERROR
    assert 'incorrect taxonomy id' in err.value.message

    # not a number -taxidlist
    with NamedTemporaryFile() as ftax:
        for i in '1,2,a,4'.split(','):
            # write taxid list to a file
            ftax.write(i.encode())
            ftax.write(b'\n')
        ftax.flush()
        ftax.seek(0)
        with pytest.raises(UserReportError) as err:
            taxonomy.get_user_taxids(f'-evalue 0.1 -taxidlist {ftax.name}')
        assert err.value.returncode == constants.INPUT_ERROR
        assert 'incorrect taxonomy id' in err.value.message

    # not taxids -taxids
    with pytest.raises(UserReportError) as err:
        taxonomy.get_user_taxids('-taxids')
    assert err.value.returncode == constants.INPUT_ERROR
    assert 'No taxonomy ids found' in err.value.message

    # not taxids -taxidlist
    with NamedTemporaryFile() as f:
        with pytest.raises(UserReportError) as err:
            taxonomy.get_user_taxids(f'-taxidlist {f.name}')
        assert err.value.returncode == constants.INPUT_ERROR
        assert 'No taxonomy ids found' in err.value.message

    # missing taxidlist file
    with pytest.raises(UserReportError) as err:
        taxonomy.get_user_taxids('-taxidlist missing-file')
    assert err.value.returncode == constants.INPUT_ERROR
    assert 'missing-file' in err.value.message
    assert 'not found' in err.value.message


def test_get_species_taxids(wait):
    """Test translating higher level taxids into species level ones"""
    species_taxids = taxonomy.get_species_taxids(input_taxids)
    error_message = f"The taxonomy IDs returned has changed: actual {len(species_taxids)}, expected {len(expected_taxids)}"
    assert sorted(species_taxids) == sorted(expected_taxids), error_message


def test_setup_taxid_filtering_taxids(wait, cfg):
    """Test preparing taxidlist file and blast options for taxid filtering
    -taxids option"""
    # set up blast command line options
    cfg.blast.options = f'-taxids {",".join([str(i) for i in input_taxids])}'

    taxonomy.setup_taxid_filtering(cfg)
    assert '-taxids' not in cfg.blast.options
    assert '-taxidlist' in cfg.blast.options

    matches = re.findall(r'-taxidlist\s+(\S+)', cfg.blast.options)
    assert len(matches) == 1
    assert matches[0] == ELB_TAXIDLIST_FILE
    key = '/'.join([cfg.cluster.results, ELB_QUERY_BATCH_DIR])
    filename = '/'.join([filehelper.bucket_temp_dirs[key], matches[0]])
    with open(filename) as f:
        taxids = [int(i.rstrip()) for i in f.readlines()]
    assert taxids == sorted(expected_taxids)


def test_setup_taxid_filtering_negative_taxids(wait, cfg):
    """Test preparing taxidlist file and blast options for taxid filtering
    -negative_taxids option"""
    # set up blast command line options
    cfg.blast.options = f'-negative_taxids {",".join([str(i) for i in input_taxids])}'

    taxonomy.setup_taxid_filtering(cfg)
    assert '-negative_taxids' not in cfg.blast.options
    assert '-negative_taxidlist' in cfg.blast.options

    matches = re.findall(r'-negative_taxidlist\s+(\S+)', cfg.blast.options)
    assert len(matches) == 1
    assert matches[0] == ELB_TAXIDLIST_FILE
    key = '/'.join([cfg.cluster.results, ELB_QUERY_BATCH_DIR])
    filename = '/'.join([filehelper.bucket_temp_dirs[key], matches[0]])
    with open(filename) as f:
        taxids = [int(i.rstrip()) for i in f.readlines()]
    assert taxids == sorted(expected_taxids)


def test_setup_taxid_filtering_taxidlist(wait, cfg):
    """Test preparing taxidlist file and blast options for taxid filtering
    -taxidlist option"""

    # set up input taxidlist
    with NamedTemporaryFile() as fin:
        for i in input_taxids:
            fin.write(str(i).encode())
            fin.write(b'\n')
        fin.flush()
        fin.seek(0)
        
        cfg.blast.options = f'-taxidlist {fin.name}'
        taxonomy.setup_taxid_filtering(cfg)
        assert '-taxids' not in cfg.blast.options
        assert fin.name not in cfg.blast.options
        assert '-taxidlist' in cfg.blast.options

    matches = re.findall(r'-taxidlist\s+(\S+)', cfg.blast.options)
    assert len(matches) == 1
    assert matches[0] == ELB_TAXIDLIST_FILE
    key = '/'.join([cfg.cluster.results, ELB_QUERY_BATCH_DIR])
    filename = '/'.join([filehelper.bucket_temp_dirs[key], matches[0]])
    with open(filename) as f:
        taxids = [int(i.rstrip()) for i in f.readlines()]
    assert taxids == sorted(expected_taxids)


def test_non_existent_taxid(wait, cfg):
    """Test setting up taxonomy filtering with a non-existent taxid"""
    cfg.blast.options = '-taxids 99999999999,9606'

    with pytest.raises(UserReportError) as err:
        taxonomy.setup_taxid_filtering(cfg)
    assert err.value.returncode == constants.INPUT_ERROR
    assert 'is not a valid taxonomy id' in err.value.message


def test_entrez_query_retries():
    """Test that entrez_query is retried only on HTTPError and the last
    exception is reraised"""
    with pytest.raises(HTTPError):
        # request to a non-existing cgi
        taxonomy.entrez_query('bad-tool', {})
    assert taxonomy.entrez_query.retry.statistics['attempt_number'] >= 3
    assert taxonomy.entrez_query.retry.statistics['idle_for'] > 1

    with pytest.raises(TypeError):
        # passing int as the tool parameter invokes TypeError
        # this test may not work if taxonomy.entrez_query implementation
        # changes
        taxonomy.entrez_query(123, {})
    assert taxonomy.entrez_query.retry.statistics['attempt_number'] == 1
 
