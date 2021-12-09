#!/bin/bash
# aws-delete-elastic-blast-janitor-role.sh: Deletes IAM role to run
# ElasticBLAST janitor on AWS
#
# Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
# Created: Tue Nov 30 08:07:53 EST 2021

export PATH=/bin:/usr/local/bin:/usr/bin
set -xuo pipefail
shopt -s nullglob

ROLE_NAME=ncbi-elasticblast-janitor-role

aws iam get-role --role-name $ROLE_NAME >&/dev/null || exit 0
aws iam detach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AWSLambda_FullAccess
aws iam detach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AmazonVPCReadOnlyAccess
aws iam detach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess
aws iam detach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AWSBatchFullAccess
aws iam detach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AmazonEC2FullAccess
aws iam detach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/IAMFullAccess
aws iam detach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AWSCloudFormationFullAccess
aws iam detach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/CloudWatchEventsFullAccess
aws iam delete-role --role-name ${ROLE_NAME}
