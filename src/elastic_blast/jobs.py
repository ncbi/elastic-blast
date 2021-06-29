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
Module elastic_blast.jobs

Generate Kubernetes job YAML files from template

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""

import os
import re
from typing import List
from pkg_resources import resource_string

from .filehelper import open_for_read, open_for_write
from .subst import substitute_params
from .constants import ELB_DFLT_BLAST_JOB_TEMPLATE, ELB_LOCAL_SSD_BLAST_JOB_TEMPLATE
from .elb_config import ElasticBlastConfig

def read_job_template(template_name=ELB_DFLT_BLAST_JOB_TEMPLATE, cfg: ElasticBlastConfig = None):
    """ Read job template file or resource
    Parameters:
        template_name - name of file to read or default resource
    Returns:
        string with job template text
    """
    if cfg and cfg.cluster.use_local_ssd:
        template_name = ELB_LOCAL_SSD_BLAST_JOB_TEMPLATE
    resource_prefix = 'resource:'
    resource_prefix_len = len(resource_prefix)
    if template_name[:resource_prefix_len] == resource_prefix:
        template_name = template_name[resource_prefix_len:]
        return resource_string('elastic_blast', template_name).decode()
    with open_for_read(template_name) as f:
        return f.read()


re_batch_num = re.compile(r'[^0-9]+([0-9]{3,})')


def _write_job_file(job_path, job_prefix, job_template, query_fqn, njob, **subs):
    """ Write YAML job file from template making substitutions
        internal function
    Parameters:
        job_path: path to which write job files
        job_prefix: name prefix for job file
        job_template: string with contents of job file with variables to substitute
        query_fqn: fully qualified name of query file
        njob: ordinal number of a job
        subs: other substitution variables
    Result:
        Job file name
    """
    if not job_template:
        return None
    job_file_name = os.path.join(job_path, f'{job_prefix}{njob:03d}.yaml')
    query_path = os.path.dirname(query_fqn)
    query = os.path.splitext(os.path.basename(query_fqn))[0]
    # Try to recover batch number from file name, if not available use njob
    mo = re_batch_num.match(query)
    if mo:
        query_num = mo.group(1)
    else:
        query_num = f'{njob:03d}'

    map_obj = {}
    for k, v in subs.items():
        map_obj[k] = v
    map_obj['QUERY'] = query
    map_obj['QUERY_FQN'] = query_fqn
    map_obj['QUERY_PATH'] = query_path
    map_obj['QUERY_NUM'] = query_num
    map_obj['JOB_NUM'] = query_num

    s = substitute_params(job_template, map_obj)
    with open_for_write(job_file_name) as f:
        f.write(s)
    return job_file_name


def write_job_files(job_path: str, job_prefix: str, job_template: str, queries: List[str], **subs):
    """ Write YAML job files from template making substitutions
    Parameters:
        job_path: path to which write job files
        job_prefix: name prefix for job file
        job_template: string with contents of job file with variables to substitute
        queries: list of query file names to substitute in job files
        subs: other substitution variables
    Result:
        List of job file names
    """
    if not job_template:
        return []
    jobs = []
    for njob, query in enumerate(queries):
        subs['BLAST_ELB_BATCH_NUM'] = str(njob)
        job = _write_job_file(job_path, job_prefix,
                              job_template, query, njob, **subs)
        jobs.append(job)
    return jobs
