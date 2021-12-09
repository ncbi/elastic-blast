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
# Default exit code for error
ERR_CODE=${2:-1}
ROOT_DIR=${SCRIPT_DIR}/..
export ELB_DONT_DELETE_SETUP_JOBS=1
export BLAST_USAGE_REPORT=false

DRY_RUN=''
#DRY_RUN=--dry-run     # uncomment for debugging
logfile=${3:-elb.log}
rm -f $logfile

cleanup_resources_on_error() {
    set +e
    time $ROOT_DIR/elastic-blast delete --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN
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
set +e
$ROOT_DIR/elastic-blast submit --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN
err_code=$?

if [ $err_code -eq $ERR_CODE ]; then
    exit_code=0
else
    exit_code=1
fi

$ROOT_DIR/elastic-blast delete --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN

exit $exit_code
