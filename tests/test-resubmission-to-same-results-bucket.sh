#!/bin/bash
# tests/test-resubmission-to-same-results-bucket.sh: Perform an end-to-end
# ElasticBLAST blast search, interleaved with a submission to that uses the
# same results bucket to elicit an error message.
#
# Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
# Created: Wed 06 May 2020 06:59:03 AM EDT

SCRIPT_DIR=$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )
set -euo pipefail

# All other settings are specified in the config file
CFG=${1:-"${SCRIPT_DIR}/../share/etc/elb-blastn-pdbnt.ini"}
ROOT_DIR=${SCRIPT_DIR}/..
export ELB_DONT_DELETE_SETUP_JOBS=1
export BLAST_USAGE_REPORT=false

[ -f $CFG ] || { echo "ElasticBLAST configuration file $CFG doesn't exist"; exit 1; }

export ELB_RESULTS="gs://elasticblast-${USER}/test-resubmission-`date +%s`"
if grep -qs ^aws $CFG ; then
    export ELB_RESULTS="s3://elasticblast-${USER}/test-resubmission-`date +%s`"
fi

DRY_RUN=''
#DRY_RUN=--dry-run     # uncomment for debugging
timeout_minutes=${2:-5}

logfile=${3:-elb.log}
rm -f $logfile

errmsgfile=err.msg
rm -f $errmsgfile

cleanup_resources_on_error() {
    set +e
    echo Cleanup on error
    if grep -q '^aws-' $CFG; then
        $ROOT_DIR/elastic-blast delete --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN
    fi
    exit 1;
}

TMP=`mktemp -t $(basename -s .sh $0)-XXXXXXX`
trap "cleanup_resources_on_error; /bin/rm -f $TMP" INT QUIT HUP KILL ALRM ERR
if [ ! -z "${ELB_TC_BRANCH+x}" ] ; then
    if grep -q ^labels $CFG; then
        sed -i~ -e "s@\(^labels.*\)@\1,branch=$ELB_TC_BRANCH@" $CFG
    else
        sed -i~ -e "/^\[cluster\]/a labels = branch=$ELB_TC_BRANCH" $CFG
    fi
fi

if [ ! -z "${ELB_TC_BRANCH+x}" ] ; then
    if grep -q ^labels $CFG; then
        sed -i~ -e "s@\(^labels.*\)@\1,branch=$ELB_TC_BRANCH@" $CFG
    else
        sed -i~ -e "/^\[cluster\]/a labels = branch=$ELB_TC_BRANCH" $CFG
    fi
fi

echo Submit first time
$ROOT_DIR/elastic-blast submit --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN
sleep 5
echo Submit second time
# This should fail, grab the error message to check later
$ROOT_DIR/elastic-blast submit --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN 2>$errmsgfile || true

attempts=0
[ ! -z "$DRY_RUN" ] || sleep 10    # Should be enough for the BLAST k8s jobs to get started

echo Check status
while [ $attempts -lt $timeout_minutes ]; do
    $ROOT_DIR/elastic-blast status --verbose --cfg $CFG $DRY_RUN | tee $TMP
    #set +e
    if grep '^Pending 0' $TMP && grep '^Running 0' $TMP; then
        break
    fi
    attempts=$((attempts+1))
    sleep 60
    #set -e
done

# This should fail, grab the error message to check later
#$ROOT_DIR/elastic-blast submit --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN || true

# Clean up results
echo Clean up buckets
if ! grep -q '^aws-' $CFG; then
    gsutil -qm rm -r ${ELB_RESULTS}
else
    aws s3 rm ${ELB_RESULTS}/ --recursive
    if ! aws iam get-role --role-name ncbi-elasticblast-janitor-role  >&/dev/null; then
        $ROOT_DIR/elastic-blast delete --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN
    fi
fi

# Do the final error check: this string must be in the logfile
echo Check the error message
grep 'Please resubmit your search with a different value' $logfile || {
    echo "Missing expected error message in log file" ;
    exit 1;
}
