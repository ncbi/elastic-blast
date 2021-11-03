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
elastic_blast/elasticblast_factory.py - Factory for ElasticBlastXXX

Author: Victor Joukov (joukovv@ncbi.nlm.nih.gov)
Created: Mon 13 Sep 2021 05:17:00 PM EDT
"""

from elastic_blast.aws import ElasticBlastAws
from elastic_blast.constants import CSP
from elastic_blast.elasticblast import ElasticBlast
from elastic_blast.elb_config import ElasticBlastConfig
from elastic_blast.gcp import ElasticBlastGcp


def ElasticBlastFactory(cfg: ElasticBlastConfig, create: bool, cleanup_stack):
    if cfg.cloud_provider.cloud == CSP.AWS:
        elastic_blast: ElasticBlast = ElasticBlastAws(cfg, create, cleanup_stack)
    elif cfg.cloud_provider.cloud == CSP.GCP:
        elastic_blast = ElasticBlastGcp(cfg, create, cleanup_stack)
    else:
        raise NotImplementedError(f'Provider {cfg.cloud_provider.cloud} is not supported yet')
    return elastic_blast
