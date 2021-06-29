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
Unit tests for split module

"""

import os
from io import StringIO
import tempfile
import shutil
import hashlib
from elastic_blast import split
import pytest


@pytest.fixture
def tmpdir():
    """Fixture that creates a temporary directory and deletes it after a test"""
    name = tempfile.mkdtemp()
    yield name
    shutil.rmtree(name)


def test_FASTAReader_multi_file(tmpdir):
    """Test FASTAReader with multiple files, ensure continuity in a batch."""
    fasta1 =""">seq1
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC
>seq2
TTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTTT
GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG"""

    fasta2 = """>some_id
AACTCTCTCTCTCTCTCTCTCTTCTCTTCTCTCTCTCTCTCTCTCTCTC
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"""


    # run FASTA reader on two input streams with batch size larger than
    # sum of both strings
    with StringIO(fasta1) as f1, StringIO(fasta2) as f2:
        reader = split.FASTAReader([f1, f2], len(fasta1) + len(fasta2) + 1,
                                   tmpdir)
        reader.read_and_cut()
        assert len(reader.queries) == 1

    # read resulting batch
    with open(os.path.join(tmpdir, 'batch_000.fa')) as f:
        batch = f.readlines()

    # check that batch has the same content as fasta1 and fasta2 combined
    assert hashlib.sha256('\n'.join([fasta1, fasta2, '']).encode()).hexdigest() == \
           hashlib.sha256(''.join(batch).encode()).hexdigest()
        
