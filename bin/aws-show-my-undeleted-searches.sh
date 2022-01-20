#!/bin/bash
# aws-show-my-undeleted-searches.sh: This script shows my undeleted searches in
# AWS and their status
#
# Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
# Created: Sat 07 Aug 2021 11:01:46 AM EDT

set -euo pipefail
shopt -s nullglob

username=`whoami`
verbose=0

command -v elastic-blast >&/dev/null || { echo "elastic-blast must be in your PATH for this script to work"; exit 1; }

usage() {
    echo -e "$0 [-h] [-u USERNAME] [-v]\n"
    echo -e "This script shows ElasticBLAST searches that have not been deleted on AWS and their statusn"
    echo -e "Options:"
    echo -e "\t-u USERNAME: Show ElasticBLAST searches for user USERNAME (default: $username)"
    echo -e "\t-v: Show verbose output, i.e.: displays your AWS user identity"
    echo -e "\t-h: Show this message"
}

check_status() {
    results=$1
    created=$2
    status_file=$3
    now=$(date -u +"%s")
    SECONDS_IN_A_DAY=$((24*60*60))
    if egrep -q '^Your ElasticBLAST search succeeded,|^Pending 0' $status_file; then
        case `uname` in 
            Linux)
                created_date=$(date -d "$created" +"%s")
                ;;
            Darwin)
                created_date=$(date -j -f "%F %T" "$created" +"%s")
                ;;
        esac
        if [ $(($now - $created_date)) -gt $SECONDS_IN_A_DAY ]; then
            echo "Please run 'elastic-blast delete --results $results'"
        fi
    fi
}

while getopts "u:vh" OPT; do
    case $OPT in 
        u) username=${OPTARG}
            ;;
        v) verbose=1
            ;;
        h) usage
           exit 0
            ;;
    esac
done

# User name for label computed as in elastic_blast.elb_config.create_labels
user=$(echo $username | tr '[A-Z-]' '[a-z_]' | tr '.' '-' | cut -b-62)

TMP=`mktemp -t $(basename -s .sh $0)-XXXXXXX`
STATUS=`mktemp -t $(basename -s .sh $0)-XXXXXXX`
trap " /bin/rm -fr $TMP $STATUS" INT QUIT EXIT HUP KILL ALRM

if [ $verbose -eq 1 ]; then 
    echo -n "AWS user identity: ";
    aws sts get-caller-identity --output json | jq -Mr .Arn
fi

aws batch describe-compute-environments --output json | \
    jq -Mr ".computeEnvironments[] | select(.tags.creator==\"$user\") | [ .tags.results, .tags.created ] | @tsv" > $TMP

[ -s $TMP ] && echo "These are your ElasticBLAST searches on AWS that have not been deleted"

while read -r results c; do 
    created=$(echo $c | sed 's/-/ /3;s/-/:/4;s/-/:/3')
    echo "##### Results bucket: $results"
    echo "##### Created: $created UTC"
    echo "##### Status:"
    elastic-blast status --results $results | tee $STATUS
    check_status $results "$created" $STATUS
done < $TMP
echo

# Show also those CloudFormation stacks that failed to delete
aws cloudformation describe-stacks --output json | \
    jq -Mr ".Stacks[] | select( (.StackName|contains(\"$user\")) and (.StackStatus|contains(\"DELETE\")) ) | [ (.Tags[] | select(.Key==\"results\") | .Value), (.Tags[] | select(.Key==\"created\") | .Value), .StackStatus ] | @tsv" > $TMP
[ ! -s $TMP ] && exit

echo "These are your failed CloudFormation stacks, please be sure to delete them with the commands listed below"

while read -r results c status; do 
    created=$(echo $c | sed 's/-/ /3;s/-/:/4;s/-/:/3')
    echo "##### Results bucket: $results"
    echo "##### Created: $created UTC"
    echo "##### Status: $status"
    echo elastic-blast delete --results $results
done < $TMP
