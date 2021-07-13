#!/usr/bin/env python3
"""
create-blastdb-metadata.py - See DESC constant below

Author: Irena Zaretskaya (zaretska@ncbi.nlm.nih.gov)
Created: Fri 4 Sep 2020 02:05:56 PM EST
"""
import os
import time
import argparse
import glob
import configparser
import unittest
import logging
import json
import subprocess
import re
import datetime
from pathlib import Path
import tempfile
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional
from tempfile import NamedTemporaryFile


DFLT_LOGFILE = 'create-blastdb-metadata.log'

ERROR_DEPENDENCY = 3
ERROR_DATABASE_INFO = 2
ERROR_DATABASE_NOT_FOUND = 1

DESC = r"""
This program creates BLAST database metadata in JSON format.
"""

"""
Arguments: --db [database]
--logfile [logfile, default:create-blastdb-metadata.log]


Dependencies:
* BLAST+ command line applications


"""

# BLAST database metadata version
BLASTDB_METADATA_VERSION = '1.1'


class DataCollection(Enum):
    """Types of metadata collection from file system"""
    UNCOMPRESSED_FILES = auto()
    CACHED_FILES = auto()


class DbType(Enum):
    """Database molecule type"""
    PROTEIN = 'prot'
    NUCLEOTIDE = 'nucl'

    @classmethod
    def choices(self):
        return [self.PROTEIN.value, self.NUCLEOTIDE.value]


    def __str__(self):
        """Convert value to a string"""
        return self.value


@dataclass
class BlastDbMetadata:
    """Class that holds database metadata information"""
    dbname: str
    version: str = BLASTDB_METADATA_VERSION
    dbtype: str = ''
    description: str = ''
    number_of_letters: int = 0
    number_of_sequences: int = 0
    files: List[str] = field(default_factory=list)
    last_updated: str = ''
    bytes_total: int = 0
    bytes_to_cache: int = 0
    number_of_volumes: int = 0

    def to_json(self, pretty = False):
        """Serialize the object as JSON"""
        output = json.dumps(self, cls=BlastDbMetadataEncoder, sort_keys=False)
        #rename '_' to '-' in keys
        dict = json.loads(output)
        current_keys = list(dict.keys())
        for current_key in current_keys:
            new_key = current_key.replace('_','-')
            dict[new_key] = dict.pop(current_key)
        if pretty:
            output = json.dumps(dict,sort_keys=False, indent=2)
        else:
            output = json.dumps(dict,sort_keys=False)

        return output


class UserReportError(Exception):
    """Exception wich is reported to the user as an error message and exit code"""
    def __init__(self, returncode: int, message: str):
        """Initialize parameters"""
        self.returncode = returncode
        self.message = message

    def __str__(self):
        """Conversion to a string"""
        return self.message


class BlastDbMetadataEncoder(json.JSONEncoder):
    """JSON encoder"""
    def default(self, obj):
        if isinstance(obj, BlastDbMetadata):
            return obj.__dict__
        else:
            return json.JSONEncoder.default(self, obj)


def get_database_info(oneDBJson: BlastDbMetadata, db: Path, dbtype: DbType,
                      file_prefix: Optional[str] = None) -> None:
    """
    Initialize database metadata

    Arguments:
        oneDBJson: object that holds metadata
        db: path plus database name
        dbtype: database molecule type
        file_prefix: if not None, path prefix for database files in metadata
    """
    # get number of volumes
    # this is called first to verify that we are dealing with a proper BLAST
    # database
    cmd = f'blastdbcmd -db {db} -dbtype {dbtype} -info'.split()
    logging.debug(f'Getting number of volumes for {db} CMD: {cmd}')
    try:
        p = subprocess.run(cmd, check=True, stdout = subprocess.PIPE,
                           stderr = subprocess.PIPE)

        lines = p.stdout.decode().split('\n')
        for num, line in enumerate(lines):
            if line.startswith('Volumes:'):
                oneDBJson.number_of_volumes = len(lines) - num - 2
                break

    except subprocess.CalledProcessError as err:
        raise UserReportError(returncode=ERROR_DATABASE_INFO,
                              message=f'{err.stdout.decode().strip()}\n{err.stderr.decode().strip()}')
    except PermissionError:
        raise UserReportError(returncode=ERROR_DEPENDENCY,
                              message='blastdbcmd application could not be executed')


    # get other database information
    # blastdbcmd -list fails for alias files and works with a directory, where
    # additional files may cause it to fail. To avoid problems we create
    # symlinks to database file in a temporary directory and work with them.
    dbfiles = db.parent.glob(f'{db.name}.*[np]??')
    with tempfile.TemporaryDirectory() as tmp:
        logging.debug(f'Creating symlinks to database file in {tmp}')
        # create symlinks, dbfile.resolve() finds an absolute path
        for dbfile in dbfiles:
            (Path(tmp) / dbfile.name).symlink_to(dbfile.resolve())

        cmd = f'blastdbcmd -list {tmp} -dbtype {dbtype} -remove_redundant_dbs -list_outfmt'.split() +  ['%f\t%p\t%t\t%l\t%n\t%d\t%U']
        logging.debug("Getting uncompressed database " + str(db) + " information. CMD: " + ' '.join(cmd))
        try:
            p = subprocess.run(cmd, check=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)

            for line in p.stdout.decode().split('\n'):
                fields = line.rstrip().split('\t')
                if os.path.basename(fields[0]) != db.name:
                    continue

                oneDBJson.dbtype = fields[1]
                oneDBJson.description = fields[2]
                oneDBJson.number_of_letters = int(fields[3])
                oneDBJson.number_of_sequences = int(fields[4])
                oneDBJson.last_updated = convert_date_to_iso8601(fields[5])
                oneDBJson.bytes_total = int(fields[6])
                break
        except subprocess.CalledProcessError as err:
            raise UserReportError(returncode=ERROR_DATABASE_INFO,
                                  message=f'{err.stdout.decode().strip()}\n{err.stderr.decode().strip()}')
        except ValueError as err:
            raise UserReportError(returncode=ERROR_DATABASE_INFO,
                                  message=f'Error when parsing database informtation: {err}')
        except PermissionError:
            raise UserReportError(returncode=ERROR_DEPENDENCY,
                                  message='blastdbcmd application could not be executed')

    if not oneDBJson.dbtype:
        # this happens when database is in BLASTDB path, but the path to the
        # database was not provided
        raise UserReportError(returncode=ERROR_DATABASE_INFO,
                              message=f'Database "{db}" was not found. Please, provide path to the database.')

    populate_db_info(oneDBJson, db, DataCollection.UNCOMPRESSED_FILES, file_prefix)
    try:
        populate_db_info(oneDBJson, db, DataCollection.CACHED_FILES, file_prefix)
    except FileNotFoundError as err:
        # if blastdbcmd above worked and database files are missing we are
        # very likely dealing with an alias database
        raise UserReportError(returncode=ERROR_DATABASE_INFO,
                              message=f'{err}. BLAST databases made of alias files that aggregate distinct databases are not supported.')
    logging.debug("Success getting uncompressed database " + str(db) + " information.")

    
def populate_db_info(oneDBJson: BlastDbMetadata, db: Path,
                     data2collect: DataCollection,
                     file_prefix: Optional[str]) -> None:
    """
    Get and populate database information from the filesystem.

    Arguments:
        oneDBJson: object holding database metadata
        db: database path plus name
        data2collect: type of information to gather
        file_prefix: if not None, path prefix for database files in metadata
    """
    dbtype = oneDBJson.dbtype[0].lower()
    if data2collect == DataCollection.UNCOMPRESSED_FILES:
        pattern = '.*' + dbtype + '??'
    elif data2collect == DataCollection.CACHED_FILES:
        pattern = '.*' + dbtype + '[si][qn]'
    else:
        raise NotImplementedError(f'Invalid data collection type {data2collect}')

    fileFound = False       
    
    logging.debug("Searching " + str(db)  + pattern)
    for f in glob.glob(str(db) + pattern):
        if not os.path.islink(f):
            if data2collect == DataCollection.UNCOMPRESSED_FILES:
                filename_parts = os.path.splitext(f)
                if filename_parts[1] == ".md5" or filename_parts[1] == ".gz":
                    continue
                db_file = os.path.basename(f)
                if file_prefix:
                    db_file = os.path.join(file_prefix, db_file)
                oneDBJson.files.append(db_file)
            else:
                oneDBJson.bytes_to_cache += os.stat(f).st_size
            fileFound = True
            
    if not fileFound:
        raise FileNotFoundError(f'Database files: {db}{pattern} not found in {db.parent}')
        
    # include additional CDD files
    # CSeqDB does not know about these files, so their size is not
    # reported by blastdbcmd -list
    for ff in db.parent.glob(db.name + '.*'):
        if data2collect == DataCollection.UNCOMPRESSED_FILES:
            if ff.suffix in ['.aux', '.loo', '.rps', '.freq']:
                db_file = ff.name
                if file_prefix:
                    db_file = os.path.join(file_prefix, ff.name)
                oneDBJson.files.append(db_file)
                oneDBJson.bytes_total += ff.stat().st_size
        else:
            if ff.suffix in ['.loo', '.rps', '.freq']:
                oneDBJson.bytes_to_cache += ff.stat().st_size


def convert_date_to_iso8601(date: str) -> str:
    """Convert a date in human readable format to ISO-8501"""
    months = {'Jan': '01',
              'Feb': '02',
              'Mar': '03',
              'Apr': '04',
              'May': '05',
              'Jun': '06',
              'Jul': '07',
              'Aug': '08',
              'Sep': '09',
              'Oct': '10',
              'Nov': '11',
              'Dec': '12'}

    m = re.findall('([A-Z][a-z]{2})\s(\d{1,2}),\s(\d{4})', date)
    if not m or len(m[0]) < 3:
        raise ValueError(f'The date string "{date}" could not be parsed')

    day = m[0][1]
    month = months[m[0][0]]
    year = m[0][2]

    return f'{year}-{month}-{int(day):02}'


def get_blast_version() -> str:
    """Get BLAST+ version"""
    cmd = 'blastdbcmd -version'.split()
    try:
        p = subprocess.run(cmd, check=True, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)

    except subprocess.CalledProcessError as err:
        raise UserReportError(returncode=ERROR_DEPENDENCY,
                              message=f'Unexpected error when checking BLAST+ version')
    except PermissionError:
        raise UserReportError(returncode=ERROR_DEPENDENCY,
                              message='blastdbcmd application could not be executed')

    return p.stdout.decode().split('\n')[0].split()[1][:-1]


def main():
    """ Entry point into this program. """
    parser = create_arg_parser()
    args = parser.parse_args()
        
    config_logging(args)

    db = Path(args.db)
    dbtype = DbType(args.dbtype.lower())
    oneDBJson = BlastDbMetadata(db.name)
    get_database_info(oneDBJson, db, dbtype, args.output_prefix)
    output_file_name = f'{db.name}-{dbtype}-metadata.json'
    if args.out:
        output_file_name = args.out
    with open(output_file_name, 'wt') as output_file:
        print(oneDBJson.to_json(args.pretty), file=output_file)
    logging.debug(f'Metadata printed to {output_file_name}')

    return 0


def create_arg_parser():
    """ Create the command line options parser object for this script. """
    parser = argparse.ArgumentParser(description=DESC)
    parser._action_groups.pop()
    required = parser.add_argument_group('required arguments')
    optional = parser.add_argument_group('optional arguments')

    required.add_argument("--db", metavar='DBNAME', type=str, help="A BLAST database", required=True)
    required.add_argument("--dbtype", type=str,
                        help="Database molecule type", choices=DbType.choices(),
                        required=True)
    optional.add_argument('--out', metavar='FILENAME', help='Output file name. Default: ${db}-${dbtype}-metadata.json')
    optional.add_argument('--output-prefix', metavar='PATH', type=str, help='Path prefix for location of database files in metadata')
    optional.add_argument("--pretty", action='store_true', help="Pretty-print JSON output")
    optional.add_argument("--logfile", default=DFLT_LOGFILE,help="Default: " + DFLT_LOGFILE)
    optional.add_argument("--loglevel", default='INFO',choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    optional.add_argument('--version', action='version', version=f'%(prog)s {get_blast_version()}')
    return parser


def config_logging(args):
    """Configure logging"""
    if args.logfile == 'stderr':
        logging.basicConfig(level=str2ll(args.loglevel),
                            format="%(asctime)s %(message)s")
    else:
        logformat_for_file = "%(asctime)s %(levelname)s: %(message)s"
        logformat_for_stderr = "%(levelname)s: %(message)s"

        logger = logging.getLogger()
        logger.setLevel(str2ll(args.loglevel))

        # to stderr
        handler = logging.StreamHandler()
        handler.setLevel(logging.WARNING)
        handler.setFormatter(logging.Formatter(logformat_for_stderr))
        logger.addHandler(handler)

        # to a file
        handler = logging.FileHandler(args.logfile, mode='a')
        handler.setLevel(str2ll(args.loglevel))
        handler.setFormatter(logging.Formatter(logformat_for_file))
        logger.addHandler(handler)


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
    import sys
    try:
        sys.exit(main())
    except UserReportError as err:
        logging.error(err.message)
        sys.exit(err.returncode)


import contextlib
import io
import sys
from unittest.mock import patch


class TestCreateDbMetadata(unittest.TestCase):
    "Unit tests for create-blastdb-metadata tool"""

    def test_metadata_version(self):
        """Test that metadata version is set correctly"""
        obj = BlastDbMetadata('some-db')
        json_str = obj.to_json()
        d = json.loads(json_str)
        self.assertEqual(d['version'], BLASTDB_METADATA_VERSION)


    def test_cmd_line_options(self):
        """Test command line parameters parsing"""
        parser = create_arg_parser()

        # minimal parameters
        parser.parse_args(['--db', 'some-db', '--dbtype', 'prot'])

        # --db is required
        with contextlib.redirect_stderr(io.StringIO()) as f:
            with self.assertRaises(SystemExit):
                parser.parse_args(['abc'])
            message = f.getvalue()
            self.assertTrue('required' in message)
            self.assertTrue('--db' in message)
            self.assertTrue('--dbtype' in message)

        # --help and --version should work
        # arparse raises SystemExit withe exit code 0 here
        with contextlib.redirect_stdout(io.StringIO()) as f:
            try:
                parser.parse_args(['--help'])
                parser.parse_args(['--version'])
            except SystemExit:
                pass


    def test_run(self):
        """Test main function with a sample database"""
        # path test database
        db = str(Path(__file__).parent.parent / 'tests/blastdb/testdb')

        with NamedTemporaryFile() as output_file:
            with patch.object(argparse.ArgumentParser, 'parse_args', return_value=argparse.Namespace(db=db, dbtype='prot', out=output_file.name, logfile='stderr', loglevel='ERROR', pretty=None, output_prefix=None)):
                main()
            with open(output_file.name, 'rt') as metadata:
                output = metadata.read()
            result = json.loads(output)
            self.assertEqual(result['version'], BLASTDB_METADATA_VERSION)
            self.assertEqual(result['dbname'], 'testdb')
            self.assertEqual(result['dbtype'], 'Protein')
            self.assertEqual(result['description'], 'Test database: the first four sequences for swissprot')
            self.assertEqual(result['number-of-letters'], 875)
            self.assertEqual(result['number-of-sequences'], 3)
            self.assertEqual(result['last-updated'], '2021-06-17')
            self.assertEqual(result['bytes-total'], 50956)
            self.assertEqual(result['bytes-to-cache'], 1039)
            self.assertEqual(result['number-of-volumes'], 1)
            self.assertEqual(len(result['files']), 9)
            self.assertEqual(len([s for s in result['files'] if s.startswith('testdb.')]), len(result['files']))


    def test_output_prefix(self):
        """Test main function with a sample database and --output-prefix option"""
        # path to test database
        db = str(Path(__file__).parent.parent / 'tests/blastdb/testdb')
        PREFIX = 'gs://some-bucket/some-dir'

        with NamedTemporaryFile() as output_file:
            with patch.object(argparse.ArgumentParser, 'parse_args', return_value=argparse.Namespace(db=db, dbtype='prot', out=output_file.name, logfile='stderr', loglevel='ERROR', pretty=None, output_prefix=PREFIX)):
                main()
            with open(output_file.name, 'rt') as metadata:
                output = metadata.read()
            result = json.loads(output)
            self.assertEqual(len([s for s in result['files'] if s.startswith(PREFIX)]), len(result['files']))


    def test_concert_date_to_iso8601(self):
        """Test converting date to ISO8601 format"""
        self.assertEqual(convert_date_to_iso8601('May 18, 2021  4:21 AM'), '2021-05-18')

        with self.assertRaises(ValueError):
            convert_date_to_iso8601('Some string that is not a date')
