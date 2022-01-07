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
# elastic-blast-janitor.sh: Script to monitor the status of an ElasticBLAST
# search and delete is when done or once there's a failed BLAST job.
# This script works only on GCP.
#
# Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
# Created: Wed Sep 15 09:42:44 EDT 2021

set -euo pipefail
shopt -s nullglob

# Exit codes for elastic-blast status --exit-code from constants.py::ElbStatus
SUCCESS=0    # Cluster computation finished successfully
FAILURE=1    # There was a failure in the process
CREATING=2   # Cloud resources are being allocated/created
SUBMITTING=3 # Jobs are being submitted
RUNNING=4    # Jobs are running
DELETING=5   # Cluster is being deleted
UNKNOWN=6    # Cluster is unknown to the system


if [ -z "${ELB_RESULTS+x}" ] ; then
    echo "$0 FATAL ERROR: Missing ELB_RESULTS environment variable"
    exit 1
fi
if [ -z "${ELB_CLUSTER_NAME+x}" ] ; then
    echo "$0 FATAL ERROR: Missing ELB_CLUSTER_NAME environment variable"
    exit 1
fi
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

DRY_RUN=''
GSUTIL='gsutil'
KUBECTL='kubectl'
if [ ! -z "${ELB_DRY_RUN+x}" ] ; then
    echo "ELB_DRY_RUN was in the environment"
    DRY_RUN='--dry-run'
    GSUTIL='echo gsutil'
    KUBECTL='echo kubectl'
fi

export ELB_LOGLEVEL=DEBUG
export ELB_LOGFILE=stderr

TMP=`mktemp`
trap " /bin/rm -fr $TMP " INT QUIT EXIT HUP KILL ALRM

exit_code=$SUCCESS
result=`elastic-blast status --exit-code --verbose` || exit_code=$?

case $exit_code in
    $SUCCESS)
        echo Success, deleting cluster
        if ! gsutil -q stat ${ELB_RESULTS}/metadata/FAILURE.txt; then
            echo '' | $GSUTIL -q cp - ${ELB_RESULTS}/metadata/SUCCESS.txt
            set +e
            $KUBECTL get jobs -o json | $GSUTIL -q cp - ${ELB_RESULTS}/metadata/SUCCESS_details.json
        fi
        elastic-blast delete ${DRY_RUN}
        ;;
    $FAILURE)
        echo Failed, deleting cluster
        if ! gsutil -q stat ${ELB_RESULTS}/metadata/FAILURE.txt; then
            echo $result | $GSUTIL -q cp - ${ELB_RESULTS}/metadata/FAILURE.txt
            set +e
            $KUBECTL get jobs -o json | $GSUTIL -q cp - ${ELB_RESULTS}/metadata/FAILURE_details.json
        fi
        elastic-blast delete ${DRY_RUN}
        ;;
    $CREATING)
        echo Cluster is being created
        ;;
    $SUBMITTING)
        echo Cluster jobs are being submitted
        ;;
    $RUNNING)
        echo Cluster jobs are running
        ;;
    $DELETING)
        echo Cluster is being deleted
        ;;
    $UNKNOWN)
        echo Cluster state is unknown
        ;;
esac
