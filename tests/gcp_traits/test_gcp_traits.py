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
Test for elastic_blast.gcp_traits

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""
from elastic_blast.gcp_traits import get_machine_properties
from elastic_blast.base import InstanceProperties
import pytest

def test_ram():
    assert get_machine_properties('n1-standard-32') == InstanceProperties(32, 120)

def test_unsupported_instance_type_optimal():
    with pytest.raises(NotImplementedError):
        get_machine_properties('optimal')

def test_not_found():
    with pytest.raises(KeyError):
        get_machine_properties('n1-nonstandard-32')
