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
elb/tuner.py - Functions for checking and estimating ElasticBLAST compute and
memory requirements

Created: Fri 14 May 2021 05:10:18 PM EDT
"""

import json
from .filehelper import open_for_read
from .constants import ELB_BLASTDB_MEMORY_MARGIN, BLASTDB_ERROR
from .base import DBSource
from .util import UserReportError


def get_blastdb_mem_requirements(db: str, source: DBSource) -> float:
    """
    Get memory requirements for a BLAST database in GB.

    Arguments:
        db: Database name or URI
        source: Source for NCBI provided database, ignored for a user database
    """
    DB_BUCKET_AWS = 's3://ncbi-blast-databases'
    DB_BUCKET_GCP = 'gs://blast-db'
    DB_BUCKET_NCBI = 'ftp://ftp.ncbi.nlm.nih.gov/blast/db'

    # for user databases
    metadata_file = db + '.json'

    # if an NCBI-provided database
    if not db.startswith('s3://') and not db.startswith('gs://'):
        if source == DBSource.AWS or source == DBSource.GCP:
            bucket = DB_BUCKET_AWS if source == DBSource.AWS else DB_BUCKET_GCP
            with open_for_read(f'{bucket}/latest-dir') as f:
                metadata_file = f'{bucket}/{f.readline().rstrip()}/{db}.json'
        else:
            metadata_file = f'{DB_BUCKET_NCBI}/{db}.json'

    try:
        with open_for_read(metadata_file) as f:
            db_metadata = json.load(f)
    except:
        msg = f'Metadata file for database: "{db}" does not exist'
        if db.startswith('s3://') or db.startswith('gs://'):
            msg += ' or you lack credentials to access this file'
        msg += '.'
        raise UserReportError(returncode=BLASTDB_ERROR, message=msg)
    bytes_to_cache_gb = int(db_metadata['bytes-to-cache']) / (1024 ** 3)
    return round(bytes_to_cache_gb * ELB_BLASTDB_MEMORY_MARGIN, 1)
