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

from elastic_blast.aws import ElasticBlastAws
from elastic_blast.gcp import delete_cluster_with_cleanup, enable_gcp_api
from elastic_blast.gcp import remove_split_query, remove_ancillary_data
from elastic_blast.constants import ELB_LOG_DIR, ELB_METADATA_DIR, CSP, ElbCommand
from elastic_blast.elb_config import ElasticBlastConfig

# TODO: use cfg only when args.wait, args.sync, and args.run_label are replicated in cfg
def delete(args, cfg, clean_up_stack):
    """ Entry point to delete resources associated with an ElasticBLAST search """
    cfg.validate(ElbCommand.DELETE)
    if cfg.cloud_provider.cloud == CSP.AWS:
        elastic_blast = ElasticBlastAws(cfg)
        elastic_blast.delete()
    else:
        enable_gcp_api(cfg)
        delete_cluster_with_cleanup(cfg)
        remove_split_query(cfg)
        remove_ancillary_data(cfg, ELB_LOG_DIR)
        remove_ancillary_data(cfg, ELB_METADATA_DIR)
    return 0
