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
elastic_blast/elasticblast.py - Base class for ElasticBlastXXX

Author: Victor Joukov (joukovv@ncbi.nlm.nih.gov)
Created: Tue 03 Aug 2021 06:54:30 PM EDT
"""

from typing import Any, List
from .elb_config import ElasticBlastConfig
from .constants import ElbStatus
from abc import ABCMeta, abstractmethod

class ElasticBlast(metaclass=ABCMeta):
    """ Base class for core ElasticBLAST functionality. """
    def __init__(self, cfg: ElasticBlastConfig, create=False, cleanup_stack: List[Any]=None):
        self.cfg = cfg
        self.cleanup_stack = cleanup_stack if cleanup_stack else []
        self.dry_run = self.cfg.cluster.dry_run

    @abstractmethod
    def cloud_query_split(self, query_files: List[str]) -> None:
        """ Submit the query sequences for splitting to the cloud.
            Parameters:
                query_files - list of files containing query sequence data to split
        """
        self.query_files = query_files

    @abstractmethod
    def wait_for_cloud_query_split(self) -> None:
        """ Wait for cloud query job comletion """
        pass

    @abstractmethod
    def upload_query_length(self, query_length: int) -> None:
        """ Save query length in a metadata file in cloud storage """
        pass

    @abstractmethod
    def check_job_number_limit(self, queries, query_length) -> None:
        """ Check that number of jobs generated does not exceed platform maximum
            If the platform-specific maximum is exceeded throws UserReportError(INPUT_ERROR) """
        pass

    @abstractmethod
    def status(self) -> ElbStatus:
        """ Return the status of an ElasticBLAST search """
        pass

    @abstractmethod
    def delete(self) -> ElbStatus:
        """ Delete all resources allocated for an ElasticBLAST search """
        pass

    @abstractmethod
    def submit(self, query_batches: List[str], one_stage_cloud_query_split: bool) -> None:
        """ Submit query batches to cluster, converts AWS exceptions to UserReportError
            Parameters:
                query_batches               - list of bucket names of queries to submit
                one_stage_cloud_query_split - do the query split in the cloud as a part
                                              of executing a regular job """
        pass
