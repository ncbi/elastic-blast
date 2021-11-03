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
elb/comands/delete.py - delete cluster

Author: Victor Joukov joukovv@ncbi.nlm.nih.gov
"""

from typing import Any, List

from elastic_blast.elasticblast_factory import ElasticBlastFactory
from elastic_blast.constants import ElbCommand
from elastic_blast.elb_config import ElasticBlastConfig

# TODO: use cfg only when args.wait, args.sync, and args.run_label are replicated in cfg
def delete(args, cfg: ElasticBlastConfig, clean_up_stack: List[Any]) -> int:
    """ Entry point to delete resources associated with an ElasticBLAST search """
    cfg.validate(ElbCommand.DELETE)
    elastic_blast = ElasticBlastFactory(cfg, False, clean_up_stack)
    elastic_blast.delete()
    return 0
