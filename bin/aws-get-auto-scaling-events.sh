#!/bin/bash
# aws-get-auto-scaling-events.sh: Get autoscaling events for ElasticBLAST's
# AWS Batch compute environment
#
# Author: Greg Boratyn (borayng@ncbi.nlm.nih.gov)
# Created: Fri Aug 12 17:28:20 EDT 2022

# The script assumes that elastic-blast.log file exists
logfile=${1:-elastic-blast.log}
COMP_ENV_NAME=$(grep ComputeEnvName $logfile | tr '/' '\t' | cut -f 2 | tail -n 1)
if [ ! -z "${COMP_ENV_NAME}" ] ; then
    AUTO_SCALE_GRP_NAME=$(aws autoscaling describe-auto-scaling-groups --output json | jq -Mr '.AutoScalingGroups[].AutoScalingGroupName' | grep $COMP_ENV_NAME)
    if [ $? -eq 0 ] ; then
        aws autoscaling describe-scaling-activities --auto-scaling-group-name $AUTO_SCALE_GRP_NAME
    else
        echo "Failed to find an AWS auto scaling group for the AWS Batch Compute environment $COMP_ENV_NAME"
        exit 1
    fi
else
    echo "Failed to find an AWS Batch Compute environment in $logfile"
    exit 1
fi
