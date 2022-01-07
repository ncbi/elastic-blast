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
elastic_blast/db_metadata.py - Spec and funtions for reading database metadata

Created: Wed 11 Aug 2021 02:45:09 PM EDT
Author: Greg Boratyn (boratyng@ncbi.nlm.nih.gov)
"""

import os
import logging
from dataclasses import dataclass
from dataclasses_json import dataclass_json, Undefined, LetterCase
from json.decoder import JSONDecodeError
from marshmallow.exceptions import ValidationError
from typing import List
from .constants import MolType, ELB_S3_PREFIX, ELB_GCS_PREFIX, BLASTDB_ERROR
from .filehelper import open_for_read, check_for_read
from .base import DBSource
from .util import UserReportError

# ignore new json fields
# change dashes to underscores in json keys
@dataclass_json(undefined=Undefined.EXCLUDE, letter_case=LetterCase.KEBAB)
@dataclass
class DbMetadata:
    """BLAST database metadata"""
    version: str
    dbname: str
    dbtype: str
    description: str
    number_of_letters: int
    number_of_sequences: int
    files: List[str]
    last_updated: str
    bytes_total: int
    bytes_to_cache: int
    number_of_volumes: int


def get_db_metadata(db: str, dbtype: MolType, source: DBSource, dry_run: bool = False) -> DbMetadata:
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

    # metadata file suffixes
    metadata_suffix_v11 = f'-{dbtype}-metadata.json'
    metadata_suffix_v12 = f'.{str(dbtype)[0]}js'

    db_path = db

    # if an NCBI-provided database
    if not db.startswith(ELB_S3_PREFIX) and not db.startswith(ELB_GCS_PREFIX):
        if source == DBSource.AWS or source == DBSource.GCP:
            bucket = DB_BUCKET_AWS if source == DBSource.AWS else DB_BUCKET_GCP
            try:
                with open_for_read(f'{bucket}/latest-dir') as f:
                    db_path = os.path.join(f'{bucket}/{f.readline().rstrip()}', db)
            except:
                raise UserReportError(returncode=BLASTDB_ERROR, message=f'File "{bucket}/latest-dir" could not be read')
        else:
            db_path = os.path.join(f'{DB_BUCKET_NCBI}', db)
    # try metadata file version 1.2 first; if not found try version 1.1
    try:
        metadata_file = f'{db_path}{metadata_suffix_v12}'
        logging.debug(f'BLASTDB metadata file: {metadata_file}')
        check_for_read(metadata_file, dry_run)
    except FileNotFoundError:
        metadata_file = f'{db_path}{metadata_suffix_v11}'
        logging.debug(f'BLASTDB metadata file: {metadata_file}')
        check_for_read(metadata_file, dry_run)

    try:
        with open_for_read(metadata_file) as f:
            lines = f.readlines()
            if isinstance(lines[0], bytes):
                lines = [s.decode() for s in lines]
            db_metadata = DbMetadata.schema().loads(''.join(lines)) # type: ignore
    except JSONDecodeError as err:
        raise UserReportError(returncode=BLASTDB_ERROR,
                              message=f'BLAST database metadata file "{metadata_file}" is not a proper JSON file: {err}')
    except ValidationError as err:
        raise UserReportError(returncode=BLASTDB_ERROR,
                              message=f'Problem parsing BLAST database metadata file "{metadata_file}": {err}')
    except KeyError as err:
        raise UserReportError(returncode=BLASTDB_ERROR,
                              message=f'Missing field {err} in BLAST database metadata file "{metadata_file}"')
    return db_metadata

