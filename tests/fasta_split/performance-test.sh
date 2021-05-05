#!/bin/bash
# performance-test.sh: What this script does
#
# Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
# Created: Mon 09 Mar 2020 09:18:03 AM EDT

TEST_FILE=gs://elastic-blast-samples/queries/protein/dark-matter-1M.faa.gz
SCRIPT_DIR=$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )
TEST_BATCH_LENGTH=10000
TEST_NBATCHES=19920

#export PATH=/bin:/usr/bin:/opt/python-all/bin
shopt -s nullglob
set -xeuo pipefail

created=$(date -Iseconds | tr : - | tr "[:upper:]" "[:lower:]")
test_bucket=gs://${USER}-test/performance-test-elastic-blast-fasta-split-script-$created-batches

manifest=`mktemp -t $(basename -s .sh $0)-for-elastic-blast-fasta-split-script-XXXXXXX`
jobs=`mktemp -d`
exit_code=0

cleanup() {
#    find . -type f -name "*.yaml" -delete
    rm -rf ${jobs}
    rm -f ${manifest}
    set +e
    gsutil -qm rm -r ${test_bucket}
    exit $exit_code
}

timeout=${1:-"2m"}
trap "cleanup" INT QUIT EXIT HUP KILL ALRM

find $SCRIPT_DIR -type f -name "*.yaml" -delete 
rm -f ${manifest}
time timeout $timeout fasta_split.py ${TEST_FILE} -l ${TEST_BATCH_LENGTH} -o ${test_bucket} -j ${jobs} -m ${manifest} -t $SCRIPT_DIR/../../src/elb/templates/blast-batch-job.yaml.template
exit_code=$?
# timeout code is either 124 if SIGTERM was sent, 128+9 if SIGKILL, or return code of the program if timeout did not happen
# fasta_split uses 1 to 7 codes to report various errors, so we combine codes to convey this to the user
[ ${TEST_NBATCHES} -eq `find ${jobs} -name "*.yaml" -type f | wc -l` ] || { echo "Mismatch number of generated job files"; exit_code=$((10+exit_code)); }
[ ${TEST_NBATCHES} -eq `wc -l ${manifest} | cut -f 1 -d ' '` ] || { echo "Mismatch number of generated job files"; exit_code=$((20+exit_code)); }
