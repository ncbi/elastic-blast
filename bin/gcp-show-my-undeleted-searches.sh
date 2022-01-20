#!/bin/bash
# gcp-show-my-undeleted-searches.sh: This script shows my undeleted searches in
# GCP and their status
#
# Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
# Created: Tue 17 Aug 2021 09:57:27 PM EDT

set -o pipefail
shopt -s nullglob

username=`whoami`
verbose=0

command -v elastic-blast >&/dev/null || { echo "elastic-blast must be in your PATH for this script to work"; exit 1; }

usage() {
    echo -e "$0 [-h] [-u USERNAME] [-v]\n"
    echo -e "This script shows ElasticBLAST searches that have not been deleted on GCP and their status\n"
    echo -e "Options:"
    echo -e "\t-u USERNAME: Show ElasticBLAST searches for user USERNAME (default: $username)"
    echo -e "\t-v: Show verbose output, i.e.: displays your GCP configuration settings"
    echo -e "\t-h: Show this message"
}

check_status() {
    results=$1
    created=$2
    status_file=$3
    now=$(date -u +"%s")
    SECONDS_IN_A_DAY=$((24*60*60))
    if egrep -q '^Your ElasticBLAST search succeeded,' $status_file; then
        case `uname` in 
            Linux)
                created_date=$(date -d "$created" +"%s")
                ;;
            Darwin)
                created_date=$(date -j -f "%F %T" "$created" +"%s")
                ;;
        esac
        if [ $(($now - $created_date)) -gt $SECONDS_IN_A_DAY ]; then
            echo "Please run 'elastic-blast delete --results $results --gcp-project $ELB_GCP_PROJECT --gcp-region $ELB_GCP_REGION --gcp-zone $ELB_GCP_ZONE'"
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

if [ -z "${ELB_GCP_PROJECT}" ]; then
    export ELB_GCP_PROJECT=`gcloud config get-value core/project`
fi
if [ -z "${ELB_GCP_REGION}" ]; then
    export ELB_GCP_REGION=`gcloud config get-value compute/region`
fi
if [ -z "${ELB_GCP_ZONE}" ]; then
    export ELB_GCP_ZONE=`gcloud config get-value compute/zone`
fi

if [ $verbose -eq 1 ]; then 
    echo -n "Account: " ; gcloud config get-value core/account
    echo "Project: $ELB_GCP_PROJECT"
    echo "Region: $ELB_GCP_REGION"
    echo "Zone: $ELB_GCP_ZONE"
fi

TMP=`mktemp -t $(basename -s .sh $0)-XXXXXXX`
STATUS=`mktemp -t $(basename -s .sh $0)-XXXXXXX`
trap " /bin/rm -fr $TMP $STATUS" INT QUIT EXIT HUP KILL ALRM

# User name for label computed as in elastic_blast.elb_config.create_labels
user=$(echo $username | tr '[A-Z-]' '[a-z_]' | tr '.' '-' | cut -b-62)
gcloud container clusters list --filter=resourceLabels.owner=$user --format='value(resourceLabels.results,resourceLabels.created)' | sort > $TMP
[ -s $TMP ] && {
    echo "These are your ElasticBLAST searches on GCP that have not been deleted";
    echo "Please note that the results bucket names below been modified to remove upper case and all '/' characters following 'gs://'";
}

while read -r r c; do 
    results=$(echo $r | sed 's,---,://,')
    created=$(echo $c | sed 's/-/ /3;s/-/:/4;s/-/:/3')
    # FIXME: how to restore original results bucket name?
    #if [[ "$r" =~ "elasticblast-$user" ]]; then
    #    results=$(echo $r | sed "s,---,://,;s,$user,$user/,")
    #fi
    echo "##### Results bucket: $results"
    echo "##### Created: $created UTC"
    #echo "##### Status:"
    #elastic-blast status --results $results | tee $STATUS
    #check_status $results "$created" $STATUS
done < $TMP
