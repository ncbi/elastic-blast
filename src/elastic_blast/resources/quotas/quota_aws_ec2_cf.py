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


class ResourceCheckAwsEc2CloudFormation:
    """ Class to encapsulate retrieval of EC2 and CloudFormation service quotas, current
    usage and whether this suffices to run ElasticBLAST 
    """

    def __init__(self, boto_cfg = None):
        """ Initialize this object AwsLimitChecker object.
        boto_cfg: boto3 library configuration
        """
        self.checker = AwsLimitChecker() if boto_cfg is None else AwsLimitChecker(region=boto_cfg.region_name)


    def __call__(self):
        """ Retrieve the current usage of the relevant AWS resources and compare it with the service quotas.
        Throws a UserReportError if there aren't enough resources available to run ElasticBLAST
        """
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
