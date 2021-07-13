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

import json, logging, os
from enum import Enum
from dataclasses import dataclass
from .filehelper import open_for_read
from .constants import BLASTDB_ERROR, INPUT_ERROR, ELB_BLASTDB_MEMORY_MARGIN
from .constants import UNKNOWN_ERROR, MolType
from .constants import ELB_S3_PREFIX, ELB_GCS_PREFIX
from .base import DBSource, PositiveInteger, MemoryStr
from .util import UserReportError, get_query_batch_size
from .aws_traits import get_instance_type_offerings, get_suitable_instance_types

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


def get_db_data(db: str, dbtype: MolType, source: DBSource) -> DbData:
    """
    Read database metadata.

    Arguments:
        db: Database name or URI
        dbtype: Molecule type for BLASTDB
        source: Source for NCBI provided database, ignored for a user database
    """
    DB_BUCKET_AWS = os.path.join(ELB_S3_PREFIX, 'ncbi-blast-databases')
    DB_BUCKET_GCP = os.path.join(ELB_GCS_PREFIX, 'blast-db')
    DB_BUCKET_NCBI = 'ftp://ftp.ncbi.nlm.nih.gov/blast/db'

    # for user databases
    metadata_file = f"{db}-{dbtype}-metadata.json"

    # if an NCBI-provided database
    if not db.startswith(ELB_S3_PREFIX) and not db.startswith(ELB_GCS_PREFIX):
        if source == DBSource.AWS or source == DBSource.GCP:
            bucket = DB_BUCKET_AWS if source == DBSource.AWS else DB_BUCKET_GCP
            with open_for_read(f'{bucket}/latest-dir') as f:
                metadata_file = os.path.join(f'{bucket}/{f.readline().rstrip()}', metadata_file)
        else:
            metadata_file = os.path.join(f'{DB_BUCKET_NCBI}', metadata_file)
    logging.debug(f'BLASTDB metadata file: {metadata_file}')
    try:
        with open_for_read(metadata_file) as f:
            db_metadata = json.load(f)
    except:
        msg = f'Metadata file for database: "{db}" does not exist in {source}'
        if db.startswith(ELB_S3_PREFIX) or db.startswith(ELB_GCS_PREFIX):
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
           '-negative_taxids' in options or '-negative_taxidlist' in options:
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


def get_mem_limit(db: DbData, const_limit: MemoryStr, db_factor: float,
                  with_optimal: bool) -> MemoryStr:
    """Get memory limit for searching a single query batch

    Arguments:
        db: Database information
        const_limit: A constant memory limit
        db_factor: If larger than 0, memory limit will be computed as databse
                   bytes-to-cache times db_factor
        with_optimal: Set memory limit for optimal instance type in AWS

    Returns:
        A search job memory limit as MemoryStr"""
    if db_factor > 0.0:

        return MemoryStr(f'{round(db.bytes_to_cache_gb * db_factor, 1)}G')
    else:
        if with_optimal:
            result = 60 if db.bytes_to_cache_gb >= 60 else db.bytes_to_cache_gb + 2
            return MemoryStr(f'{result}G')
        else:
            return const_limit


def get_machine_type(db: DbData, num_cpus: PositiveInteger, region: str) -> str:
    """Select a machine type that can acomodate the database and and has
    enough VCPUs. The machine type is selected from a set of machines supported
    by AWS Batch and offered in a specific region.

    Arguments:
        db: Database information
        num_cpus: Required number of CPUs
        region: Cloud provided region

    Returns:
        Instance type with at least as much memory as db.bytes_to_cache_gb and
        required number of CPUs"""

    AWS_BATCH_SUPPORTED_INSTANCE_TYPES = ['m6g.xlarge', 'r5d.24xlarge', 
          'm3.xlarge', 'r4.16xlarge', 'r5a.2xlarge', 'c6g.4xlarge',
          'm6gd.xlarge', 'm5.xlarge', 'c5a.2xlarge', 'r6g.4xlarge',
          'r6g.16xlarge', 'i3.4xlarge', 'z1d.3xlarge', 'm5n.24xlarge',
          'a1.medium', 'd3en.2xlarge', 'c6gd.12xlarge', 'r5b.16xlarge',
          'm5.large', 'c5d.large', 'm6g.2xlarge', 'm5dn.2xlarge', 'c5.large',
          'g4dn.2xlarge', 'c5.metal', 'i3en.6xlarge', 'inf1.2xlarge',
          'd3.4xlarge', 'r6gd.4xlarge', 'm5.2xlarge', 'r6g.xlarge',
          'm5dn.8xlarge', 'r5n.16xlarge', 'm6g.8xlarge', 'm6gd.12xlarge',
          'c5a.8xlarge', 'i2.xlarge', 'm5d.12xlarge', 'm5.metal', 'c5d.metal',
          'm4.4xlarge', 'm5.12xlarge', 'm6g.12xlarge', 'r5n.4xlarge',
          'm6gd.4xlarge', 'd3en.8xlarge', 'c4.large', 'c5d.2xlarge',
          'r5d.2xlarge', 'r5.xlarge', 'r5b.24xlarge', 'c4.4xlarge', 'c4.xlarge',
          'c6g.large', 'c6gd.medium', 'r6gd.12xlarge', 'r4.8xlarge',
          'm5d.xlarge', 'c6gd.2xlarge', 'm5.8xlarge', 'c5.2xlarge',
          'g3.8xlarge', 'c5n.9xlarge']

    # get a list of instance types offered in the region
    offerings = get_instance_type_offerings(region)

    supported_offerings = [tp for tp in offerings if tp in AWS_BATCH_SUPPORTED_INSTANCE_TYPES]

    # get properties of suitable instances
    suitable_props = get_suitable_instance_types(min_memory=MemoryStr(f'{db.bytes_to_cache_gb * ELB_BLASTDB_MEMORY_MARGIN}G'),
                                                 min_cpus=num_cpus,
                                                 instance_types=supported_offerings)

    return sorted(suitable_props, key=lambda x: x['VCpuInfo']['DefaultVCpus'])[0]['InstanceType']

