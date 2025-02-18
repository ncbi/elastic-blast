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
test_status.py - unit test for ElasticBlastGcp check_status method

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""

import os
from argparse import Namespace
from elastic_blast.config import configure
from elastic_blast.elb_config import ElasticBlastConfig

from elastic_blast.azure import ElasticBlastAzure
from elastic_blast.constants import ElbCommand, ElbStatus
from tests.utils import gke_mock

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
INI = os.path.join(DATA_DIR, 'status-test-azure.ini')

def test_status():
    "Using mock kubectl run our actual test"
    args = Namespace(cfg=INI)
    cfg = ElasticBlastConfig(configure(args), task = ElbCommand.STATUS)
    cfg.cluster.name = cfg.cluster.name + f'-{os.environ["USER"]}' + '-27'
    elastic_blast =  ElasticBlastAzure(cfg)
    status, counters, _ = elastic_blast.check_status()
    assert status == ElbStatus.FAILURE
    assert counters ==  {'failed': 1, 'succeeded': 1, 'pending': 1, 'running': 1}
