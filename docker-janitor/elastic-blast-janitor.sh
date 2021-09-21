#!/bin/bash
# elastic-blast-janitor.sh: Script to monitor the status of an ElasticBLAST
# search and delete is when done or once there's a failed BLAST job.
#
# Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
# Created: Tue 31 Aug 2021 09:29:12 AM EDT

set -euo pipefail
shopt -s nullglob

if [ -z "${ELB_RESULTS+x}" ] ; then
    echo "$0 FATAL ERROR: Missing ELB_RESULTS environment variable"
    exit 1
fi
if [[ ${ELB_RESULTS} =~ ^gs:// ]]; then
    if [ -z "${ELB_GCP_PROJECT+x}" ] ; then
        echo "$0 FATAL ERROR: Missing ELB_GCP_PROJECT environment variable"
        exit 1
    fi
    if [ -z "${ELB_GCP_REGION+x}" ] ; then
        echo "$0 FATAL ERROR: Missing ELB_GCP_REGION environment variable"
        exit 1
    fi
    if [ -z "${ELB_GCP_ZONE+x}" ] ; then
        echo "$0 FATAL ERROR: Missing ELB_GCP_ZONE environment variable"
        exit 1
    fi
fi

export ELB_LOGLEVEL=DEBUG
export ELB_LOGFILE=stderr

TMP=`mktemp`
trap " /bin/rm -fr $TMP " INT QUIT EXIT HUP KILL ALRM

elastic-blast status --verbose --logfile ${ELB_LOGFILE} | tee $TMP

if grep '^Pending 0' $TMP && grep '^Running 0' $TMP; then
    if [[ ${ELB_RESULTS} =~ ^s3:// ]]; then
        aws s3 cp --only-show-errors $TMP ${ELB_RESULTS}/metadata/DONE.txt
    else
        gsutil -qm cp $TMP ${ELB_RESULTS}/metadata/DONE.txt
    fi
    elastic-blast delete --logfile ${ELB_LOGFILE}
fi

num_failed=`grep '^Failed ' $TMP | cut -f 2 -d ' '`;
if [ $num_failed -gt 0 ] ; then
    if [[ ${ELB_RESULTS} =~ ^s3:// ]]; then
        aws s3 cp --only-show-errors $TMP ${ELB_RESULTS}/metadata/FAILURE.txt
    else
        gsutil -qm cp $TMP ${ELB_RESULTS}/metadata/FAILURE.txt
    fi
    elastic-blast delete --logfile ${ELB_LOGFILE}
fi
