#!/bin/bash
# tests/integration-test-synchronous.sh: End-to-end ElasticBLAST blast search
# using synchronous mode
#
# Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
# Created: Wed 06 May 2020 06:59:03 AM EDT

SCRIPT_DIR=$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )
set -euo pipefail

# All other settings are specified in the config file
CFG=${1:-"${SCRIPT_DIR}/../share/etc/elb-blastn-pdbnt.ini"}
ROOT_DIR=${SCRIPT_DIR}/..
export BLAST_USAGE_REPORT=false

DRY_RUN=''
#DRY_RUN=--dry-run     # uncomment for debugging
timeout_minutes=${2:-10}
logfile=${3:-elb.log}
runsummary_output=${4:-elb-run-summary.json}
logs=${5:-k8s.log}
rm -f $logfile

get_num_cores() {
    retval=1
    if which parallel >&/dev/null; then
        retval=$(parallel --number-of-cores)
    elif [ -f /proc/cpuinfo ] ; then
        retval=$(grep -c '^proc' /proc/cpuinfo)
    elif which lscpu >& /dev/null; then
        retval=$(lscpu -p | grep -v ^# | wc -l)
    elif [ `uname -s` == 'Darwin' ]; then
        retval=$(sysctl -n hw.ncpu)
    fi
    echo $retval
}
NTHREADS=$(get_num_cores)

cleanup_resources_on_error() {
    echo "Previous exit code: $?"
    set +e
    time $ROOT_DIR/elastic-blast delete --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN
    exit 1;
}

TMP=`mktemp -t $(basename -s .sh $0)-XXXXXXX`
trap "cleanup_resources_on_error; /bin/rm -f $TMP" INT QUIT HUP KILL ALRM ERR

rm -fr *.fa *.out.gz elb-*.log
if which timeout >& /dev/null; then
    timeout --preserve-status ${timeout_minutes}m $ROOT_DIR/elastic-blast submit --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN --sync
else
    $ROOT_DIR/elastic-blast submit --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN --sync
fi

if ! grep -qi aws $CFG; then
    make logs 2>&1 | tee $logs
    $ROOT_DIR/elastic-blast run-summary --cfg $CFG --loglevel DEBUG --logfile $logfile -o $runsummary_output $DRY_RUN

    # Get results
    gsutil -qm cp ${ELB_RESULTS}/*.out.gz .
    gsutil -qm cp ${ELB_RESULTS}/metadata/* .
    # Split query is now removed during submit --sync, so all tests with it are unavailable
    # Compare with async version, integration-test.sh

    # Test results
    find . -name "batch*.out.gz" -type f -print0 | \
        xargs -0 -P $NTHREADS  -I{} gzip -t {}
    if grep 'outfmt 11' $logfile; then
        find . -name "batch*.out.gz" -type f -print0 | \
            xargs -0 -P $NTHREADS -I{} \
            bash -c "zcat {} | datatool -m /netopt/ncbi_tools64/c++.metastable/src/objects/blast/blast.asn -M /am/ncbiapdata/asn/asn.all -v - -e /dev/null"
    fi
    test $(du -a -b *.out.gz | sort -n | head -n 1 | cut -f 1) -gt 0
else
    $ROOT_DIR/elastic-blast run-summary --cfg $CFG --loglevel DEBUG --logfile $logfile -o $runsummary_output --write-logs $logs --detailed $DRY_RUN
    # As we have no logs yet we can't check ASN.1 integrity
    # Get results
    aws s3 cp ${ELB_RESULTS}/ . --recursive --exclude '*' --include "*.out.gz" --exclude '*/*'
    # Test results
    find . -name "batch*.out.gz" -type f -print0 | \
        xargs -0 -P $NTHREADS  -I{} gzip -t {}
    test $(du -a -b *.out.gz | sort -n | head -n 1 | cut -f 1) -gt 0
fi
