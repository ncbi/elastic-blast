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

import logging
import os
from abc import ABCMeta, abstractmethod
from typing import Any, List, Tuple, Dict

from .constants import ELB_QUERY_BATCH_DIR
from .filehelper import copy_to_bucket, remove_bucket_key, cleanup_temp_bucket_dirs
from .elb_config import ElasticBlastConfig
from .constants import ElbStatus

class ElasticBlast(metaclass=ABCMeta):
    """ Base class for core ElasticBLAST functionality. """
    def __init__(self, cfg: ElasticBlastConfig, create=False, cleanup_stack: List[Any]=None):
        self.cfg = cfg
        self.cleanup_stack = cleanup_stack if cleanup_stack else []
        self.dry_run = self.cfg.cluster.dry_run
        # If we request no search for debugging purposes we can't engage
        # cloud job submission
        self.cloud_job_submission = 'ELB_DISABLE_JOB_SUBMISSION_ON_THE_CLOUD' not in os.environ and \
            'ELB_NO_SEARCH' not in os.environ

    @abstractmethod
    def cloud_query_split(self, query_files: List[str]) -> None:
        """ Submit the query sequences for splitting to the cloud.
            Parameters:
                query_files - list of files containing query sequence data to split
        """

    @abstractmethod
    def wait_for_cloud_query_split(self) -> None:
        """ Wait for cloud query split job completion """

    @abstractmethod
    def upload_query_length(self, query_length: int) -> None:
        """ Save query length in a metadata file in cloud storage """

    @abstractmethod
    def submit(self, query_batches: List[str], query_length, one_stage_cloud_query_split: bool) -> None:
        """ Submit query batches to cluster
            Parameters:
                query_batches               - list of bucket names of queries to submit
                query_length                - total query length
                one_stage_cloud_query_split - do the query split in the cloud as a part
                                              of executing a regular job """

    @abstractmethod
    def check_status(self, extended=False) -> Tuple[ElbStatus, Dict[str, int], str]:
        """ Check execution status of ElasticBLAST search
        Parameters:
            extended - do we need verbose information about jobs
        Returns:
            tuple of
                status - cluster status, ElbStatus
                counts - job counts for all job states
                verbose_result - detailed info about jobs
        """

    # Compatibility method, used now only in janitor.py
    def status(self) -> ElbStatus:
        """ Return the status of an ElasticBLAST search """
        return self.check_status()[0]

    @abstractmethod
    def delete(self) -> None:
        """ Delete cluster and associated resources and workfiles """

    def upload_workfiles(self):
        """ Upload workfiles - query batches, taxidslist etc to their
            appropriate places in the results bucket """
        self.cleanup_stack.append(lambda: logging.debug('Before copying split jobs to bucket'))
        if not self.cloud_job_submission:
            self.cleanup_stack.append(cleanup_temp_bucket_dirs)
        copy_to_bucket(self.dry_run)
        self.cleanup_stack.append(lambda: logging.debug('After copying split jobs to bucket'))
