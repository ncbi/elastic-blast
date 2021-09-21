#!/bin/bash
# tests/integration-test.sh: End-to-end ElasticBLAST blast search
#
# Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
# Created: Wed 06 May 2020 06:59:03 AM EDT

SCRIPT_DIR=$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )
set -euo pipefail

# All other settings are specified in the config file
CFG=${1:-"${SCRIPT_DIR}/../share/etc/elb-blastn-pdbnt.ini"}
ROOT_DIR=${SCRIPT_DIR}/..
QUERY_BATCHES=${ELB_RESULTS}/query_batches
export ELB_DONT_DELETE_SETUP_JOBS=1
export BLAST_USAGE_REPORT=false

DRY_RUN=''
#DRY_RUN=--dry-run     # uncomment for debugging
timeout_minutes=${2:-5}
logfile=${3:-elb.log}
runsummary_output=${4:-elb-run-summary.json}
logs=${5:-k8s.log}
run_report=${6:-elb-run-report.csv}
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
    set +e
    if ! grep -qi gcp $CFG; then
        time $ROOT_DIR/elastic-blast delete --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN
    fi
    exit 1;
}

TMP=`mktemp -t $(basename -s .sh $0)-XXXXXXX`
trap "cleanup_resources_on_error; /bin/rm -f $TMP" INT QUIT HUP KILL ALRM ERR

rm -fr *.fa *.out.gz elb-*.log batch_list.txt
$ROOT_DIR/elastic-blast submit --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN

attempts=0
[ ! -z "$DRY_RUN" ] || sleep 10    # Should be enough for the BLAST k8s jobs to get started

while [ $attempts -lt $timeout_minutes ]; do
    $ROOT_DIR/elastic-blast status --verbose --cfg $CFG $DRY_RUN | tee $TMP

    num_failed=`grep '^Failed ' $TMP | cut -f 2 -d ' '`;
    num_pending=`grep '^Pending ' $TMP | cut -f 2 -d ' '`;
    num_succeeded=`grep '^Succeeded ' $TMP | cut -f 2 -d ' '`;
    num_running=`grep '^Running ' $TMP | cut -f 2 -d ' '`;
    num_jobs=$(($num_failed + $num_pending + $num_succeeded + $num_running))

    [ $num_jobs -eq 0 ] && continue # Jobs have not been submitted yet

    [ $num_failed -gt 0 ] && break  # If there's a failure, break out of the loop

    [ $num_pending -eq 0 ] && [ $num_running -eq 0 ] && break  # ElasticBLAST is done successfully

    attempt=$((attempts+1))
    sleep 60
done

export PATH=$PATH:$ROOT_DIR
$ROOT_DIR/share/tools/run-report.py --cfg $CFG --results ${ELB_RESULTS} -f csv | tee $run_report

if ! grep -qi aws $CFG; then
    make logs 2>&1 | tee $logs
    $ROOT_DIR/elastic-blast run-summary --cfg $CFG --loglevel DEBUG --logfile $logfile -o $runsummary_output $DRY_RUN
    # Get query batches
    gsutil -qm cp ${QUERY_BATCHES}/*.fa . || true

    # Get results
    gsutil -qm cp ${ELB_RESULTS}/metadata/* .
    gsutil -qm cp ${ELB_RESULTS}/*.out.gz .
else
    $ROOT_DIR/elastic-blast run-summary --cfg $CFG --loglevel DEBUG --logfile $logfile -o $runsummary_output $DRY_RUN

    # Get query batches
    aws s3 cp ${QUERY_BATCHES}/ . --recursive --exclude '*' --include "*.fa" --exclude '*/*'
    # Get results
    aws s3 cp ${ELB_RESULTS}/ . --recursive --exclude '*' --include "*.out.gz" --exclude '*/*'
    # Get backend logs
    aws s3 cp ${ELB_RESULTS}/logs/backends.log ${logs}

    $ROOT_DIR/elastic-blast delete --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN
fi

# Test results, unless disabled via environment variable
if [ -z "${DO_NOT_TEST_RESULTS+x}" ] ; then
    exit 0
fi

find . -name "batch*.out.gz" -type f -print0 | \
    xargs -0 -P $NTHREADS  -I{} gzip -t {}
if grep -q 'outfmt 11' $logfile; then
    find . -name "batch*.out.gz" -type f -print0 | \
        xargs -0 -P $NTHREADS -I{} \
        bash -c "zcat {} | datatool -m /netopt/ncbi_tools64/c++.metastable/src/objects/blast/blast.asn -M /am/ncbiapdata/asn/asn.all -v - -e /dev/null"
fi
if [ -f batch_list.txt ]; then
    nbatches=`cat batch_list.txt | wc -l`
else
    nbatches=`ls -1 *fa | wc -l`
fi
echo There are $nbatches batches
test $nbatches -eq $(ls -1 *.out.gz | wc -l)
test $(du -a -b *.out.gz | sort -n | head -n 1 | cut -f 1) -gt 0
