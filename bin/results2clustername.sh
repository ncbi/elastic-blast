#!/bin/bash
# results2clustername.sh: Script to convert ElasticBLAST results to the default
# cluster name
#
# Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
# Created: Thu 08 Apr 2021 04:07:29 PM EDT

if [ $# -ne 1 ] ; then
    echo "Usage: $0 <ElasticBLAST results path>"
    exit 1
fi
elb_results=$1
md5=md5sum
command -v $md5 >& /dev/null || md5=md5
results_hash=$(printf $elb_results | $md5 | cut -b-9)
echo elasticblast-$USER-$results_hash
