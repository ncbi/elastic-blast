#!/usr/bin/env python3
"""
src/elb/resources/quotas/quota_aws_ec2_cf.py - Module to check AWS resource
availability in EC2 and CloudFormation

Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
Created: Mon 14 Sep 2020 10:37:01 AM EDT
"""
import logging
from awslimitchecker.checker import AwsLimitChecker # type: ignore
from elastic_blast.util import UserReportError
from elastic_blast.constants import DEPENDENCY_ERROR
from elastic_blast.elb_config import ElasticBlastConfig


class ResourceCheckAwsEc2CloudFormation:
    """ Class to encapsulate retrieval of EC2 and CloudFormation service quotas, current
    usage and whether this suffices to run ElasticBLAST 
    """

    def __init__(self, cfg: ElasticBlastConfig, boto_cfg = None):
        """ Initialize this object AwsLimitChecker object.
        cfg: ElasticBLAST config
        boto_cfg: boto3 library configuration
        """
        self.checker = AwsLimitChecker() if boto_cfg is None else AwsLimitChecker(region=boto_cfg.region_name)
        self.cfg = cfg


    def __call__(self):
        """ Retrieve the current usage of the relevant AWS resources and compare it with the service quotas.
        Throws a UserReportError if there aren't enough resources available to run ElasticBLAST
        """
        self.check_cpus()

        SERVICES = [ 'EC2', 'CloudFormation' ]
        result = self.checker.check_thresholds(service=SERVICES)
        if not result:
            # No service thresholds were exceeded :)
            return

        fatal_errors = ''
        warnings = ''
        for svc_name in result.keys():
            for usage_metric in result[svc_name].keys():
                if svc_name == 'EC2' and not usage_metric.startswith('Running On-Demand'):
                    continue
                aws_limit = result[svc_name][usage_metric]
                criticals = aws_limit.get_criticals()
                warnings = aws_limit.get_warnings()
                if len(criticals):
                    for c in criticals:
                        fatal_errors += f'{svc_name} metric "{usage_metric}" has reached a critical usage level ({c}) that is too close to the limit ({aws_limit.get_limit()}) to run ElasticBLAST. '
                elif len(warnings):
                    for w in warnings:
                        warnings += f'{svc_name} metric "{usage_metric}" has reached a level of usage ({w}) that is close to the limit ({aws_limit.get_limit()}) and may run into problems. '
        if fatal_errors:
            raise UserReportError(DEPENDENCY_ERROR, fatal_errors)
        if warnings:
            logging.warning(warnings)


    def check_cpus(self):
        """Check that the quota on number of vCPUs allows to create at least
        one worker node. Raises UserReportError if the quota is smaller than
        number of vCPUs in a single instance."""
        # A negative value indicates that the optimal instance type was
        # selected and we will not know the number of vCPUs until the AWS
        # Batch cluster is created.
        if self.cfg.cluster.num_cores_per_instance <= 0:
            return

        result = self.checker.get_limits(service=['EC2'])
        if self.cfg.cluster.use_preemptible:
            keys = [k for k in result['EC2'].keys() if k.startswith('All Standard') and 'Spot Instance' in k]
        else:
            keys = [k for k in result['EC2'].keys() if k.startswith('Running On-Demand All Standard') and 'instances' in k]

        if len(keys) == 1:
            key = keys[0]
            limit = result['EC2'][key].get_limit()
            if limit < self.cfg.cluster.num_cores_per_instance:
                raise UserReportError(DEPENDENCY_ERROR, f'Your account has a quota limit of {limit} vCPUs. The instance type selected to run BLAST searches: {self.cfg.cluster.machine_type} has more vCPUs: {self.cfg.cluster.num_cores_per_instance}, and cannot be initiated. Please, increase your quota "{key}" in service "EC2". See https://docs.aws.amazon.com/servicequotas/latest/userguide/request-quota-increase.html or https://repost.aws/knowledge-center/ec2-instance-limit for more information on requesting a quota increase. Alternatively use a smaller instance type, which may require searching a smaller database.')
            if limit < self.cfg.cluster.num_cores_per_instance * self.cfg.cluster.num_nodes:
                logging.warning(f'ElasticBLAST is configured to use up to {self.cfg.cluster.num_cores_per_instance * self.cfg.cluster.num_nodes} vCPUs, but only up to {limit} can be used in your account. This impacts how much work can ElasticBLAST parallelize, and thus search speed. ElasticBLAST will use up to {limit} vCPUs. For information on how to increase your vCPU quota, please see https://aws.amazon.com/premiumsupport/knowledge-center/ec2-instance-limit/')
        else:
            logging.warning('EC2 CPU limit was not found or there are multiple matching limits')
