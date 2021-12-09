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
#
# Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
# Created: Wed Sep 15 09:42:44 EDT 2021

set -euo pipefail
shopt -s nullglob

if [ -z "${ELB_RESULTS+x}" ] ; then
    echo "$0 FATAL ERROR: Missing ELB_RESULTS environment variable"
    exit 1
fi
if [ -z "${ELB_CLUSTER_NAME+x}" ] ; then
    echo "$0 FATAL ERROR: Missing ELB_CLUSTER_NAME environment variable"
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

DRY_RUN=''
AWS_CLI='aws'
GSUTIL='gsutil'
KUBECTL='kubectl'
if [ ! -z "${ELB_DRY_RUN+x}" ] ; then
    echo "ELB_DRY_RUN was in the environment"
    DRY_RUN='--dry-run'
    AWS_CLI='echo aws'
    GSUTIL='echo gsutil'
    KUBECTL='echo kubectl'
fi

export ELB_LOGLEVEL=DEBUG
export ELB_LOGFILE=stderr

TMP=`mktemp`
trap " /bin/rm -fr $TMP " INT QUIT EXIT HUP KILL ALRM

init_failed=false

GCP_SENTINEL_JOB='submit-jobs'

if [[ ${ELB_RESULTS} =~ ^gs:// ]]; then
    if gsutil -q stat ${ELB_RESULTS}/metadata/FAILURE.txt; then
        init_failed=true
    elif ! gsutil -q stat ${ELB_RESULTS}/metadata/num_jobs_submitted.txt; then
        gcloud container clusters get-credentials ${ELB_CLUSTER_NAME} --project ${ELB_GCP_PROJECT} --zone ${ELB_GCP_ZONE}
        s=`$KUBECTL get jobs ${GCP_SENTINEL_JOB} -o jsonpath='{.status.conditions[*].type}'`
        if [ $? -ne 0 ]; then
            echo "kubectl failed to get status of jobs: ${s}"
            exit 1
        fi
        if [ "x$s" != "xComplete" ]; then
            if [ "x$s" == "xFailed" ]; then
                echo ${GCP_SENTINEL_JOB} failed | $GSUTIL -q cp - ${ELB_RESULTS}/metadata/FAILURE.txt
                set +e
                $KUBECTL get jobs ${GCP_SENTINEL_JOB} -o json | $GSUTIL -q cp - ${ELB_RESULTS}/metadata/FAILURE_details.txt
                for c in get-blastdb import-query-batches; do
                    $KUBECTL logs -l 'job-name=init-pv' -c $c --timestamps --since=24h --tail=-1 | $GSUTIL -q cp - ${ELB_RESULTS}/logs/k8s-init-pv-$c.log
                done
                $KUBECTL logs -l 'job-name=submit-jobs' -c submit-jobs --timestamps --since=24h --tail=-1 | $GSUTIL -q cp - ${ELB_RESULTS}/logs/k8s-submit-jobs.log
                elastic-blast delete --results ${ELB_RESULTS} --gcp-project ${ELB_GCP_PROJECT} --gcp-region ${ELB_GCP_REGION} --gcp-zone ${ELB_GCP_ZONE}
            fi
            exit 0
        fi
    fi
fi

if $init_failed; then
    num_failed=1
    num_pending=0
    num_succeeded=0
    num_running=0
else
    elastic-blast status --verbose | tee $TMP

    num_failed=`grep '^Failed ' $TMP | cut -f 2 -d ' '`;
    num_pending=`grep '^Pending ' $TMP | cut -f 2 -d ' '`;
    num_succeeded=`grep '^Succeeded ' $TMP | cut -f 2 -d ' '`;
    num_running=`grep '^Running ' $TMP | cut -f 2 -d ' '`;
fi
num_jobs=$(($num_failed + $num_pending + $num_succeeded + $num_running))

if [[ ${ELB_RESULTS} =~ ^s3:// ]]; then
    # Jobs have not been submitted yet, do not delete cluster prematurely
    [ $num_jobs -eq 0 ] && exit 0
fi


if [ $((num_pending + num_running)) -eq 0 ]; then
    echo "No jobs left, deleting cluster"
    if [[ ${ELB_RESULTS} =~ ^s3:// ]]; then
        $AWS_CLI s3 cp --only-show-errors $TMP ${ELB_RESULTS}/metadata/DONE.txt
    else
        if ! gsutil -q stat ${ELB_RESULTS}/metadata/FAILURE.txt; then
            $GSUTIL -qm cp $TMP ${ELB_RESULTS}/metadata/DONE.txt
            set +e
            $KUBECTL get jobs -o json | $GSUTIL -q cp - ${ELB_RESULTS}/metadata/DONE_details.json
        fi
    fi
    elastic-blast delete ${DRY_RUN}
fi

if [ $num_failed -gt 0 ] ; then
    echo "$num_failed job(s) failed, deleting cluster"
    if [[ ${ELB_RESULTS} =~ ^s3:// ]]; then
        $AWS_CLI s3 cp --only-show-errors $TMP ${ELB_RESULTS}/metadata/FAILURE.txt
    else
        $GSUTIL -qm cp $TMP ${ELB_RESULTS}/metadata/FAILURE.txt
        set +e
        $KUBECTL get jobs -o json | $GSUTIL -q cp - ${ELB_RESULTS}/metadata/FAILURE_details.json
    fi
    elastic-blast delete ${DRY_RUN}
fi
