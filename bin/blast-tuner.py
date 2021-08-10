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
blast-tuner.py - See DESC constant below

Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
Created: Tue 21 Apr 2020 12:07:42 PM EDT
"""
import os
import argparse
import json
import logging
from elastic_blast import VERSION
from elastic_blast.config import configure
from elastic_blast.util import ElbSupportedPrograms, UserReportError
from elastic_blast.util import get_query_batch_size, config_logging
from elastic_blast.tuner import get_db_data, SeqData, MTMode, MolType
from elastic_blast.tuner import get_mt_mode, get_num_cpus, get_batch_length
from elastic_blast.tuner import aws_get_machine_type, aws_get_mem_limit
from elastic_blast.tuner import gcp_get_machine_type, gcp_get_mem_limit
from elastic_blast.base import DBSource, PositiveInteger, MemoryStr
from elastic_blast.constants import CFG_CLOUD_PROVIDER, CFG_CP_AWS_REGION, CFG_CP_GCP_REGION
from elastic_blast.constants import ELB_DFLT_GCP_REGION, ELB_DFLT_AWS_REGION
from elastic_blast.constants import CFG_BLAST, CFG_CLUSTER
from elastic_blast.constants import CFG_BLAST_DB, CFG_BLAST_PROGRAM, CFG_BLAST_BATCH_LEN
from elastic_blast.constants import CFG_BLAST_OPTIONS, CFG_CLUSTER_NUM_CPUS
from elastic_blast.constants import CFG_CLUSTER_MACHINE_TYPE
from elastic_blast.constants import CFG_BLAST_MEM_LIMIT
from elastic_blast.constants import MolType, INPUT_ERROR, CSP


DESC = r"""This application's purpose is to provide suggestions to run help run
BLAST efficiently. It is meant to be used in conjunction with BLAST+ and
ElasticBLAST."""


def main():
    """ Entry point into this program. """
    try:
        parser = create_arg_parser()
        args = parser.parse_args()
        config_logging(args)
        cfg = configure(args)

        options = '' if args.options is None else args.options
        SECTIONS = [ CFG_CLOUD_PROVIDER, CFG_BLAST, CFG_CLUSTER ]
        conf = { s : {} for s in SECTIONS }
        cloud_provider = CSP[args.csp_target]
        sp = ElbSupportedPrograms()

        db_source = DBSource[cloud_provider.name] if not args.db_source else DBSource[args.db_source]

        if args.db_mem_limit_factor is None:
            db_mem_limit_factor = 0.0 if cloud_provider == CSP.AWS else 1.1
        else:
            db_mem_limit_factor = args.db_mem_limit_factor

        if args.db is not None:
            db_data = get_db_data(args.db, sp.get_db_mol_type(args.program),
                                  db_source)
            conf[CFG_BLAST][CFG_BLAST_DB] = args.db

        if not args.region:
            if cloud_provider == CSP.AWS:
                args.region = ELB_DFLT_AWS_REGION
            else:
                args.region = ELB_DFLT_GCP_REGION

        if cloud_provider == CSP.AWS:
            conf[CFG_CLOUD_PROVIDER][CFG_CP_AWS_REGION] = args.region
        else:
            conf[CFG_CLOUD_PROVIDER][CFG_CP_GCP_REGION] = args.region

        query_data = SeqData(args.total_query_length,
                             sp.get_query_mol_type(args.program))
        mt_mode = get_mt_mode(args.program, args.options, db_data, query_data)
        options += f' {mt_mode}'

        num_cpus = get_num_cpus(program = args.program, mt_mode = mt_mode,
                                query = query_data)
        conf[CFG_BLAST][CFG_BLAST_PROGRAM] = args.program
        conf[CFG_BLAST][CFG_BLAST_BATCH_LEN] = str(get_batch_length(program = args.program,
                                                          mt_mode = mt_mode,
                                                          num_cpus = num_cpus))

        if len(options) > 1:
           conf[CFG_BLAST][CFG_BLAST_OPTIONS] = options

        conf[CFG_CLUSTER][CFG_CLUSTER_NUM_CPUS] = str(num_cpus)

        if cloud_provider == CSP.AWS:
            mem_limit = aws_get_mem_limit(db = db_data,
                                          const_limit = MemoryStr(f'{args.constant_mem_limit}G'),
                                          db_factor = db_mem_limit_factor,
                                          with_optimal = args.with_optimal)
        else:
            # Currently one job per instance is assumed in GCP
            mem_limit = gcp_get_mem_limit(db = db_data,
                                          db_factor = db_mem_limit_factor)
        conf[CFG_BLAST][CFG_BLAST_MEM_LIMIT] = mem_limit

        if args.with_optimal:
            machine_type = 'optimal'
            if cloud_provider != CSP.AWS:
                raise UserReportError(INPUT_ERROR, f'The "optimal" instance type is only allowed for AWS')
        else:
            if cloud_provider == CSP.AWS:
                machine_type = aws_get_machine_type(db = db_data,
                                                    num_cpus = num_cpus,
                                                    region = args.region)
            else:
                machine_type = gcp_get_machine_type(mem_limit = mem_limit,
                                                     num_cpus = num_cpus)

        conf[CFG_CLUSTER][CFG_CLUSTER_MACHINE_TYPE] = machine_type

        for section in SECTIONS:
            print(f'[{section}]', file=args.out)
            for key, value in sorted(conf[section].items(), key=lambda x: x[0]):
                print(f'{key} = {value}', file=args.out)
            print('', file=args.out)

        return 0
    except UserReportError as err:
        logging.error(err.message)
        return err.returncode


def create_arg_parser():
    """ Create the command line options parser object for this script. """
    DFLT_LOGFILE = 'stderr'
    parser = argparse.ArgumentParser(prog=os.path.basename(os.path.splitext(sys.argv[0])[0]), 
                                     description=DESC)
    parser._action_groups.pop()
    required = parser.add_argument_group('required arguments')
    optional = parser.add_argument_group('optional arguments')

    required.add_argument("--db", type=str, help="BLAST database to search", required=True)
    required.add_argument("--program", type=str, help="BLAST program to run",
                        choices=ElbSupportedPrograms().get(), required=True)
    required.add_argument("--total-query-length", type=PositiveInteger, required=True,
                        help='Number of residues or bases in query sequecnes')
    required.add_argument("--csp-target", type=str, help="Which Cloud Service Provider to use, default: AWS", choices=['AWS', 'GCP'], default='AWS')
    required.add_argument('--out', type=argparse.FileType('w'), help='Save configuration in this file', default='-')

    optional.add_argument("--db-source", type=str, help="Where NCBI-provided databases are downloaded from, default: AWS", choices=['AWS', 'GCP', 'NCBI'])
    optional.add_argument("--region", type=str, help=f'Cloud Service Provider region. Defaults: {ELB_DFLT_AWS_REGION} for AWS; {ELB_DFLT_GCP_REGION} for GCP')
    optional.add_argument("--options", type=str, help='BLAST options', default='')
    optional.add_argument("--db-mem-limit-factor", type=float,
                          help='This number times database bytes-to-cache will produce memory limit for a BLAST search. (default: 0.0: for AWS, 1.1 for GCP)')
    optional.add_argument("--constant-mem-limit", type=int, help='A constant memory limit for all search jobs in GB', default='20')
    optional.add_argument("--with-optimal", action='store_true',
                         help='Use AWS optimal instance type')
    optional.add_argument('--version', action='version',
                        version='%(prog)s ' + VERSION)
    optional.add_argument("--logfile", default=DFLT_LOGFILE, type=str,
                        help="Default: " + DFLT_LOGFILE)
    optional.add_argument("--loglevel", default='INFO',
                        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    return parser


if __name__ == "__main__":
    import sys, traceback
    try:
        sys.exit(main())
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

