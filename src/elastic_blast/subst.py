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
Module elastic_blast.subst - substitute variables of form ${VAR_NAME} from either parameters or environment

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""
import re

re_sub = re.compile(r'\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))')
def substitute_params(job_template: str, map_obj) -> str:
    """ Substitute variables ${QUERY}, ${QUERY_PATH}, ... ${RESULTS} with
    actual values to form a valid YAML job file.
    Also substitute variables from OS environment

    Params:

    job_template: text to substitute variables in
    map_obj: object with get method to use for substitutions

    Returns: text with substitutions
    """
    def _subs_var(mo):
        v = ''
        if mo.group(1):
            v = mo.group(1)
        else:
            v = mo.group(2)
        return map_obj.get(v, mo.group(0))
    return re_sub.sub(_subs_var, job_template)

