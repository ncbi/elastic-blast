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
Module status

Reads status of job execution and reports it

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""
import logging
from collections import defaultdict
import re
from . import kubernetes
from .util import safe_exec, SafeExecError, UserReportError
from .constants import CLUSTER_ERROR

#TODO: get rid of unused run_label, EB-407 
def get_status(run_label=None, dry_run=False):
    """Return numbers of pending, running, succeded, and failed jobs

    run_label: optional argument
        If argument run_label is set it is added to pod selector for kubectl request.
    """
    status = defaultdict(int)
    selector = 'app=blast'
    # If run_label is set add it to selector
    if run_label:
        # FIXME: EB-132 will need to distinguish this from the the run-label used for cost tracking
        kv = run_label.split(':')
        if len(kv) == 2 and kv[0] and kv[1]:
            selector += f',{kv[0]}={kv[2]}'
        else:
            raise ValueError('Run label not in correct format, must be: <key>:<value>')
    # if we need name of the job in the future add NAME:.metadata.name to custom-columns
    kubectl = 'kubectl'

    # get status of jobs (pending/running, succeeded, failed)
    cmd = f'{kubectl} get jobs -o custom-columns=STATUS:.status.conditions[0].type -l {selector}'.split()
    if dry_run:
        logging.debug(cmd)
    else:
        try:
            proc = safe_exec(cmd)
        except SafeExecError as err:
            raise UserReportError(CLUSTER_ERROR, err.message.strip())

        for line in proc.stdout.decode().split('\n'):
            if not line or line.startswith('STATUS'):
                continue
            if line.startswith('Complete'):
                status['Succeeded'] += 1
            elif line.startswith('Failed'):
                status['Failed'] += 1
            else:
                status['Pending'] += 1
            
    # get number of running pods
    arglist = [kubectl, 'get', 'pods', '-o', 'custom-columns=STATUS:.status.phase', '-l', selector]
    if dry_run:
        logging.info(arglist)
    else:
        try:
            proc = safe_exec(arglist)
        except SafeExecError as e:
            raise UserReportError(CLUSTER_ERROR, e.message.strip())
        for line in proc.stdout.decode().split('\n'):
            if line == 'Running':
                status[line] += 1

    # correct number of pending jobs: running jobs were counted twice,
    # as running and pending
    status['Pending'] -= status['Running']

    return status['Pending'], status['Running'], status['Succeeded'], status['Failed']
