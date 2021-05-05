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
from elb import gcp
from elb import aws
from elb.util import SafeExecError, UserReportError
from elb.status import get_status
from elb.constants import CLUSTER_ERROR, CSP, ElbCommand
from elb.elb_config import ElasticBlastConfig

def create_arg_parser(subparser, common_opts_parser):
    """ Create the command line options subparser for the status command. """
    parser = subparser.add_parser('status', parents=[common_opts_parser],
                                  help='Get the status of an ElasticBLAST search')
    parser.add_argument("--wait", action='store_true',
                        help="Wait for job completion")
    # FIXME: EB-132
    parser.add_argument("--run-label", type=str,
                        help="Run-label for this ElasticBLAST search, format: key:value")
    parser.set_defaults(func=_status)


#TODO: use cfg only when args.wait, args.sync, and args.run_label are replicated in cfg
def _status(args, cfg, clean_up_stack):
    """ Entry point to handle checking status for an ElasticBLAST search """
    cfg.validate(ElbCommand.STATUS)
    returncode = 0
    try:
        dry_run = cfg.cluster.dry_run

        if cfg.cloud_provider.cloud == CSP.GCP:
            gcp.get_gke_credentials(cfg)

        while True:

            if cfg.cloud_provider.cloud == CSP.AWS:
                eb = aws.ElasticBlastAws(cfg)
                counts = eb.check_status()
                pending = counts['pending']
                running = counts['running']
                succeeded = counts['succeeded']
                failed = counts['failed']
            else:
                pending, running, succeeded, failed = get_status(args.run_label, dry_run=dry_run)

            if not args.wait or pending + running == 0:
                break
            logging.debug(f'Pending {pending}, Running {running}, Succeeded {succeeded}, Failed {failed}')
            time.sleep(20)  # TODO: make this a parameter (granularity)
    except RuntimeError as e:
        returncode = e.args[0]
        print(e.args[1], file=sys.stderr)
    except ValueError as e:
        returncode = 1
        print(e)
    except SafeExecError as err:
        msg = err.message.rstrip().replace('\n', ' | ')
        logging.debug(f'kubectl error: {msg}')
        # if the cluster exists, assume it is initializing
        if gcp.check_cluster(cfg):
            raise UserReportError(CLUSTER_ERROR, f'The cluster "{cfg.cluster.name}" exists, but is not responding. It may be still initializing, please try checking status again in a few minutes.')
        else:
            raise UserReportError(CLUSTER_ERROR, f'The cluster "{cfg.cluster.name}" was not found')
    else:
        print(f'Pending {pending}\nRunning {running}\nSucceeded {succeeded}\nFailed {failed}')
    return returncode
