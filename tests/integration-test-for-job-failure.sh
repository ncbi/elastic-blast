#!/bin/bash
# tests/integration-test-for-job-failure.sh: End-to-end ElasticBLAST blast search
# expecting a job failure
#
# Authors: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
#          Victor Joukov (joukovv@ncbi.nlm.nih.gov)
# Created: Fri 02 Jul 2020 04:01:00 PM EDT

SCRIPT_DIR=$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )
set -euo pipefail

# All other settings are specified in the config file
CFG=${1:-"${SCRIPT_DIR}/../share/etc/elb-aws-blastn-out-of-memory"}
ROOT_DIR=${SCRIPT_DIR}/..
export ELB_DONT_DELETE_SETUP_JOBS=1
export BLAST_USAGE_REPORT=false

DRY_RUN=''
#DRY_RUN=--dry-run     # uncomment for debugging
timeout_minutes=${2:-15}
logfile=${3:-elb.log}
rm -f $logfile

cleanup_resources_on_error() {
    set +e
    if grep -q '^aws' $CFG; then
        time $ROOT_DIR/elastic-blast delete --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN
    fi
    exit 1;
}

TMP=`mktemp -t $(basename -s .sh $0)-XXXXXXX`
trap "cleanup_resources_on_error; /bin/rm -f $TMP" INT QUIT HUP KILL ALRM ERR

rm -fr *.fa *.out.gz elb-*.log
if [ ! -z "${ELB_TC_BRANCH+x}" ] ; then
    if grep -q ^labels $CFG; then
        sed -i~ -e "s@\(^labels.*\)@\1,branch=$ELB_TC_BRANCH@" $CFG
    else
        sed -i~ -e "/^\[cluster\]/a labels = branch=$ELB_TC_BRANCH" $CFG
    fi
fi
$ROOT_DIR/elastic-blast submit --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN

attempts=0
[ ! -z "$DRY_RUN" ] || sleep 10    # Should be enough for the BLAST k8s jobs to get started

while [ $attempts -lt $timeout_minutes ]; do
    $ROOT_DIR/elastic-blast status --verbose --cfg $CFG $DRY_RUN | tee $TMP
    #set +e
    if grep '^Pending 0' $TMP && grep '^Running 0' $TMP; then
        break
    fi
    attempt=$((attempts+1))
    sleep 60
    #set -e
done

if grep '^Failed 0' $TMP; then
    exit_code=1
else
    exit_code=0
fi

if grep -q '^aws' $CFG; then
    if ! aws iam get-role --role-name ncbi-elasticblast-janitor-role  >&/dev/null; then
        $ROOT_DIR/elastic-blast delete --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN
    fi
fi

exit $exit_code
