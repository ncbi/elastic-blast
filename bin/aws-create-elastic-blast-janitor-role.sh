#!/bin/bash
# aws-create-elastic-blast-janitor-role.sh: Create and tag role for running
# ElasticBLAST janitor on AWS
#
# Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
# Created: Mon Nov 29 17:29:31 EST 2021

export PATH=/bin:/usr/local/bin:/usr/bin
set -xeuo pipefail
shopt -s nullglob

ROLE_PATH=/app/ncbi/elasticblast/
ROLE_NAME=ncbi-elasticblast-janitor-role

TMP=`mktemp -t $(basename -s .sh $0)-XXXXXXX`
trap " /bin/rm -fr $TMP " INT QUIT EXIT HUP KILL ALRM

aws iam list-roles --path-prefix ${ROLE_PATH} --output text | tee $TMP
[ -s $TMP ] && { echo "Role $ROLE_PATH/$ROLE_NAME exists, exiting"; exit 0 ; }

# Create the trust policy file
cat >$TMP<<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "cloudformation.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

aws iam create-role --role-name ${ROLE_NAME} --path ${ROLE_PATH} \
    --assume-role-policy-document file://$TMP \
    --tags Key=Project,Value=BLAST Key=billingcode,Value=elastic-blast Key=Owner,Value=${USER} Key=Name,Value=${ROLE_NAME}

aws iam attach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AWSLambda_FullAccess
aws iam attach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AmazonVPCReadOnlyAccess
aws iam attach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess
aws iam attach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AWSBatchFullAccess
aws iam attach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AmazonEC2FullAccess
aws iam attach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/IAMFullAccess
aws iam attach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/AWSCloudFormationFullAccess
aws iam attach-role-policy --role-name ${ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/CloudWatchEventsFullAccess
