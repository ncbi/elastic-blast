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
from enum import Enum
from dataclasses import dataclass
from .filehelper import open_for_read
from .constants import BLASTDB_ERROR, INPUT_ERROR
from .base import DBSource
from .util import UserReportError, get_query_batch_size


class MolType(Enum):
    """Sequence molecular type"""
    PROTEIN = 'prot'
    NUCLEOTIDE = 'nucl'


@dataclass
class SeqData:
    """Basic sequence information"""
    length: int
    moltype: MolType


@dataclass
class DbData(SeqData):
    """Database information"""
    bytes_to_cache_gb: float


class MTMode(Enum):
    """Values for BLAST MT mode option

    Str converter generates commad line option."""
    ZERO = 0
    ONE = 1

    def __str__(self):
        """Convert enum value to BLAST commad line options string"""
        return '-mt_mode 1' if self.value == 1 else ''


# MT mode 1 query length per thread
RESIDUES_PER_THREAD = 10000
BASES_PER_THREAD = 2500000

# Maximum database length for MT mode 1
MAX_MT_ONE_DB_LENGTH_PROT = 2000000000
MAX_MT_ONE_DB_LENGTH_NUCL = 14000000000

# Number of threads for MT mode 0
NUM_THREADS_MT_ZERO = 16


def get_db_data(db: str, source: DBSource) -> DbData:
    """
    Read database metadata.

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

    return DbData(length = int(db_metadata['number-of-letters']),
                  moltype = MolType[db_metadata['dbtype'].upper()],
                  bytes_to_cache_gb = int(db_metadata['bytes-to-cache']) / (1024 ** 3))


def get_mt_mode(program: str, options: str, db: DbData, query: SeqData) -> MTMode:
    """
    Compute BLAST search MT mode

    Arguments:
        program: BLAST program
        options: BLAST options (empty string for defaults)
        db: Database information
        query: Queries information
    """
    if (query.moltype == MolType.PROTEIN and query.length <= RESIDUES_PER_THREAD) or \
       (query.moltype == MolType.NUCLEOTIDE and query.length <= BASES_PER_THREAD):
        return MTMode.ZERO

    if program.lower() == 'rpsblast' or program.lower() == 'rpstblastn':
        return MTMode.ONE

    if '-taxids' in options or '-taxidlist' in options or \
           '-gilist' in options or '-seqidlist' in options or \
           '-negative_taxidlist' in options:
        return MTMode.ONE

    if (db.moltype == MolType.PROTEIN and db.length <= MAX_MT_ONE_DB_LENGTH_PROT) or \
       (db.moltype == MolType.NUCLEOTIDE and db.length <= MAX_MT_ONE_DB_LENGTH_NUCL):
        return MTMode.ONE

    return MTMode.ZERO


def get_num_cpus(mt_mode: MTMode, query: SeqData) -> int:
    """Get number of CPUs to use to optimally run BLAST

    Arguments:
        mt_mode: BLAST MT mode
        query: Queries information"""
    if mt_mode == MTMode.ZERO:
        return NUM_THREADS_MT_ZERO
    else:
        characters_per_thread = RESIDUES_PER_THREAD if query.moltype == MolType.PROTEIN else BASES_PER_THREAD
        return min([query.length // characters_per_thread + 1, 16])


def get_batch_length(program: str, mt_mode: MTMode, num_cpus: int) -> int:
    """
    Get batch length for BLAST batch search

    Arguments:
        program: BLAST program
        mt_mode: BLAST MT mode
        num_cpus: Number of threads/CPUs to use
    """
    batch_len = get_query_batch_size(program)
    if batch_len is None:
        raise UserReportError(returncode=INPUT_ERROR,
                              message=f"Invalid BLAST program '{program}'")

    if mt_mode == MTMode.ONE:
        batch_len *= num_cpus

    return batch_len
