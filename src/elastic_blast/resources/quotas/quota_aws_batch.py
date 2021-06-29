#!/usr/bin/env python3
"""
src/elb/resources/quotas/quota_aws_batch.py - Module to check AWS Batch
resource availability

Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
Created: Tue 22 Sep 2020 10:37:01 AM EDT
"""
import logging
import boto3 # type: ignore
from pprint import pformat
from botocore.config import Config  # type: ignore
from elastic_blast.util import UserReportError
from elastic_blast.constants import DEPENDENCY_ERROR

OUT_OF_QUOTA_ERR_MSG = 'ElasticBLAST cannot create the necessary AWS resources ({}) to run your search. Please run elastic-blast delete on searches that have already completed.'

class ResourceCheckAwsBatch:
    """ Class to encapsulate retrieval of AWS Batch service quotas, current
    usage and whether this suffices to run ElasticBLAST 
    """
    _service_codes = [ 'batch' ]
    _service_quotas = {
        'Job queue limit': -1,
        'Compute environment limit': -1
    }

    def __init__(self, boto_cfg: Config = None):
        """ Initialize this object with AWS connections and service quotas 
        boto_cfg: boto3 library configuration
        """
        self.client = boto3.client('service-quotas') if boto_cfg is None else boto3.client('service-quotas', config=boto_cfg)
        self.batch = boto3.client('batch') if boto_cfg is None else boto3.client('batch', config=boto_cfg)
        self._initialize_service_quotas()


    def _initialize_service_quotas(self) -> None:
        """ Retrieves the service quotas relevant to ElasticBLAST """
        for svc in self._service_codes:
            done = False
            next_token = ''
            while not done:
                if next_token:
                    response = self.client.list_service_quotas(ServiceCode=svc, NextToken=next_token)
                else:
                    response = self.client.list_service_quotas(ServiceCode=svc)
                for q in response['Quotas']:
                    for quota_name in self._service_quotas.keys():
                        if quota_name == q['QuotaName']:
                            self._service_quotas[quota_name] = q['Value']
                if 'NextToken' in response:
                    next_token = response['NextToken']
                else: 
                    done = True
                    
        logging.debug(f'AWS Batch service quotas: {pformat(self._service_quotas)}')


    def _count_aws_batch_compute_environments(self) -> int:
        """ Count the number of AWS Batch compute environments """
        done = False
        next_token = ''
        count = 0
        while not done:
            if next_token:
                response = self.batch.describe_compute_environments(nextToken=next_token)
            else:
                response = self.batch.describe_compute_environments()
            #logging.debug(f'AWS Batch describe_compute_environments response: {pformat(response)}')
            for ce in response['computeEnvironments']:
                count += 1
            if 'nextToken' in response:
                next_token = response['nextToken']
            else: 
                done = True
        return count


    def _count_aws_batch_job_queues(self) -> int:
        """ Count the number of AWS Batch job queues """
        done = False
        next_token = ''
        count = 0
        while not done:
            if next_token:
                response = self.batch.describe_job_queues(nextToken=next_token)
            else:
                response = self.batch.describe_job_queues()
            #logging.debug(f'AWS Batch describe_job_queues response {pformat(response)}')
            for ce in response['jobQueues']:
                count += 1
            if 'nextToken' in response:
                next_token = response['nextToken']
            else: 
                done = True
        return count


    def __call__(self) -> None:
        """ Retrieve the current usage of the relevant AWS Batch resources and compare it with the service quotas.
        Throws a UserReportError if there aren't enough resources available to run ElasticBLAST
        """
        njq = self._count_aws_batch_job_queues()
        nce = self._count_aws_batch_job_queues()
        logging.debug(f'AWS Batch usage: number of job queues {njq}')
        logging.debug(f'AWS Batch usage: number of compute environments {nce}')
        
        if njq + 1 >= self._service_quotas['Job queue limit']:
            raise UserReportError(DEPENDENCY_ERROR, OUT_OF_QUOTA_ERR_MSG.format('batch job queue'))
        if nce + 1 >= self._service_quotas['Compute environment limit']:
            raise UserReportError(DEPENDENCY_ERROR, OUT_OF_QUOTA_ERR_MSG.format('batch compute environment'))
