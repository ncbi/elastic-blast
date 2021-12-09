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
elb/commands/status.py - check status of job execution

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""

import sys
import time
import logging
from typing import Any, List

from elastic_blast.constants import ElbCommand, ElbStatus
from elastic_blast.elasticblast_factory import ElasticBlastFactory
from elastic_blast.elb_config import ElasticBlastConfig

def create_arg_parser(subparser, common_opts_parser):
    """ Create the command line options subparser for the status command. """
    parser = subparser.add_parser('status', parents=[common_opts_parser],
                                  help='Get the status of an ElasticBLAST search')
    parser.add_argument("--wait", action='store_true',
                        help="Wait for job completion")
    parser.add_argument('--verbose', default=False, action='store_true',
                        help='Detailed information about jobs')
    parser.set_defaults(func=_status)


#TODO: use cfg only when args.wait, args.sync, and args.run_label are replicated in cfg
def _status(args, cfg: ElasticBlastConfig, clean_up_stack: List[Any]) -> int:
    """ Entry point to handle checking status for an ElasticBLAST search """
    cfg.validate(ElbCommand.STATUS)
    returncode = 0
    try:
        verbose_result = ''
        elastic_blast = ElasticBlastFactory(cfg, False, clean_up_stack)
        while True:
            status, counts, verbose_result = elastic_blast.check_status(args.verbose)
            result = str(status)
            if counts:
                result = '\n'.join([f'{x} {counts[x.lower()]}' for x in
                    ('Pending', 'Running', 'Succeeded', 'Failed')
                ])

            logging.debug(result)
            if not args.wait or status in (ElbStatus.SUCCESS, ElbStatus.FAILURE, ElbStatus.UNKNOWN):
                break
            time.sleep(20)  # TODO: make this a parameter (granularity)
    except RuntimeError as err:
        returncode = err.args[0]
        print(err.args[1], file=sys.stderr)
    except ValueError as err:
        returncode = 1
        print(err)
    else:
        if verbose_result:
            print(verbose_result)
        else:
            print(result)
    return returncode
