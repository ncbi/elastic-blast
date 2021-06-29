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
test_subst.py - unit test for elastic_blast.subst module

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""

from elastic_blast.subst import substitute_params

def test_subst():
    query_num = '046'
    query_path = 'gs://example-bucket/some_path'
    map_obj = {
        'QUERY_NUM' : query_num,
        'QUERY_PATH' : query_path,
    }
    text = """\
${QUERY_NUM}$QUERY_NUM
${QUERY_PATH}
${SOME_NON_EXISTING_VARIABLE}"""
    ref_text = f"""\
{query_num}{query_num}
{query_path}
${{SOME_NON_EXISTING_VARIABLE}}"""
    sub_text = substitute_params(text, map_obj)
    assert sub_text == ref_text