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
Functions that facilitate taxonomic filtering of BLAST databases for elastic-blast searches.

Author: Greg Boratyn (boratyng@ncbi.nlm.nih.gov)
"""

import re
import logging
import urllib.parse
import urllib.request
from urllib.error import HTTPError
import time
from tenacity import retry, retry_if_exception_type, stop_after_attempt
from tenacity import wait_exponential

from .filehelper import open_for_write
from .constants import ELB_QUERY_BATCH_DIR, ELB_TAXIDLIST_FILE, INPUT_ERROR
from .util import UserReportError
from .elb_config import ElasticBlastConfig 

from typing import List, Dict


# retry function up to 3 times if utllib.errors.HTTPError occurs
@retry(retry=retry_if_exception_type(HTTPError), reraise=True, stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def entrez_query(tool: str, query: Dict[str, str]) -> str:
    """Run NCBI entrez query using e-utils.

    Arguments:
        tool: E-utils tool (esearch, efetch, esummary, etc.)
        query: Entrez query as a dictionary of key-value pairs

    Returns:
        Response from E-utils tool as a string.
    """
    EUTILS_BASE_URL = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
    data = urllib.parse.urlencode(query).encode('ascii')
    url = EUTILS_BASE_URL + tool + '.fcgi'
    request = urllib.request.Request(url, data)
    with urllib.request.urlopen(request) as response:
        result = response.read()
    result = result.decode()
    return result
    

def get_species_taxids(user_taxids: List[int]) -> List[int]:
    """Get species level taxonomy ids for a given list of taxonomy ids.

    Arguments:
        user_taxids: A list of taxonomy ids

    Returns:
        A list of species level taxonomy ids"""

    species_taxids = []
    for taxid in user_taxids:

        logging.debug(f'Getting species level taxids for {taxid}')

        # esearch
        result = entrez_query('esearch', {'db': 'taxonomy',
                                          'term': f'txid{taxid}[orgn]',
                                          'usehistory': 'y'})

        # report an error if taxid is invalid
        if 'PhraseNotFound' in result:
            raise UserReportError(returncode=INPUT_ERROR,
                                  message=f'"{taxid}" is not a valid taxonomy id')

        webenvs = re.findall(r'<WebEnv>(\S+)</WebEnv>', result)
        query_keys = re.findall(r'<QueryKey>(\S+)</QueryKey>', result)
        if not webenvs or not query_keys:
            raise UserReportError(returncode=INPUT_ERROR,
                                  message=f'Unexpected error while searching for species level taxids for "{taxid}"')
        webenv = webenvs[0]
        query_key = query_keys[0]

        # efetch
        result = entrez_query('efetch', {'db': 'taxonomy',
                                         'WebEnv': webenv,
                                         'query_key': query_key,
                                         'format': 'uid'})

        species_taxids += [int(num) for num in re.findall(r'(\d+)', result)]
        # E-utils allows up to 3 requests per second
        if len(user_taxids) > 1:
            time.sleep(1)

    return sorted(species_taxids)

# Parse taxid options - -taxids, -taxidlist, -negative_taxids, and -negative_taxidlist
# into triplets:
# prefix - '' or 'negative_'
# opt_type - taxids or taxidlist
# opt_val  - value of the option, possibly empty
re_taxid_parse = re.compile(f'-(negative_)?(taxid(?:list|s))(?:\\s+(\\S+))?')

def setup_taxid_filtering(cfg: ElasticBlastConfig) -> None:
    """ Prepare taxonomy id list for taxonomy filtering
        Processes the following options in blast.options parameter:
            -taxids, -taxidlist - for positive filtering,
            -negative_taxids, -negative_taxidlist - for negative filtering
        Only one of these options can be set at a time, as
        they are mutually exclusive in BLAST+
    """
    user_taxids = get_user_taxids(cfg.blast.options)

    if user_taxids:
        # get species level taxids ans save them to a file that will be
        # uploaded to cloud storage
        logging.debug('Preparing taxid filtering')
        filename = '/'.join([cfg.cluster.results, ELB_QUERY_BATCH_DIR, ELB_TAXIDLIST_FILE])
        with open_for_write(filename) as f:
            for taxid in get_species_taxids(user_taxids):
                f.write(str(taxid))
                f.write('\n')

        # update blast options
        cfg.blast.taxidlist = filename
        blast_opts = cfg.blast.options
        # Here we can be sure taxid option happens only once,
        # it was tested in get_user_taxids
        matches = re_taxid_parse.findall(blast_opts)
        neg_prefix, _, _ = matches[0]
        # replace user's -taxid or -taxidlist options with -taxidlist with the
        # newly created species level taxid list
        blast_opts = re_taxid_parse.sub('', blast_opts)
        blast_opts += f' -{neg_prefix}taxidlist {ELB_TAXIDLIST_FILE}'
        cfg.blast.options = blast_opts
    else:
        logging.debug('No taxonomic filtering configuration provided')


def get_user_taxids(blast_opts: str) -> List[int]:
    """Extract user-provided taxids from -taxids or -taxidlist blast command
    line options and return as a list of ints.

    Arguments:
        blast_opts: blast command line options

    Returns:
        A list of taxonomy ids
    """
    matches = re_taxid_parse.findall(blast_opts)
    if not matches:
        return []
    if len(matches) > 1:
        raise UserReportError(
            returncode=INPUT_ERROR,
            message='BLAST -taxids, -taxidlist, -negative_taxids, and -negative_taxidlist options '
                    'are mutually exclusive, please use only one of them')
    taxids: List[int] = []
    neg_prefix, opt_type, opt_val = matches[0]
    if opt_type == 'taxids':
        # -taxids or -negative_taxids was used
        if not opt_val:
            raise UserReportError(
                returncode=INPUT_ERROR,
                message=f'No taxonomy ids found for the -{neg_prefix}taxids BLAST option')
        for val in opt_val.split(','):
            try:
                taxids.append(int(val))
            except ValueError:
                raise UserReportError(
                    returncode=INPUT_ERROR,
                    message=f'"{val}" in "-{neg_prefix}taxids {opt_val}" is an incorrect taxonomy id. '
                            'Taxonomy ids are positive integers.')
            
    else:
        # -taxidlist or -negative_taxidlistwas used
        filename = opt_val
        if not filename:
            raise UserReportError(
                returncode=INPUT_ERROR,
                message=f'A taxonomy id list file is missing for the -{neg_prefix}taxidlist BLAST option')
        try:
            with open(filename) as f:
                for line in f:
                    val = line.rstrip()
                    # skip empty lines
                    if not val:
                        continue
                    try:
                        taxids.append(int(val))
                    except ValueError:
                        raise UserReportError(
                            returncode=INPUT_ERROR,
                            message=f'"{val}" is an incorrect taxonomy id. '
                                    'Taxonomy ids are positive integers.')
        except FileNotFoundError:
            raise UserReportError(
                returncode=INPUT_ERROR,
                message=f'File "{filename}" with tax id list was not found')
        if not taxids:
            raise UserReportError(
                returncode=INPUT_ERROR,
                message=f'No taxonomy ids found in file "{filename}"')
    return taxids
