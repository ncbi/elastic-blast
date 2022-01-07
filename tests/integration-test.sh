#!/bin/bash
# tests/integration-test.sh: End-to-end ElasticBLAST blast search
#
# Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
# Created: Wed 06 May 2020 06:59:03 AM EDT

SCRIPT_DIR=$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )
set -xeuo pipefail

# All other settings are specified in the config file
CFG=${1:-"${SCRIPT_DIR}/../share/etc/elb-blastn-pdbnt.ini"}
ROOT_DIR=${SCRIPT_DIR}/..
ELB=$ROOT_DIR/elastic-blast
#ELB=elastic-blast
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
    if grep -q '^aws-' $CFG; then
        time $ELB delete --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN
    fi
    exit 1;
}

check_results() {
    db=`awk '/^db/ {print $NF}' $CFG`
    if compgen -G "batch_*$db.out.gz" >/dev/null ; then
        test $(du -a batch_*$db.out.gz | sort -n | head -n 1 | cut -f 1) -gt 0
        # Test validity of compressed archives
        find . -maxdepth 1 -name "batch_*$db.out.gz" -type f -print0 | xargs -0 -P $NTHREADS  -I{} gzip -t {}
        # If output is ASN.1, test its validity
        if grep -q 'outfmt 11' $logfile; then
            find . -maxdepth 1 -name "batch_*$db.out.gz" -type f -print0 | \
                xargs -0 -P $NTHREADS -I{} \
                bash -c "zcat {} | datatool -m /netopt/ncbi_tools64/c++.metastable/src/objects/blast/blast.asn -M /am/ncbiapdata/asn/asn.all -v - -e /dev/null"
        # If output is tabular, extract number of hits, check database
        elif grep -q 'outfmt 7' $logfile; then
            searched_db=`find . -maxdepth 1 -name "batch_*$db.out.gz" -type f -print0 | xargs -0 zcat | awk '/atabase/ {print $NF}' | sort -u`
            if [ "$db" != "$searched_db" ] ; then
                echo "FATAL ERROR: Found mismatched results: configured $db, actual $searched_db"
                exit 1
            fi
            num_hsps=`find . -maxdepth 1 -name "batch_*$db.out.gz" -type f -print0 | xargs -0 zcat | grep -v '^#' | wc -l`
            echo "Number of HSPs found $num_hsps"
            find . -maxdepth 1 -name "batch_*$db.out.gz" -type f -print0 | xargs -0 zcat | \
                awk 'BEGIN{t=0} /hits found/ {t+=$2} END{print "Total hits found", t}'
        elif grep -q 'outfmt 6' $logfile; then
            num_hsps=`find . -maxdepth 1 -name "batch_*$db.out.gz" -type f -print0 | xargs -0 zcat | grep -v '^#' | wc -l`
            echo "Number of HSPs found $num_hsps"
        fi
    else
        echo "ElasticBLAST produced no results"
        exit 1
    fi
}

TMP=`mktemp -t $(basename -s .sh $0)-XXXXXXX`
trap "cleanup_resources_on_error; /bin/rm -f $TMP" INT QUIT HUP KILL ALRM # ERR

rm -fr *.fa *.out.gz elb-*.log batch_list.txt
if [ ! -z "${ELB_TC_BRANCH+x}" ] ; then
    if grep -q ^labels $CFG; then
        sed -i~ -e "s@\(^labels.*\)@\1,branch=$ELB_TC_BRANCH@" $CFG
    else
        sed -i~ -e "/^\[cluster\]/a labels = branch=$ELB_TC_BRANCH" $CFG
    fi
fi
if [ ! -z "${ELB_TC_COMMIT_SHA+x}" ] ; then
    if grep -q ^labels $CFG; then
        sed -i~ -e "s@\(^labels.*\)@\1,commit=$ELB_TC_COMMIT_SHA@" $CFG
    else
        sed -i~ -e "/^\[cluster\]/a labels = commit=$ELB_TC_COMMIT_SHA" $CFG
    fi
fi
$ELB submit --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN

attempts=0
[ ! -z "$DRY_RUN" ] || sleep 10    # Should be enough for the BLAST k8s jobs to get started

while [ $attempts -lt $timeout_minutes ]; do
    exit_code=0
    $ELB status --verbose --exit-code --cfg $CFG $DRY_RUN || exit_code=$?

    # if succeeded or failed - break out of the wait cycle
    [ $exit_code -eq 0 ] || [ $exit_code -eq 1 ] && break

    attempts=$((attempts+1))
    sleep 60
done

export PATH=$PATH:$ROOT_DIR
if [ $exit_code -eq 0 ]; then
    $ROOT_DIR/share/tools/run-report.py --cfg $CFG --results ${ELB_RESULTS} -f csv | tee $run_report
fi

if ! grep -q '^aws-' $CFG; then
    make logs ELB_CLUSTER_NAME=`make -s results2clustername` 2>&1 | tee $logs
    $ELB run-summary --cfg $CFG --loglevel DEBUG --logfile $logfile -o $runsummary_output $DRY_RUN
    # Get query batches
    gsutil -qm cp ${QUERY_BATCHES}/*.fa . || true

    # Get results
    gsutil -qm cp ${ELB_RESULTS}/metadata/* .
    # Logs saved in the process of execution can be no longer available for 'make logs'
    gsutil -qm cp ${ELB_RESULTS}/logs/* .
    gsutil -qm cp ${ELB_RESULTS}/*.out.gz .
else
    $ELB run-summary --cfg $CFG --loglevel DEBUG --logfile $logfile -o $runsummary_output $DRY_RUN
    # Get query batches
    aws s3 cp ${QUERY_BATCHES}/ . --recursive --exclude '*' --include "*.fa" --exclude '*/*'
    # Get results
    aws s3 cp ${ELB_RESULTS}/ . --recursive --exclude '*' --include "*.out.gz" --exclude '*/*'
    # Get backend logs
    aws s3 cp ${ELB_RESULTS}/logs/backends.log ${logs}
    if ! aws iam get-role --role-name ncbi-elasticblast-janitor-role  >&/dev/null; then
        $ELB delete --cfg $CFG --loglevel DEBUG --logfile $logfile $DRY_RUN
    fi
fi

# Test results, unless disabled via environment variable
if [ -z "${DO_NOT_TEST_RESULTS+x}" ] ; then
    exit 0
fi

check_results

if [ -f batch_list.txt ]; then
    nbatches=`cat batch_list.txt | wc -l`
else
    nbatches=`ls -1 *fa | wc -l`
fi
echo There are $nbatches batches
test $nbatches -eq $(ls -1 *.out.gz | wc -l)
test $(du -a -b *.out.gz | sort -n | head -n 1 | cut -f 1) -gt 0
