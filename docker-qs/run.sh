#!/bin/bash
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
#
# run.sh: 
#   For AWS - Splits FASTA and uploads it to S3
#   For GCP - depending on flags -c and -p
#             -p 0 (default) is used for network attached shared drive
#               if -c 0 (default) - splits query to local directory
#               if -c 1 - copies batched from GS to local directory
#             -p 1 -c 0 is used for local SSD cloud split, splits and copies batches to GS output bucket
#             -p 1 -c 1 is not used - it's tautology, so in case of client split with local SSD this job
#               is just ommitted
#
# Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
# Created: Wed Jul  7 13:42:14 EDT 2021

set -xeuo pipefail
shopt -s nullglob

k8s_job_limit=5000

batch_len=5000000
show_help=0
copy_only=0
split_to_cloud=0
input=''
output_bucket=''
local_output_dir='/blast/queries'

while getopts "o:i:b:c:q:p:h" OPT; do
    case $OPT in 
        b) batch_len=${OPTARG}
            ;;
        o) output_bucket=${OPTARG}
            ;;
        h) show_help=1
            ;;
        i) input=${OPTARG}
            ;;
        q) local_output_dir=${OPTARG}
            ;;
        c) copy_only=${OPTARG}
            ;;
        p) split_to_cloud=${OPTARG}
            ;;
    esac
done

[ -z "$output_bucket" ] && { echo "Missing OUTPUT_BUCKET argument"; show_help=1; }
[ -z "$input" ] && { echo "Missing INPUT argument"; show_help=1; }

[[ $copy_only -eq 1 ]] && [[ $split_to_cloud -eq 1 ]] && { echo "Options -c 1 and -p 1 must not be used together"; show_help=1; }

if [ $show_help -eq 1 ] ;then
    echo "Usage: $0 -i INPUT -o OUTPUT_BUCKET -b BATCH_LEN -p SPLIT_TO_CLOUD -c COPY_ONLY -q LOCAL_DIR_FOR_QUERIES"
    exit 0
fi

TMP=`mktemp`
if [[ $output_bucket =~ ^s3:// ]]; then
  time fasta_split.py $input -l $batch_len -o $output_bucket/query_batches -c $output_bucket/metadata/query_length.txt
  aws s3 ls $output_bucket/query_batches/batch_ | awk '{print $NF;}' > batch_list.txt
  time aws s3 cp batch_list.txt $output_bucket/metadata/batch_list.txt --only-show-errors
elif [[ $output_bucket =~ ^https:// ]]; then
  echo "Output bucket starts with https://"
  azcopy login --identity

  if [ $copy_only -eq 1 ]; then
    time azcopy cp "$output_bucket/query_batches/*" $local_output_dir --include-pattern "batch_*.fa"
  else
    time fasta_split.py $input -l $batch_len -o $local_output_dir -c $TMP
    num_batches=`find $local_output_dir -type f -name "batch_*.fa"|wc -l`
    query_length=`cat $TMP`
    if [ $num_batches -gt $k8s_job_limit ]; then
      suggested_batch_len=$(( (query_length + k8s_job_limit - 1) / k8s_job_limit ))
      echo "Your ElasticBLAST search has failed and its computing resources will be deleted.
The batch size specified ($batch_len) led to creating $num_batches kubernetes jobs, which exceeds the limit on number of jobs ($k8s_job_limit).
Please increase the batch-len parameter to at least $suggested_batch_len and repeat the search." >> msg
      azcopy cp msg $output_bucket/metadata/FAILURE.txt 
      rm msg
      exit 0
    else
      time azcopy cp $TMP $output_bucket/metadata/query_length.txt
      if [ $split_to_cloud -eq 1 ]; then
        azcopy cp "$local_output_dir/batch_*.fa" $output_bucket/query_batches/
      fi
    fi
  fi
  find $local_output_dir -type f -name "batch_*.fa" | xargs -n1 basename > batch_list.txt
  time azcopy cp batch_list.txt $output_bucket/metadata/batch_list.txt
  
else
  if [ $copy_only -eq 1 ]; then
    time gsutil -mq cp "$output_bucket/query_batches/batch_*.fa" $local_output_dir
  else
    time fasta_split.py $input -l $batch_len -o $local_output_dir -c $TMP
    num_batches=`find $local_output_dir -type f -name "batch_*.fa"|wc -l`
    query_length=`cat $TMP`
    if [ $num_batches -gt $k8s_job_limit ]; then
      suggested_batch_len=$(( (query_length + k8s_job_limit - 1) / k8s_job_limit ))
      gsutil -q cp - $output_bucket/metadata/FAILURE.txt <<EOF
Your ElasticBLAST search has failed and its computing resources will be deleted.
The batch size specified ($batch_len) led to creating $num_batches kubernetes jobs, which exceeds the limit on number of jobs ($k8s_job_limit).
Please increase the batch-len parameter to at least $suggested_batch_len and repeat the search.
EOF
      exit 0
    else
      time gsutil -qm cp $TMP $output_bucket/metadata/query_length.txt
      if [ $split_to_cloud -eq 1 ]; then
        gsutil -mq cp "$local_output_dir/batch_*.fa" $output_bucket/query_batches/
      fi
    fi
  fi
  find $local_output_dir -type f -name "batch_*.fa" | xargs -n1 basename > batch_list.txt
  time gsutil -qm cp batch_list.txt $output_bucket/metadata/batch_list.txt
fi
