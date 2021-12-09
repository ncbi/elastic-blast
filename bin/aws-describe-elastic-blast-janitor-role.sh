#!/bin/bash
# aws-describe-elastic-blast-janitor.sh: Describe the role to run the
# ElasticBLAST janitor on AWS
#
# Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
# Created: Tue Nov 30 08:09:03 EST 2021

export PATH=/bin:/usr/local/bin:/usr/bin
set -xuo pipefail
shopt -s nullglob

ROLE_NAME=ncbi-elasticblast-janitor-role
aws iam get-role --role-name $ROLE_NAME --output json
