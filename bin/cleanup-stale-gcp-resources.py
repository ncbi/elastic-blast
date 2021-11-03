#!/usr/bin/env python3
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
share/tools/cleanup-stale-gcp-resources.py - See DESC constant below

Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
Created: Fri 21 May 2021 02:48:21 PM EDT
"""
import argparse
import unittest
import json, pprint
import logging
import subprocess
from datetime import datetime, timezone
import datetime
from os.path import basename
import shlex
from typing import List, Union

VERSION = '0.1'
DFLT_LOGFILE = 'stderr'
DFLT_PROJECT = 'ncbi-sandbox-blast'
DESC = r"""Script to clean up GCP resources that are older than the specified date"""


def safe_exec(cmd: Union[List[str], str]) -> subprocess.CompletedProcess:
    """Wrapper around subprocess.run that raises SafeExecError on errors from
    command line with error messages assembled from all available information"""
    if isinstance(cmd, str):
        cmd = cmd.split()
    if not isinstance(cmd, list):
        raise ValueError('safe_exec "cmd" argument must be a list or string')

    try:
        logging.debug(' '.join(cmd))
        p = subprocess.run(cmd, check=True, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        msg = f'The command "{" ".join(e.cmd)}" returned with exit code {e.returncode}\n{e.stderr.decode()}\n{e.stdout.decode()}'
        if e.output is not None:
            '\n'.join([msg, f'{e.output.decode()}'])
            raise RuntimeError(e.returncode, msg)
    return p


def main():
    """ Entry point into this program. """
    parser = create_arg_parser()
    args = parser.parse_args()
    config_logging(args)

    date_threshold = datetime.datetime.now(timezone.utc) - datetime.timedelta(days=args.older_than)
    logging.debug(f"date_threshold={date_threshold}")

    # GKE clusters
    cmd = f"gcloud container clusters list --project {args.project} --format json "
    cmd += "--filter='status=RUNNING AND resourceLabels.billingcode=elastic-blast'"
    p = safe_exec(shlex.split(cmd))
    clusters = json.loads(p.stdout.decode())

    for cluster in clusters:
        creation_time = datetime.datetime.fromisoformat(cluster['createTime'])
        if date_threshold > creation_time:
            if args.delete:
                cmd = 'gcloud container clusters delete --quiet --project '
                cmd += f"{args.project} --zone {cluster['zone']} {cluster['name']}"
                if not args.dry_run:
                    safe_exec(cmd)
                else:
                    logging.info(cmd)
            else:
                logging.info(f"{cluster['name']} {cluster['createTime']}")

    # GCE disks
    cmd = f"gcloud compute disks list --project {args.project} --format json "
    cmd += "--filter='labels.billingcode=elastic-blast'"
    p = safe_exec(shlex.split(cmd))
    disks = json.loads(p.stdout.decode())

    for disk in disks:
        creation_time = datetime.datetime.fromisoformat(disk['creationTimestamp'])
        if date_threshold > creation_time:
            if args.delete:
                cmd = 'gcloud compute disks delete --quiet --project '
                cmd += f"{args.project} --zone {basename(disk['zone'])} {disk['name']}"
                if not args.dry_run:
                    safe_exec(cmd)
                else:
                    logging.info(cmd)
            else:
                logging.info(f"{disk['name']} {disk['creationTimestamp']}")

    # GCE instances
    cmd = f"gcloud compute instances list --project {args.project} --format json "
    cmd += "--filter='labels.billingcode=elastic-blast'"
    p = safe_exec(shlex.split(cmd))
    instances = json.loads(p.stdout.decode())

    for instance in instances:
        creation_time = datetime.datetime.fromisoformat(instance['creationTimestamp'])
        if date_threshold > creation_time:
            if args.delete:
                cmd = 'gcloud compute instances delete --project '
                cmd += f"{args.project} --zone {basename(instance['zone'])} {instance['name']}"
                if not args.dry_run:
                    safe_exec(cmd)
                else:
                    logging.info(cmd)
            else:
                logging.info(f"{instance['name']} {instance['creationTimestamp']}")
    return 0


def create_arg_parser():
    """ Create the command line options parser object for this script. """
    parser = argparse.ArgumentParser(description=DESC)
    parser.add_argument("--project", help=f"GCP Project ID, default: {DFLT_PROJECT}", default=DFLT_PROJECT)
    parser.add_argument("--older-than", default=1, type=int, 
            help="Display/delete GKE clusters older than this number of days, default: 1")
    parser.add_argument("--delete", action='store_true',
                        help="Delete GCP resources")
    parser.add_argument("--dry-run", action='store_true',
                        help="Do not delete anything")
    parser.add_argument("--logfile", default=DFLT_LOGFILE,
                        help="Default: " + DFLT_LOGFILE)
    parser.add_argument("--loglevel", default='DEBUG',
                        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    parser.add_argument('-V', '--version', action='version',
                        version='%(prog)s ' + VERSION)
    return parser


def config_logging(args):
    if args.logfile == 'stderr':
        logging.basicConfig(level=str2ll(args.loglevel),
                            format="%(asctime)s %(message)s")
    else:
        logging.basicConfig(filename=args.logfile, level=str2ll(args.loglevel),
                            format="%(asctime)s %(message)s", filemode='a')
    logging.logThreads = 0
    logging.logProcesses = 0
    logging._srcfile = None


def str2ll(level):
    """ Converts the log level argument to a numeric value.

    Throws an exception if conversion can't be done.
    Copied from the logging howto documentation
    """
    retval = getattr(logging, level.upper(), None)
    if not isinstance(retval, int):
        raise ValueError('Invalid log level: %s' % level)
    return retval


if __name__ == "__main__":
    import sys, traceback
    try:
        sys.exit(main())
    except Exception as e:
        print(e, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

