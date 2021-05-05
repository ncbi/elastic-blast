#!/bin/bash
# tc-bash-runner.sh: Facilitates TC reporting of bash scripts
#
# Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
# Created: Wed 06 May 2020 11:45:02 AM EDT

SCRIPT_DIR=$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )
test_suite_name='ElasticBLAST-application-level-tests'
echo "##teamcity[testSuiteStarted name='$test_suite_name'] "

# Default is to run all scripts WITHOUT parameters
test_scripts=$SCRIPT_DIR/*.sh
test_label=
if [ $# -ne 0 ] ; then
    test_scripts=$1
    shift
    # if the next argument ends with "ini", treat it as the ini file,
    # otherwise as additional test label for TC statistics collection
    if [[ $1 != *ini ]] ; then
       test_label="-$1"
       shift
    fi
    script_arguments=$*
fi

for t in $test_scripts; do
    [ $(basename $t) == $(basename ${BASH_SOURCE[0]}) ] && continue
    name=$(basename $t)
    echo "##teamcity[testStarted name='$name' captureStandardOutput='true'] "
    $t $script_arguments || echo "##teamcity[testFailed name='$name'] "
    #awk -f $SCRIPT_DIR/parse-runtimes.awk elb.log | sed "s,\",\',g"
    awk '/ RUNTIME / {printf "##teamcity[buildStatisticValue key=\"%s\" value=\"%f\"]\n", $(NF-2), $(NF-1)}' elb.log | sed "s,\",\',g"
    echo "##teamcity[testFinished name='$name'] "

    if ! [ -z $test_label ] ; then
       cp elb.log ${test_label##-}.log
    fi
done

echo "##teamcity[testSuiteFinished name='$test_suite_name'] "
