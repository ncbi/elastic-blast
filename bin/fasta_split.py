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
Split FASTA file into smaller chunks

File can be on local filesystem, available by URL,
or reside in GCP bucket (GS). File can be compressed and/or
archived (contents of all files in the archive is treated as
one large merged file). Following combinations are recognized:
.gz, .tar, .tar.gz, .tgz, .tar.bz2 .

Also creates YAML files for each generated piece from template,
substituting several variable.

For details see README file

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""

import sys
import argparse
from tarfile import ReadError
from elastic_blast.filehelper import open_for_read, open_for_write, copy_to_bucket
from elastic_blast.split import FASTAReader
from elastic_blast.jobs import write_job_files
from elastic_blast.constants import ELB_QUERY_BATCH_FILE_PREFIX


DEFAULT_BATCH_LEN    = 5000000
DEFAULT_OUT_PATH     = 'batches'
DEFAULT_RES_PATH     = 'results'
DEFAULT_JOB_PATH     = 'jobs'

manifest_file = sys.stdout


def parse_arguments():
    parser = argparse.ArgumentParser(description="Split FASTA file")
    parser.add_argument('input', help='input FASTA file, possible gzipped')
    parser.add_argument('-l', '--batch_len', type=int, default=DEFAULT_BATCH_LEN,
        help='batch length')
    parser.add_argument('-o', '--output',    default=DEFAULT_OUT_PATH,
        help='output path for batch FASTA files')
    parser.add_argument('-r', '--results',   default=DEFAULT_RES_PATH,
        help='output path for BLAST results')
    parser.add_argument('-j', '--job_path',  default=DEFAULT_JOB_PATH,
        help='output path for job YAML files')
    parser.add_argument('-t', '--template',  default='',
        help='YAML template')
    parser.add_argument('-s', '--subs',  default='',
        help='Variable substitutes in form var1=vale1,var2=value2 ...')
    parser.add_argument('-m', '--manifest',  default='',
        help='manifest file to write')
    parser.add_argument('-c', '--count',  default='',
        help='file to report total number of bases/residues in input file')
    parser.add_argument("-n", "--dry-run", action='store_true', 
                        help="Do not run any commands, just show what would be executed")
    return parser.parse_args()

def main():
    global manifest_file
    args = parse_arguments()
    input_path   = args.input
    out_path     = args.output
    res_path     = args.results
    job_path     = args.job_path
    batch_len    = args.batch_len
    job_template = args.template
    manifest     = args.manifest
    count_file   = args.count
    dry_run      = args.dry_run
    job_template_text = ''
    try:
        if job_template:
            with open_for_read(job_template) as f:
                job_template_text = f.read()
    except FileNotFoundError as e:
        print(e, "for --template parameter", file=sys.stderr)
        return 1
    # Convert string of form key1=val1,key2=val2 into dictionary { 'key1' : 'val1', 'key2' : 'val2' }
    subs = { key: value for key, value in filter(lambda x: len(x) == 2 and x[0], map(lambda x: x.split('='), args.subs.split(','))) }
    subs['RESULTS'] = res_path
    total_count = 0
    try:
        with open_for_read(input_path) as s:
            reader = FASTAReader(s, batch_len, out_path)
            total_count, queries = reader.read_and_cut()
        jobs = write_job_files(job_path, ELB_QUERY_BATCH_FILE_PREFIX, job_template_text, queries, **subs)
        if count_file:
            if count_file == '-':
                sys.stdout.write(str(total_count)+'\n')
            else:
                with open_for_write(count_file) as f:
                    f.write(str(total_count))
        if jobs and manifest:
            manifest_text = '\n'.join(jobs)+'\n'
            if manifest == '-':
                sys.stdout.write(manifest_text)
            else:
                with open_for_write(manifest) as manifest_file:
                    manifest_file.write(manifest_text)
    except FileNotFoundError as e:
        print(e, "for input file", file=sys.stderr)
        return 2
    except PermissionError as e:
        print(e, file=sys.stderr)
        return 3
    except UnicodeDecodeError as e:
        print(e, "\nPossibly missing .gz or .tar extension for compressed or archived file", file=sys.stderr)
        return 4
    except OSError as e:
        # If .gz extension is present on not gzipped file
        print(e, file=sys.stderr)
        return 5
    except ReadError as e:
        print(e, "\nProbably not a tar file", file=sys.stderr)
        return 6
    except Exception as e:
        # If the file is empty
        print(e, file=sys.stderr)
        return 7
    copy_to_bucket(dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
