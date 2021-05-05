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
Tools to track GCP costs using billing data exported to BigQuery.

Author: Greg Boratyn boratyng@ncbi.nlm.nih.gov
"""

import subprocess
import io
import re
from itertools import islice


#FIXME: return codes should be defined somwhere else
# exit codes
BQ_ERROR = 1
NO_RESULTS_ERROR = 2
CMD_ARGS_ERROR = 3

# default BigQuery dataset and table to be searched
DFLT_BQ_DATASET = 'NIHSGCNLMNCBI'
DFLT_BQ_TABLE = 'gcp_billing_export_v1_0164A6_0C026C_669C6E'

def get_cost(label, date_range = None, dataset = DFLT_BQ_DATASET,
             table = DFLT_BQ_TABLE, verbose = None):
    """Do a BigQuery search and get costs for GCP resources with a given label
    Parameters:
        label - GCP resource lable as 'key:value'
        date_range - range of dates to limit the search (optional)
        dataset - BigQuery dataset id
        table - BigQuery table
        verbose - if not None verpose information will be printed
    Returns:
        a list of costs"""
    kv = label.split(':')

    # check that label is provided in the approrpiate format
    if len(kv) != 2:
        raise ValueError('Run label not in correct format, must be: <key>:<value>')

    # split label into key and value
    key, value = kv

    partition = ''
    if date_range is not None:
        # check that date range is in the appropriate format
        if not re.match(r'^\d{4}-\d{2}-\d{2}:\d{4}-\d{2}-\d{2}$', date_range):
            raise ValueError('Incorrect date range format, must be: yyyy-mm-dd:yyyy-mm-dd')
            
        date_from, date_to = date_range.split(':')
        partition = f"""(_PARTITIONTIME BETWEEN TIMESTAMP('{date_from}') AND TIMESTAMP('{date_to}'))
    AND """

    # query to run
    query = f"""
SELECT cost
FROM {dataset}.{table}
WHERE {partition} (SELECT count(1) FROM UNNEST(labels) AS pair WHERE pair IN (('{key}', '{value}'))) >= 1"""

    if verbose:
        print('Running this query:')
        print(query.strip())
        print('')

    # run command line BigQuery tool
    cmd = 'bq query --use_legacy_sql=false --format csv --max_rows 2147483647'
    cmd = cmd.split() + [query]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # if BigQuery client exited with an error, throw
    if p.returncode != 0:
        raise RuntimeError('BigQuery error: ' + p.stderr.decode() + p.stdout.decode())

    # otherwise return results
    results = []
    with io.BytesIO(p.stdout) as f:
        for line in islice(f, 1, None):
            fields = line.decode().rstrip().split(',')
            results.append(float(fields[0]))
    return results

