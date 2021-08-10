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
from bisect import bisect_left
from .filehelper import open_for_read
from .constants import BLASTDB_ERROR, INPUT_ERROR, ELB_BLASTDB_MEMORY_MARGIN
from .constants import UNKNOWN_ERROR, MolType
from .constants import ELB_S3_PREFIX, ELB_GCS_PREFIX
from .base import DBSource, PositiveInteger, MemoryStr
from .util import UserReportError, get_query_batch_size
from .aws_traits import get_instance_type_offerings, get_suitable_instance_types
from .gcp_traits import GCP_MACHINES

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
# From https://preview.ncbi.nlm.nih.gov/books/prevqa/NBK322759/ , in particular
# As noted above, the threading by query option works well with relatively small databases if you have a lot of queries to process.
# For BLASTP, your input FASTA should contain at least 10,000 residues per thread, or 320,000 residues for 32 threads. 
# For BLASTX, the FASTA should contain 30,000 bases per thread. For both BLASTP and BLASTX, we find threading by query works best 
# if the database has fewer than 2 billion residues (e.g, swissprot). For BLASTN, your FASTA file should contain at least 2.5 
# million bases per thread and the database should contain fewer than 14 billion residues. Threading by query also works well if
# you limit the search, such as by -taxid or -gilist, regardless of the size of the database.
RESIDUES_PER_THREAD = 10000
BASES_PER_THREAD = 2500000
BASES_PER_THREAD_BLASTX = 30000

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
    if program == 'blastx' and query.length <= BASES_PER_THREAD_BLASTX:
        return MTMode.ZERO
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


def get_num_cpus(program: str, mt_mode: MTMode, query: SeqData) -> int:
    """Get number of CPUs to use to optimally run BLAST

    Arguments:
        program: BLAST program
        mt_mode: BLAST MT mode
        query: Queries information"""
    if mt_mode == MTMode.ZERO:
        return NUM_THREADS_MT_ZERO
    else:
        if program.lower() == 'blastx':
            characters_per_thread = BASES_PER_THREAD_BLASTX
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

    if program.lower == 'blastx':
        batch_len = BASES_PER_THREAD_BLASTX

    if mt_mode == MTMode.ONE:
        batch_len *= num_cpus

    return batch_len


def aws_get_mem_limit(db: DbData, const_limit: MemoryStr, db_factor: float,
                  with_optimal: bool) -> MemoryStr:
    """Get memory limit for searching a single query batch for AWS

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


def gcp_get_mem_limit(db: DbData, db_factor: float) -> MemoryStr:
    """Get memory limit for searching a single query batch for GCP. One job
    per instance is assumed.

    Arguments:
        db: Database information
        db_factor: If larger than 0, memory limit will be computed as database
                   bytes-to-cache times db_factor

    Returns:
        A search job memory limit as MemoryStr"""
    return MemoryStr(f'{round(db.bytes_to_cache_gb * db_factor, 1)}G')


def aws_get_machine_type(db: DbData, num_cpus: PositiveInteger, region: str) -> str:
    """Select an AWS machine type that can accommodate the database and has
    enough VCPUs. The machine type is selected from a set of machines supported
    by AWS Batch and offered in a specific region.

    Arguments:
        db: Database information
        num_cpus: Required number of CPUs
        region: Cloud provided region

    Returns:
        Instance type with at least as much memory as db.bytes_to_cache_gb and
        required number of CPUs"""
    M5_FAMILY = ['m5.large'] + [f'm5.{i}xlarge' for i in [2, 4, 8, 12, 16, 24]]
    C5_FAMILY = ['c5.large'] + [f'c5.{i}xlarge' for i in [2, 4, 9, 12, 18, 24]]
    R5_FAMILY = ['r5.large'] + [f'r5.{i}xlarge' for i in [2, 4, 8, 12, 16, 24]]
    SUPPORTED_INSTANCE_TYPES = M5_FAMILY + C5_FAMILY + R5_FAMILY

    # get a list of instance types offered in the region
    offerings = get_instance_type_offerings(region)

    supported_offerings = [tp for tp in offerings if tp in SUPPORTED_INSTANCE_TYPES]

    # get properties of suitable instances
    suitable_props = get_suitable_instance_types(min_memory=MemoryStr(f'{db.bytes_to_cache_gb * ELB_BLASTDB_MEMORY_MARGIN}G'),
                                                 min_cpus=num_cpus,
                                                 instance_types=supported_offerings)

    return sorted(suitable_props, key=lambda x: x['VCpuInfo']['DefaultVCpus'])[0]['InstanceType']


def gcp_get_machine_type(mem_limit: MemoryStr, num_cpus: PositiveInteger) -> str:
    """Select a GCP machine type that can accommodate the database and has
    enough VCPUs. The instance type is selected from E2 and N1 instance
    families. One job per instance is assumed.

    Arguments:
        mem_limit: Search job memort limit
        num_cpus: Required number of CPUs

    Returns:
        Instance type with at least as much memory as mem_limit and
        required number of CPUs"""
    # machine type families ranked by memory to CPU ratio (order matters)
    FAMILIES_N1 = ['n1-highcpu',
                   'n1-standard',
                   'n1-highmem']

    FAMILIES_E2 = ['e2-standard', 'e2-highmem']

    # numbers of CPUs in GCP instance types
    CPUS = [1, 2, 4, 8, 16, 32, 64, 96]

    idx = bisect_left(CPUS, num_cpus)
    if idx >= len(CPUS):
        raise UserReportError(returncode=UNKNOWN_ERROR,
                              message=f'GCP machine type with {num_cpus} CPUs could not be found')

    # E2 machine types are usually the cheapest, but have at most 128GB memory
    machine_type_families = FAMILIES_E2 if mem_limit.asGB() < 120 and num_cpus <= 32 else FAMILIES_N1

    machine_cpus = CPUS[idx]
    mem_cpu_ratio = mem_limit.asGB() / machine_cpus
    family = None
    while idx < len(CPUS) and not family:
        machine_cpus = CPUS[idx]
        mem_cpu_ratio = mem_limit.asGB() / machine_cpus
        for fam in machine_type_families:
            if mem_cpu_ratio <= GCP_MACHINES[fam]:
                family = fam
                break
        if not family:
            idx += 1

    if not family:
        raise UserReportError(returncode=UNKNOWN_ERROR,
                              message=f'GCP machine type for memory limit {mem_limit.asGB()}GB and {num_cpus} CPUs could not be found')

    return f'{family}-{machine_cpus}'
