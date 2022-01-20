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
import math
from typing import Optional
from .filehelper import open_for_read
from .constants import BLASTDB_ERROR, INPUT_ERROR
from .constants import UNKNOWN_ERROR, MolType, CSP
from .constants import ELB_S3_PREFIX, ELB_GCS_PREFIX
from .constants import SYSTEM_MEMORY_RESERVE, MEMORY_FOR_BLAST_HITS
from .constants import ELB_DFLT_AWS_REGION
from .constants import ELB_DFLT_AWS_NUM_CPUS, ELB_DFLT_GCP_NUM_CPUS
from .base import DBSource, PositiveInteger, MemoryStr
from .util import UserReportError, get_query_batch_size, ElbSupportedPrograms
from .aws_traits import get_instance_type_offerings, get_suitable_instance_types
from .aws_traits import get_machine_properties as aws_get_machine_properties
from .aws_traits import create_aws_config
from .gcp_traits import GCP_MACHINES
from .gcp_traits import get_machine_properties as gcp_get_machine_properties
from .db_metadata import DbMetadata


@dataclass
class SeqData:
    """Basic sequence information"""
    length: int
    moltype: MolType


@dataclass
class DbData(SeqData):
    """Database information"""
    bytes_to_cache_gb: float

    @classmethod
    def from_metadata(cls, db_metadata: DbMetadata):
        """Create an object from a database metadata object"""
        obj = cls(length = db_metadata.number_of_letters,
                  moltype = MolType[db_metadata.dbtype.upper()],
                  bytes_to_cache_gb = max((db_metadata.bytes_to_cache / (1024 ** 3), 1)))
        return obj


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

# Minimum query length for MT mode 1
MIN_MT_ONE_QUERY_LENGTH_BLASTN = 2500000
MIN_MT_ONE_QUERY_LENGTH_BLASTP = 10000
MIN_MT_ONE_QUERY_LENGTH_BLASTX = 20004

# Maximum database length for MT mode 1
MAX_MT_ONE_DB_LENGTH_PROT = int(2e9)
MAX_MT_ONE_DB_LENGTH_NUCL = int(14e9)

# Number of threads for MT mode 0
NUM_THREADS_MT_ZERO_AWS = 16
NUM_THREADS_MT_ZERO_GCP = 15

# Maximum number of threads to use per BLAST job
MAX_NUM_THREADS_AWS = 16
MAX_NUM_THREADS_GCP = 15


def get_mt_mode(program: str, options: str = '', db_metadata: DbMetadata = None,
                query: SeqData = None) -> MTMode:
    """
    Compute BLAST search MT mode

    Arguments:
        program: BLAST program
        options: BLAST options (empty string for defaults)
        db: Database metadata
        query: Queries information
    """
    if query:
        if (program.lower() == 'blastn' and query.length < MIN_MT_ONE_QUERY_LENGTH_BLASTN) or \
            (program.lower() == 'blastp' and query.length < MIN_MT_ONE_QUERY_LENGTH_BLASTP) or \
            (program.lower() == 'blastx' and query.length < MIN_MT_ONE_QUERY_LENGTH_BLASTX):
            return MTMode.ZERO

    if program.lower() == 'rpsblast' or program.lower() == 'rpstblastn':
        return MTMode.ONE
    elif program.lower() in ['tblastn', 'tblastx', 'psiblast']:
        return MTMode.ZERO

    if '-taxids' in options or '-taxidlist' in options:
        return MTMode.ONE

    if db_metadata:
        db = DbData.from_metadata(db_metadata)
        if program.lower() == 'blastp':
            if db_metadata.number_of_letters < 5e8:
                return MTMode.ONE
            else:
                return MTMode.ZERO

        if (db.moltype == MolType.PROTEIN and db.length <= MAX_MT_ONE_DB_LENGTH_PROT) or \
           (db.moltype == MolType.NUCLEOTIDE and db.length <= MAX_MT_ONE_DB_LENGTH_NUCL):
            return MTMode.ONE

    return MTMode.ZERO


def get_num_cpus(cloud_provider: CSP, program: str, mt_mode: MTMode, query: SeqData = None) -> int:
    """Get number of CPUs to use to optimally run BLAST

    Arguments:
        program: BLAST program
        mt_mode: BLAST MT mode
        query: Queries information"""
    if mt_mode == MTMode.ZERO:
        return NUM_THREADS_MT_ZERO_AWS if cloud_provider == CSP.AWS else NUM_THREADS_MT_ZERO_GCP
    elif not query:
        return ELB_DFLT_AWS_NUM_CPUS if cloud_provider == CSP.AWS else ELB_DFLT_GCP_NUM_CPUS
    else:
        characters_per_thread = RESIDUES_PER_THREAD if query.moltype == MolType.PROTEIN else BASES_PER_THREAD
        num_cpus = query.length // characters_per_thread
        if query.length % characters_per_thread > 0:
            num_cpus += 1
        if cloud_provider == CSP.AWS:
            return min([num_cpus, MAX_NUM_THREADS_AWS])
        else:
            return min([num_cpus, MAX_NUM_THREADS_GCP])


def get_batch_length(cloud_provider: CSP, program: str, mt_mode: MTMode,
                     num_cpus: int, db_metadata: DbMetadata = None) -> int:
    """
    Get batch length for BLAST batch search

    Arguments:
        cloud_provider: Cloud provider
        program: BLAST program
        mt_mode: BLAST MT mode
        num_cpus: Number of threads/CPUs to use
        db_metadata: BLAST database metadata
    """
    batch_len = get_query_batch_size(program)
    if batch_len is None:
        raise UserReportError(returncode=INPUT_ERROR,
                              message=f"Invalid BLAST program '{program}'")

    if mt_mode  == MTMode.ONE:
        moltype = ElbSupportedPrograms().get_query_mol_type(program)
        if moltype == MolType.UNKNOWN:
            raise UserReportError(returncode=INPUT_ERROR,
                                  message=f"Invalid BLAST program '{program}'")
        max_num_cpus = MAX_NUM_THREADS_AWS if cloud_provider == CSP.AWS else MAX_NUM_THREADS_GCP
        batch_len *= min((num_cpus, max_num_cpus))
        if program.lower() == 'rpsblast' or program.lower() == 'blastp':
            batch_len *= 2
    else:
        # MTMode.ZERO
        if db_metadata:
            if program.lower() == 'blastp':
                batch_len = 20000
                if db_metadata.number_of_letters < 2e10:
                    batch_len = 40000
            elif program.lower() == 'blastx':
                if db_metadata.number_of_letters < 2e10:
                    batch_len = int(1e5)
                else:
                    batch_len = 30000
            elif program.lower() == 'tblastn':
                if db_metadata.number_of_letters < 1e8:
                    batch_len = 320000
                elif db_metadata.number_of_letters < 2e10:
                    batch_len = 40000
                else:
                    batch_len = 20000
            elif program.lower() == 'tblastx':
                if db_metadata.number_of_letters < 1e8:
                    batch_len = 400000
                elif db_metadata.number_of_letters < 2e10:
                    batch_len = 100000
                else:
                    batch_len = 10000

    return batch_len


def aws_get_mem_limit(num_cpus: PositiveInteger, 
        machine_type: str,
        db: Optional[DbData] = None, 
        db_factor: float = 0.0, 
        region: str = ELB_DFLT_AWS_REGION) -> float:
    """Get memory limit for searching a single query batch for AWS

    Arguments:
        num_cpus: Number of CPUs per search job
        db: Database information
        machine_type: Machine type (can be "optimal")
        db_factor: If larger than 0, memory limit will be computed as database
                   bytes-to-cache times db_factor

    Returns:
        A search job memory limit in GB as float"""
    if db_factor > 0.0:
        if not db:
            raise ValueError('The "db" parameter must be provided if db_factor > 0.0')
        return round(db.bytes_to_cache_gb * db_factor, 1)
    elif machine_type == 'optimal':
        if not db:
            raise ValueError('The "db" parameter must be provided if machine_type == "optimal"')
        result = 60 if db.bytes_to_cache_gb >= 60 else db.bytes_to_cache_gb + MEMORY_FOR_BLAST_HITS
        return result
    else:
        boto_cfg = create_aws_config(region)
        props = aws_get_machine_properties(machine_type, boto_cfg)
        jobs_per_instance = math.floor(props.ncpus / num_cpus)
        mem_limit = (props.memory - SYSTEM_MEMORY_RESERVE) / jobs_per_instance
        return int(mem_limit * 10) / 10


def gcp_get_mem_limit(machine_type: str) -> float:
    """Get memory limit for searching a single query batch for GCP. Kubernetes
    schedules jobs based on CPU and memory request, so memory limit for each
    job can be as high as instance RAM.

    Arguments:
        machine_type: Machine type

    Returns:
        A search job memory limit int GB as float"""
    try:
        props = gcp_get_machine_properties(machine_type)
    except NotImplementedError as err:
        raise UserReportError(returncode=INPUT_ERROR,
                              message=f'Invalid machine type. Machine type name "{machine_type}" is incorrect or not supported by ElasticBLAST: {str(err)}')

    mem_limit = props.memory - SYSTEM_MEMORY_RESERVE
    return mem_limit


def get_mem_limit(cloud_provider: CSP, machine_type: str, num_cpus: PositiveInteger,
        db: Optional[DbData] = None, db_factor: float = 0.0, cloud_region: str = ELB_DFLT_AWS_REGION) -> MemoryStr:
    """Get memory limit for searching a single query batch, wrapper over
    functions specialized for each cloud provider. See aws_get_mem_limit and
    gcp_get_mem_limit for details on how memory limit is computed on each
    platform.

    Arguments:
        cloud_provider: Cloud provider
        machine_type: Instance type
        num_cpus: Number of CPUs for a search job
        db: Database information
        db_factor: If larger than 0, memory limit will be computed as database
                   bytes-to-cache times db_factor

    Returns:
        A search job memory limit as MemoryStr"""
    region = cloud_region
    if cloud_provider == CSP.AWS:
        mem_limit = aws_get_mem_limit(num_cpus, machine_type, db, db_factor, cloud_region)
    else:
        mem_limit = gcp_get_mem_limit(machine_type)

    if mem_limit <= 0:
        raise UserReportError(returncode=INPUT_ERROR,
                              message=f'The selected machine type {machine_type}: does not have enough memory to run the search. Please, select machine type with more memory.')

    return MemoryStr(f'{mem_limit}G')


def aws_get_machine_type(memory: MemoryStr, num_cpus: PositiveInteger, region: str) -> str:
    """Select an AWS machine type that can accommodate the database and has
    enough VCPUs. The machine type is selected from a set of machines supported
    by AWS Batch and offered in a specific region.

    Arguments:
        memory: Required memory
        num_cpus: Required number of CPUs
        region: Cloud provided region

    Returns:
        An AWS instance type with at least memory RAM and num_cpus vCPUs"""
    M5_FAMILY = ['m5ad.large', 'm5ad.xlarge'] + [f'm5ad.{i}xlarge' for i in [2, 4, 8, 12, 16, 24]]
    C5_FAMILY = ['c5ad.large', 'c5ad.xlarge'] + [f'c5ad.{i}xlarge' for i in [2, 4, 8, 12, 16, 24]]
    R5_FAMILY = ['r5ad.large', 'r5ad.xlarge'] + [f'r5ad.{i}xlarge' for i in [2, 4, 8, 12, 16, 24]]
    SUPPORTED_INSTANCE_TYPES = M5_FAMILY + C5_FAMILY + R5_FAMILY

    # get a list of instance types offered in the region
    offerings = get_instance_type_offerings(region)

    supported_offerings = [tp for tp in offerings if tp in SUPPORTED_INSTANCE_TYPES]

    # get properties of suitable instances
    suitable_props = get_suitable_instance_types(min_memory=memory,
                                                 min_cpus=num_cpus,
                                                 instance_types=supported_offerings)
    if not suitable_props:
        raise UserReportError(returncode = UNKNOWN_ERROR,
                              message = f'An AWS machine type with memory {memory.asGB()}GB and {num_cpus} CPUs could not be found')

    # sort first by number of CPUs, then by memory
    suitable_props = sorted(suitable_props, key=lambda x: x['VCpuInfo']['DefaultVCpus'])
    return sorted(suitable_props, key=lambda x: x['MemoryInfo']['SizeInMiB'])[0]['InstanceType']


def gcp_get_machine_type(memory: MemoryStr, num_cpus: PositiveInteger) -> str:
    """Select a GCP machine type that can accommodate the database and has
    enough VCPUs. The instance type is selected from E2 and N1 instance
    families. One job per instance is assumed.

    Arguments:
        memory: Required memory
        num_cpus: Required number of CPUs

    Returns:
        A GCP instance type with at least memory RAM and num_cpus vCPUs"""
    # machine type families ranked by memory to CPU ratio (order matters)
    FAMILIES_N1 = ['n1-highcpu',
                   'n1-standard',
                   'n1-highmem']

    FAMILIES_E2 = ['e2-standard', 'e2-highmem']

    # numbers of CPUs in GCP instance types
    CPUS = [1, 2, 4, 8, 16, 32, 64, 96]

    # 1 CPU per instance must be left for kubernetes
    idx = bisect_left(CPUS, num_cpus + 1)
    if idx >= len(CPUS):
        raise UserReportError(returncode=UNKNOWN_ERROR,
                              message=f'GCP machine type with {num_cpus} CPUs could not be found')

    # E2 machine types are usually the cheapest, but have at most 128GB memory
    machine_type_families = FAMILIES_E2 if memory.asGB() < 120 and num_cpus <= 32 else FAMILIES_N1

    machine_cpus = CPUS[idx]
    mem_cpu_ratio = memory.asGB() / machine_cpus
    family = None
    while idx < len(CPUS) and not family:
        machine_cpus = CPUS[idx]
        mem_cpu_ratio = memory.asGB() / machine_cpus
        for fam in machine_type_families:
            if mem_cpu_ratio <= GCP_MACHINES[fam]:
                family = fam
                break
        if not family:
            idx += 1

    if not family:
        raise UserReportError(returncode=UNKNOWN_ERROR,
                              message=f'GCP machine type with memory {memory.asGB()}GB and {num_cpus} CPUs could not be found')

    return f'{family}-{machine_cpus}'


def get_machine_type(cloud_provider: CSP, db: DbMetadata, num_cpus: PositiveInteger, mt_mode: MTMode, db_mem_margin: float, region: str) -> str:
    """Select a machine type that can accommodate the database and has enough
    vCPUs.

    Arguments:
        cloud_provider: Cloud service provider
        db: Database metadata
        num_cpus: Number of CPUs per BLAST search job
        mt_mode: Multi-threading mode
        region: Cloud service provider region

    Returns:
        Instance type with at enough memory for BLAST to work and required
        number of CPUs"""
    db_data = DbData.from_metadata(db)

    # find memory required for BLAST to work (excluding cached database)
    MIN_OPS_MEMORY_GB = 10
    MAX_OPS_MEMORY_GB = 60
    ops_memory_gb = db_data.bytes_to_cache_gb * (db_mem_margin - 1)
    if mt_mode == MTMode.ONE:
        ops_memory_gb *= num_cpus
    ops_memory_gb = min(MAX_OPS_MEMORY_GB, max(MIN_OPS_MEMORY_GB, ops_memory_gb))
    memory = MemoryStr(f'{db_data.bytes_to_cache_gb + ops_memory_gb + SYSTEM_MEMORY_RESERVE}G')

    if cloud_provider == CSP.AWS:
        return aws_get_machine_type(memory, num_cpus, region)
    else:
        return gcp_get_machine_type(memory, num_cpus)
