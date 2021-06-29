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
test_status.py - unit test for status.py module

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""

import os, stat, subprocess, tempfile
from collections import defaultdict
from elastic_blast import kubernetes
from elastic_blast.status import get_status
from tests.utils import gke_mock
from tests.utils import K8S_JOB_STATUS


def test_status(gke_mock):
    "Using mock kubectl run our actual test"
    status = get_status(None)

    counter = defaultdict(int)
    for i in K8S_JOB_STATUS:
        counter[i] += 1
    
    assert status == (counter['Pending'], counter['Running'],
                      counter['Succeeded'], counter['Failed'])


def test_invalid_label():
    "Supply invalid label and should get an exception"
    try:
        status = get_status('incorrect_label')
    except ValueError as e:
        pass
    else:
        assert False
