#!/bin/bash
# bin/gcp-setup-elastic-blast-janitor.sh: Script to set up the ElasticBLAST
# janitor permissions in GCP
#
# Author: Christiam Camacho (camacho@ncbi.nlm.nih.gov)
# Created: Tue 08 Mar 2022 04:53:15 PM EST

set -euo pipefail
shopt -s nullglob

command -v gcloud >&/dev/null || { echo "gcloud must be in your PATH for this script to work"; exit 1; }

user=$(gcloud config get-value account)
prj=$(gcloud config get-value project)

usage() {
    echo -e "$0 [-h] [-u USERNAME] [-p GCP_PROJECT_ID]\n"
    echo -e "This script sets up the permissions to the ElasticBLAST janitor in GCP"
    echo -e "Options:"
    echo -e "\t-u USERNAME: GCP user, group or service account to configure (default: user:$user)"
    echo -e "\t\tFor specific format, please see https://cloud.google.com/sdk/gcloud/reference/projects/add-iam-policy-binding#--member"
    echo -e "\t-p GCP_PROJECT_ID: GCP project ID (default: ${prj})"
    echo -e "\t\tDocumentation: https://cloud.google.com/sdk/gcloud/reference/projects/add-iam-policy-binding#PROJECT_ID"
    echo -e "\t-h: Show this message"
}

while getopts "u:p:h" OPT; do
    case $OPT in 
        u) user=${OPTARG}
            ;;
        p) prj=${OPTARG}
            ;;
        h) usage
           exit 0
            ;;
    esac
done

gcloud projects add-iam-policy-binding ${prj} --member=user:${user} --role=roles/container.admin
