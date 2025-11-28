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
Unit tests for run summary command

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""

import os
import subprocess
import pytest

TEST_DIR = os.path.join(os.path.dirname(__file__), 'data')
TEST_LOGS = 'aws-output-sample-aggregate.log'
TEST_SUMMARY = 'run_summary_sample.json'
TEST_FAILED_LOGS = 'aws-output-sample-failed-aggregate.log'
TEST_FAILED_SUMMARY = 'run_summary_sample_failed.json'
TEST_CASES = [
    (TEST_LOGS, TEST_SUMMARY),
    (TEST_FAILED_LOGS, TEST_FAILED_SUMMARY)
]

@pytest.mark.skipif(os.getenv('TEAMCITY_VERSION') is not None, reason='AWS credentials not set in TC')
def test_from_logs():
    for logs, summary in TEST_CASES:
        proc = subprocess.run([
            'elastic-blast', 'run-summary', '--read-logs', os.path.join(TEST_DIR, logs)
        ], capture_output=True)
        assert proc.stderr.decode() == ''
        output = proc.stdout.decode()
        with open(os.path.join(TEST_DIR, summary)) as f:
            sample = f.read()
        assert output == sample
        assert proc.returncode == 0
