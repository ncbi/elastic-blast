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
from .filehelper import open_for_write
from .constants import ELB_QUERY_BATCH_DIR, ELB_TAXIDLIST_FILE, INPUT_ERROR
from .util import UserReportError
from .elb_config import ElasticBlastConfig 

re_taxidlist_parse = re.compile(r'-(?P<negative>negative_)?(taxidlist)\s+(?P<filename>(\S+))')

def setup_taxid_filtering(cfg: ElasticBlastConfig) -> None:
    """ Upload a taxid list file to results bucket under a standard name.
        Processes the following -taxidlist and -negative_taxidlist options in
        blast.options parameter. """

    matches = re.findall(r'-(negative_)?(taxid(?:list|s))(?:\s+(\S+))?',
                         cfg.blast.options)
    # nothing to do, if taxid filtering was not requested
    if not matches:
        return

    # report an error if more than one taxid filtering option was used
    if len(matches) > 1:
        raise UserReportError(
            returncode=INPUT_ERROR,
            message='BLAST -taxids, -taxidlist, -negative_taxids, and -negative_taxidlist options '
                    'are mutually exclusive, please use only one of them')

    m = re_taxidlist_parse.search(cfg.blast.options)
    if m:
        local_filename = m.group('filename')
        filename = '/'.join([cfg.cluster.results, ELB_QUERY_BATCH_DIR, ELB_TAXIDLIST_FILE])
        logging.debug(f'Uploading taxid list file {local_filename} to {filename}')
        with open_for_write(filename) as fout:
            with open(local_filename) as fin:
                for line in fin:
                    fout.write(line)

        # update blast options
        cfg.blast.taxidlist = filename
        blast_opts = cfg.blast.options

        # replace user's taxidlist file with our taxidlist filename, to avoid
        # checks for proper cloud object names
        blast_opts = re_taxidlist_parse.sub(f'-\\g<negative>taxidlist {ELB_TAXIDLIST_FILE}', blast_opts)
        cfg.blast.options = blast_opts
