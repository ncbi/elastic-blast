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

#
# test_jobs.py - unit test for elastic_blast.jobs module
#
# Author: Victor Joukov joukovv@ncbi.nlm.nih.gov


import os
from elastic_blast.jobs import read_job_template, write_job_files
from tempfile import TemporaryDirectory
import pytest  # type: ignore


@pytest.fixture
def test_dir():
    with TemporaryDirectory() as tempdir:
        yield tempdir

def test_jobs(test_dir):
    query_path = 'gs://test-bucket'
    results = 'gs://results-bucket/results_path'
    query_num = '046'
    query = f'batch_{query_num}'
    batch_file = os.path.join(query_path, query+'.fa')
    template = """\
$QUERY_NUM
${QUERY}
$QUERY_PATH/some_file
${RESULTS}/results.aln
$SOME_UNDEFINED_VARIABLE"""
    map_obj = {
        'RESULTS' : results
    }
    expected = f"""\
{query_num}
{query}
{query_path}/some_file
{results}/results.aln
$SOME_UNDEFINED_VARIABLE"""
    jobs = write_job_files(test_dir, 'job_', template, [batch_file], **map_obj)
    print(jobs)
    with open(jobs[0]) as f:
        job_text = f.read()
        assert job_text == expected


def test_default_template():
    job_template = read_job_template()
    assert type(job_template) == str
    assert job_template.find("${ELB_BLAST_PROGRAM}") >= 0


def test_missing_template():
    with pytest.raises(FileNotFoundError):
        read_job_template('some_wild_and_non_existing_name.template')
